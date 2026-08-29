"""Live run loop glue for ``fantasy-draft run`` (LIVE checkpoint).

Architecture: an external read-only poller (``scripts/espn_poll.mjs``) writes
mDraftDetail-shaped league snapshots to ``data/<team>/snapshots/<epoch_ms>.json``.
This module never touches the browser itself:

- :func:`newest_snapshot` finds the newest snapshot file (timestamp taken
  from the filename; unparseable names fall back to mtime).
- :class:`LiveSession.iterate` is the per-snapshot step, fully testable with
  fixture payloads and a :class:`~.actuator.FakeActuator`:
  apply_snapshot -> persist dashboard state -> recommend on our turn
  (advisory+) -> guarded verify_and_submit (autopick with a valid grant).
- ALL existing guards apply unchanged (Blocked/HALT semantics). A HALT
  prints a loud manual-takeover banner and drops the session to ADVISORY
  permanently — autopick can never resume within the session.
- The freshness clock is honest: snapshots are applied with their OWN
  timestamp, so a stale snapshot file blocks submission via ``can_submit``.
- At most ONE submit attempt per on-clock overall pick, ever (no blind
  retries across poll iterations).
- :class:`SubprocessActuator` is the only real-world actuator: it shells out
  to ``node scripts/espn_actuate.mjs '<payload>' --grant-file G --live`` and
  maps a nonzero exit code to a rejected submit.

:func:`run_live` is the long-running loop; it exits cleanly on draft
completion, SIGINT, or HALT+advisory when stdin is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .actuator import (
    BrowserActuator,
    Outcome,
    SubmitIntent,
    SubmitResult,
    SubmitStatus,
    verify_and_submit,
)
from .audit import AuditLog
from .models import DraftState, _validate_alias
from .observer import SnapshotError, apply_snapshot, derive_session_id, state_age_ms
from .operator import AuthorizationGrant, Mode, Operator, derive_turn, load_grant
from .safety import MAX_STATE_AGE_MS, Allowlist, TeamIdentity, _normalize_alias

DEFAULT_ROUNDS = 16
SNAPSHOT_DIRNAME = "snapshots"

HALT_BANNER = "\n".join(
    [
        "!" * 72,
        "!!  MANUAL TAKEOVER REQUIRED — AUTOMATION HALTED                      !!",
        "!!  A submit attempt could not be verified. NO retry will happen.     !!",
        "!!  Make your pick BY HAND in the ESPN draft room NOW.                !!",
        "!!  This session is permanently downgraded to ADVISORY.               !!",
        "!" * 72,
    ]
)


class RunStatus(Enum):
    """Outcome of one loop iteration (pure data; the loop decides I/O)."""

    SNAPSHOT_ERROR = "snapshot-error"
    OBSERVED = "observed"
    ADVISED = "advised"
    SUBMITTED = "submitted"
    BLOCKED = "blocked"
    HALTED = "halted"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class IterationResult:
    """What one iteration decided, plus the lines the loop should print."""

    status: RunStatus
    messages: tuple[str, ...] = ()
    outcome: Outcome | None = None


# ---------------------------------------------------------------------------
# Snapshot files
# ---------------------------------------------------------------------------

def snapshot_timestamp_ms(path: Path) -> int:
    """Epoch-ms timestamp of a snapshot file: filename stem, else mtime."""
    try:
        value = int(path.stem)
        if value > 0:
            return value
    except ValueError:
        pass
    return int(path.stat().st_mtime * 1000)


def newest_snapshot(snapshot_dir: str | Path) -> tuple[Path, int] | None:
    """(path, epoch_ms) of the newest snapshot JSON, or None when empty."""
    directory = Path(snapshot_dir)
    if not directory.is_dir():
        return None
    best: tuple[Path, int] | None = None
    for path in directory.glob("*.json"):
        try:
            ts = snapshot_timestamp_ms(path)
        except OSError:
            continue
        if best is None or ts > best[1]:
            best = (path, ts)
    return best


def draft_complete(payload: Mapping[str, Any], teams: int, rounds: int) -> bool:
    """True when ESPN says the draft is done or every pick has been made."""
    detail = payload.get("draftDetail")
    if not isinstance(detail, Mapping):
        return False
    if detail.get("drafted") is True:
        return True
    picks = detail.get("picks")
    if not isinstance(picks, list):
        return False
    made = sum(
        1
        for p in picks
        if isinstance(p, Mapping)
        and isinstance(p.get("playerId"), int)
        and p["playerId"] > 0
    )
    return made >= teams * rounds


# ---------------------------------------------------------------------------
# Real-world actuator (subprocess boundary)
# ---------------------------------------------------------------------------

class SubprocessActuator:
    """Submits one pick by invoking the node CDP actuator script.

    Nonzero exit code (or any spawn failure) maps to a rejected
    :class:`SubmitResult`, which ``verify_and_submit`` turns into HALT —
    never a retry.
    """

    def __init__(
        self,
        grant_file: str | Path,
        script: str | Path = Path("scripts") / "espn_actuate.mjs",
        timeout_s: float = 30.0,
        runner: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    ) -> None:
        self.grant_file = str(grant_file)
        self.script = str(script)
        self.timeout_s = timeout_s
        self._runner = runner

    def build_command(self, intent: SubmitIntent) -> list[str]:
        payload = json.dumps(
            {
                "playerId": intent.player_id,
                "playerName": intent.player_name,
                "leagueId": intent.identity.league_id,
                "teamId": intent.identity.team_id,
            }
        )
        return [
            "node",
            self.script,
            payload,
            "--grant-file",
            self.grant_file,
            "--live",
        ]

    def submit(self, intent: SubmitIntent) -> SubmitResult:
        try:
            proc = self._runner(
                self.build_command(intent),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return SubmitResult(
                accepted=False, detail=f"actuator spawn failed: {type(exc).__name__}"
            )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            return SubmitResult(
                accepted=False,
                detail=f"exit {proc.returncode}: {output[-400:] or 'no output'}",
            )
        return SubmitResult(accepted=True, detail=output[-400:])


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class LiveSession:
    """State machine for the live loop. All side effects are injectable."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        team: str,
        data_dir: str | Path,
        mode: Mode,
        board_rows: Sequence[Mapping[str, Any]],
        actuator: BrowserActuator,
        grant: AuthorizationGrant | None = None,
        audit: AuditLog | None = None,
        rounds: int | None = None,
    ) -> None:
        self.config = config
        self.team = _validate_alias(team)
        self.data_dir = Path(data_dir)
        self.requested_mode = mode
        self.grant = grant
        self.actuator = actuator
        self.board_rows = list(board_rows)
        self.lookup = {
            r["espn_player_id"]: r
            for r in self.board_rows
            if isinstance(r.get("espn_player_id"), int)
        }
        espn = config["espn"]
        self.identity = TeamIdentity(
            alias=_normalize_alias(espn.get("authorized_team")),
            league_id=espn.get("league_id"),
            team_id=espn.get("team_id"),
            season=espn.get("season_id"),
        )
        # Hard identity gate: forbidden/incomplete identities raise here,
        # before any loop iteration can run.
        self.allowlist = Allowlist([self.identity])
        self.audit = audit if audit is not None else AuditLog(data_dir, self.team)
        self.teams = int(config["league"]["teams"])
        self.rounds = int(
            rounds if rounds is not None else config["league"].get("rounds", DEFAULT_ROUNDS)
        )
        self.state = DraftState.load(
            data_dir,
            self.team,
            league_id=self.identity.league_id,
            season=self.identity.season,
        )
        self.halted = False
        self.observed_session_id: str | None = None
        self.operator: Operator | None = None
        self.attempted_overalls: set[int] = set()
        self._last_advised_overall: int | None = None

    # -- helpers -------------------------------------------------------------

    def _rebuild_operator(self, now_ms: int) -> Operator:
        mode = self.requested_mode
        if self.halted and mode is Mode.AUTOPICK:
            mode = Mode.ADVISORY  # permanent downgrade for this session
        self.operator = Operator(
            self.config,
            self.allowlist,
            mode,
            grant=self.grant,
            now_ms=now_ms,
            observed_session_id=self.observed_session_id,
            audit=self.audit,
        )
        return self.operator

    def _halt(self) -> None:
        """Permanently drop autopick for the rest of the session."""
        self.halted = True
        self.operator = None  # rebuilt (capped at ADVISORY) next iteration

    def _format_recommendation(self, rec: Any, round_no: int) -> list[str]:
        lines = [f"OUR TURN (round {round_no}, overall {self.state.on_clock_overall}):"]
        for idx, cand in enumerate(rec.candidates[:3], start=1):
            tag = "PICK " if idx == 1 else f"alt {idx - 1}"
            lines.append(
                f"  {tag}: {cand.player} ({cand.position}, tier {cand.tier}) — {cand.reason}"
            )
        if not rec.candidates:
            lines.append("  (no legal candidates on the board)")
        return lines

    # -- the iteration -------------------------------------------------------

    def iterate(
        self,
        payload: Mapping[str, Any],
        snapshot_ts_ms: int,
        now_ms: int,
        fetch_snapshot: Callable[[], Mapping[str, Any]] | None = None,
    ) -> IterationResult:
        """One loop step. Pure decisions; file writes limited to state+audit.

        ``snapshot_ts_ms`` is the snapshot's OWN timestamp (poller filename),
        so freshness guards compare it against ``now_ms`` honestly — a stale
        snapshot file can never look fresh just because we read it late.
        """
        messages: list[str] = []

        # 1. Observe: reduce the snapshot into state (fail closed on garbage).
        session_id = derive_session_id(payload)
        if session_id != self.observed_session_id:
            self.observed_session_id = session_id
            self.operator = None
        try:
            new_state, events = apply_snapshot(
                self.state, payload, snapshot_ts_ms, self.lookup
            )
        except SnapshotError as exc:
            self.audit.log("run.snapshot_error", detail=str(exc))
            return IterationResult(
                RunStatus.SNAPSHOT_ERROR,
                (f"snapshot rejected (state untouched): {exc}",),
            )
        self.state = new_state
        self.state.save(self.data_dir)  # dashboard reads this file
        for event in events:
            messages.append(
                f"pick {event.overall}: {event.player} (team {event.team_id})"
                + (" [corrected]" if event.kind == "corrected" else "")
            )
            self.audit.log(
                "run.observed",
                kind=event.kind,
                overall=event.overall,
                player=event.player,
                espn_team_id=event.team_id,
            )

        if self.operator is None:
            self._rebuild_operator(now_ms)
        operator = self.operator
        assert operator is not None

        # 2. Draft over?
        if draft_complete(payload, self.teams, self.rounds):
            self.audit.log("run.complete", picks=len(self.state.picks))
            messages.append("draft complete — all picks made")
            return IterationResult(RunStatus.COMPLETE, tuple(messages))

        # 3. Not our turn, or observe-only mode: nothing more to do.
        if (
            self.state.on_clock_team_id != self.identity.team_id
            or self.state.on_clock_overall is None
            or operator.mode is Mode.OBSERVE
        ):
            return IterationResult(RunStatus.OBSERVED, tuple(messages))

        # 4. Our turn, advisory or better: always surface a recommendation.
        overall = int(self.state.on_clock_overall)
        round_no, slot = derive_turn(overall, self.teams)
        rec = operator.decide(self.state, self.board_rows, round_no, slot, now_ms)
        if overall != self._last_advised_overall:
            self._last_advised_overall = overall
            messages.extend(self._format_recommendation(rec, round_no))
            self.audit.log(
                "run.recommendation",
                overall=overall,
                round=round_no,
                primary=rec.primary.player if rec.primary else None,
                fallbacks=[c.player for c in rec.candidates[1:3]],
            )
        age = state_age_ms(self.state, now_ms)
        if age > MAX_STATE_AGE_MS:
            messages.append(
                f"WARNING: snapshot is stale (age_ms={age}) — submission blocked"
            )

        # 5. Autopick (never after a HALT, never twice for the same overall).
        if self.halted or operator.mode is not Mode.AUTOPICK:
            return IterationResult(RunStatus.ADVISED, tuple(messages))
        if overall in self.attempted_overalls:
            messages.append(
                f"overall {overall} already attempted this session — no retry"
            )
            return IterationResult(RunStatus.ADVISED, tuple(messages))

        outcome = verify_and_submit(
            operator,
            self.actuator,
            self.state,
            self.board_rows,
            round_no,
            slot,
            fetch_snapshot if fetch_snapshot is not None else (lambda: payload),
            now_fn=lambda: now_ms,
            player_lookup=self.lookup,
            audit=self.audit,
        )
        if outcome.submit_calls > 0:
            self.attempted_overalls.add(overall)
        if outcome.status is SubmitStatus.SUBMITTED:
            messages.append(f"SUBMITTED + VERIFIED: {outcome.reason}")
            return IterationResult(RunStatus.SUBMITTED, tuple(messages), outcome)
        if outcome.status is SubmitStatus.BLOCKED:
            messages.append(f"submission blocked: {outcome.reason}")
            return IterationResult(RunStatus.BLOCKED, tuple(messages), outcome)
        # HALT: loud banner + permanent advisory downgrade.
        self._halt()
        self.audit.log("run.halt", reason=outcome.reason)
        messages.append(HALT_BANNER)
        messages.append(f"halt reason: {outcome.reason}")
        return IterationResult(RunStatus.HALTED, tuple(messages), outcome)


# ---------------------------------------------------------------------------
# The long-running loop
# ---------------------------------------------------------------------------

def _stdin_interactive() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):
        return False


def _load_board_rows(data_dir: Path, team: str) -> list[dict[str, Any]]:
    from .pipeline import load_board

    board_path = data_dir / team / "board.csv"
    if not board_path.exists():
        raise SystemExit(
            f"no board at {board_path} — run `fantasy-draft build-board --team {team}` first"
        )
    return load_board(board_path)


def run_live(
    *,
    team: str,
    config_path: str | Path | None = None,
    data_dir: str | Path = "data",
    mode: str = "observe",
    grant_path: str | Path | None = None,
    poll_ms: int = 2000,
    snapshot_dir: str | Path | None = None,
) -> int:
    """The ``fantasy-draft run`` loop. Returns a process exit code."""
    import yaml

    alias = _validate_alias(team)
    data = Path(data_dir)
    config = yaml.safe_load(
        Path(config_path or f"config.{alias}.yaml").read_text(encoding="utf-8")
    )
    requested = Mode(mode)
    grant = load_grant(grant_path) if grant_path else None
    if requested is Mode.AUTOPICK and grant is None:
        print("no valid grant loaded — capping at advisory (fail closed)")

    snap_dir = Path(snapshot_dir) if snapshot_dir else data / alias / SNAPSHOT_DIRNAME
    board_rows = _load_board_rows(data, alias)

    if requested is Mode.AUTOPICK and grant_path is not None:
        actuator: BrowserActuator = SubprocessActuator(grant_file=grant_path)
    else:
        # Observe/advisory can never click; a rejected-everything actuator
        # keeps the fail-closed invariant even if modes are mishandled.
        class _NeverActuator:
            def submit(self, intent: SubmitIntent) -> SubmitResult:
                return SubmitResult(accepted=False, detail="no actuator in this mode")

        actuator = _NeverActuator()

    session = LiveSession(
        config,
        team=alias,
        data_dir=data,
        mode=requested,
        board_rows=board_rows,
        actuator=actuator,
        grant=grant,
    )
    session.audit.log(
        "run.start", mode=requested.value, snapshot_dir=str(snap_dir), poll_ms=poll_ms
    )
    print(
        f"run loop: team={alias} mode={requested.value} "
        f"snapshots={snap_dir} poll={poll_ms}ms (Ctrl-C to stop)"
    )

    def fetch_fresh() -> Mapping[str, Any]:
        """Wait briefly for a NEWER snapshot; used by verify_and_submit."""
        start = newest_snapshot(snap_dir)
        deadline = time.monotonic() + max(3 * poll_ms, 3000) / 1000.0
        while time.monotonic() < deadline:
            found = newest_snapshot(snap_dir)
            if found is not None and (start is None or found[1] > start[1]):
                return json.loads(found[0].read_text(encoding="utf-8"))
            time.sleep(min(poll_ms, 250) / 1000.0)
        if start is None:
            raise SnapshotError("no snapshot available from poller")
        return json.loads(start[0].read_text(encoding="utf-8"))

    last_ts: int | None = None
    try:
        while True:
            found = newest_snapshot(snap_dir)
            if found is None:
                print(f"waiting for snapshots in {snap_dir} ...")
            else:
                path, ts = found
                if ts != last_ts:
                    last_ts = ts
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        print(f"snapshot unreadable, skipping: {exc}")
                        payload = None
                    if payload is not None:
                        result = session.iterate(
                            payload, ts, int(time.time() * 1000), fetch_fresh
                        )
                        for line in result.messages:
                            print(line)
                        if result.status is RunStatus.COMPLETE:
                            print("run loop: draft complete — exiting")
                            return 0
            if session.halted and not _stdin_interactive():
                print(
                    "run loop: HALT with no interactive stdin — exiting to "
                    "force manual takeover"
                )
                return 1
            time.sleep(poll_ms / 1000.0)
    except KeyboardInterrupt:
        print("\nrun loop: SIGINT — exiting cleanly")
        session.audit.log("run.stop", reason="sigint")
        return 0
