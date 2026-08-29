"""Unattended end-to-end replay harness (Checkpoint 3, Task 7).

A **DraftScript** is a JSONL file of events, one JSON object per line:

- ``{"type": "league", "league": {...}, "pick_order": [...], "rounds": N}``
  — league snapshot (drives :func:`observer.derive_session_id`) plus the
  draft order (team ids, first round) and round count.
- ``{"type": "identity", "alias": ..., "league_id": ..., "team_id": ...,
  "season": ...}`` — OUR identity. The harness builds the
  :class:`safety.Allowlist` from it, so a forbidden alias (RoughRydas) is
  refused right here with ``PermissionError`` before any state exists.
- ``{"type": "grant", "grant": {...}}`` — ephemeral autopick authorization.
- ``{"type": "snapshot", "draftDetail": {...}}`` — an observed ESPN
  snapshot (may be a duplicate, out-of-order, or deliberately corrupt).
- ``{"type": "clock", "advance_ms": N}`` — simulated time passing.
- ``{"type": "disconnect", "advance_ms": N}`` — connectivity loss: time
  passes with NO snapshots, so state goes stale.
- ``{"type": "act"}`` — attempt observe → recommend → verify_and_submit.

The harness runs with a scripted :class:`actuator.FakeActuator` (never a
real browser) and a simulated ESPN server view used for the fresh pre-click
and confirmation snapshots. It emits a structured :class:`ReplayReport`
with per-pick observe→recommend latencies.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .actuator import FakeActuator, SubmitStatus, verify_and_submit
from .models import DraftState
from .observer import SnapshotError, apply_snapshot, derive_session_id
from .operator import AuthorizationGrant, Mode, Operator, derive_turn
from .safety import Allowlist, TeamIdentity

#: Simulated wall-clock epoch (ms) at which every generated script starts.
BASE_MS = 1_756_400_000_000

#: Timing budget: a newly observed pick must produce a recommendation
#: within this many milliseconds (spec success criterion: 3 seconds).
LATENCY_BUDGET_MS = 3_000

#: Draft order of the real Synaps1 league (settings.draftSettings.pickOrder).
DEFAULT_PICK_ORDER = (5, 2, 6, 1, 3, 8, 7, 9, 10, 11)


@dataclass
class ReplayReport:
    """Structured pass/fail evidence from one unattended replay."""

    our_team_id: int | None = None
    expected_our_overalls: list[int] = field(default_factory=list)
    our_picks: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    halts: list[dict[str, Any]] = field(default_factory=list)
    timings: list[dict[str, Any]] = field(default_factory=list)
    corrupt_rejected: int = 0
    duplicate_noops: int = 0
    total_events: int = 0
    completed: bool = False
    final_picks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def max_latency_ms(self) -> float:
        if not self.timings:
            return 0.0
        return max(t["observe_to_recommend_ms"] for t in self.timings)

    @property
    def ok(self) -> bool:
        """All our expected picks submitted+confirmed, no halts, on budget."""
        confirmed = [p["overall"] for p in self.our_picks if p["status"] == "submitted"]
        return (
            self.completed
            and not self.halts
            and self.expected_our_overalls != []
            and confirmed == self.expected_our_overalls
            and self.max_latency_ms < LATENCY_BUDGET_MS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "completed": self.completed,
            "our_team_id": self.our_team_id,
            "expected_our_overalls": self.expected_our_overalls,
            "our_picks": self.our_picks,
            "blocked": self.blocked,
            "halts": self.halts,
            "corrupt_rejected": self.corrupt_rejected,
            "duplicate_noops": self.duplicate_noops,
            "total_events": self.total_events,
            "max_latency_ms": self.max_latency_ms,
            "timings": self.timings,
        }


class _ReplayActuator(FakeActuator):
    """FakeActuator that also records accepted picks on the simulated server."""

    def __init__(self, runner: "ReplayRunner") -> None:
        super().__init__()
        self._runner = runner

    def submit(self, intent):  # type: ignore[override]
        result = super().submit(intent)
        if result.accepted:
            self._runner._register_submitted(intent)
        return result


class ReplayRunner:
    """Drives observer → operator → verify_and_submit from a DraftScript."""

    def __init__(
        self,
        config: Mapping[str, Any],
        board_rows: Sequence[Mapping[str, Any]],
        *,
        audit: Any = None,
    ) -> None:
        self.config = config
        self.board_rows = list(board_rows)
        self.lookup = {
            r["espn_player_id"]: r
            for r in self.board_rows
            if isinstance(r.get("espn_player_id"), int)
        }
        self.audit = audit
        self.now_ms = BASE_MS
        self.teams = int(config["league"]["teams"])
        self.rounds = 16
        self.schedule: dict[int, int] = {}
        self.made: dict[int, tuple[int, int]] = {}
        self.observed_session_id: str | None = None
        self.identity: TeamIdentity | None = None
        self.allowlist: Allowlist | None = None
        self.grant: AuthorizationGrant | None = None
        self.operator: Operator | None = None
        self.state: DraftState | None = None
        self.actuator = _ReplayActuator(self)
        self.report = ReplayReport()

    # -- simulated ESPN server view -----------------------------------------

    def _register_submitted(self, intent) -> None:
        self.made[intent.expected_overall] = (
            intent.player_id,
            intent.identity.team_id,
        )

    def _render_snapshot(self) -> dict[str, Any]:
        """The server's current full view: made picks + next on-clock slot."""
        picks = [
            {"overallPickNumber": o, "playerId": pid, "teamId": tid}
            for o, (pid, tid) in sorted(self.made.items())
        ]
        total = self.teams * self.rounds
        nxt = next((o for o in range(1, total + 1) if o not in self.made), None)
        if nxt is not None and nxt in self.schedule:
            picks.append(
                {"overallPickNumber": nxt, "playerId": -1, "teamId": self.schedule[nxt]}
            )
        return {"draftDetail": {"picks": picks}}

    # -- event handlers ------------------------------------------------------

    def _rebuild_operator(self) -> None:
        if self.allowlist is None:
            return
        mode = Mode.AUTOPICK if self.grant is not None else Mode.OBSERVE
        self.operator = Operator(
            self.config,
            self.allowlist,
            mode,
            grant=self.grant,
            now_ms=self.now_ms,
            observed_session_id=self.observed_session_id,
            audit=self.audit,
        )

    def _on_league(self, event: Mapping[str, Any]) -> None:
        league = event.get("league") or {}
        self.observed_session_id = derive_session_id(league)
        order = list(event.get("pick_order") or DEFAULT_PICK_ORDER)
        self.teams = len(order)
        self.rounds = int(event.get("rounds", self.rounds))
        for overall in range(1, self.teams * self.rounds + 1):
            round_no, slot = derive_turn(overall, self.teams)
            self.schedule[overall] = order[slot - 1]
        self._rebuild_operator()

    def _on_identity(self, event: Mapping[str, Any]) -> None:
        identity = TeamIdentity(
            alias=event.get("alias"),
            league_id=event.get("league_id"),
            team_id=event.get("team_id"),
            season=event.get("season"),
        )
        # Forbidden identities (RoughRydas) blow up RIGHT HERE, before any
        # draft state exists — Allowlist construction is the hard gate.
        self.allowlist = Allowlist([identity])
        self.identity = identity
        self.report.our_team_id = identity.team_id
        self.state = DraftState(
            team=identity.normalized_alias,
            league_id=identity.league_id,
            season=identity.season,
        )
        self._rebuild_operator()

    def _on_grant(self, event: Mapping[str, Any]) -> None:
        payload = event.get("grant") or {}
        self.grant = AuthorizationGrant(
            alias=str(payload["alias"]),
            league_id=int(payload["league_id"]),
            season=int(payload["season"]),
            draft_session_id=str(payload["draft_session_id"]),
            issued_at_ms=int(payload["issued_at_ms"]),
            expires_at_ms=int(payload["expires_at_ms"]),
        )
        self._rebuild_operator()

    def _on_snapshot(self, event: Mapping[str, Any], note: str) -> None:
        if self.state is None:
            raise ValueError("snapshot event before identity event")
        try:
            new_state, events = apply_snapshot(
                self.state, event, self.now_ms, self.lookup
            )
        except SnapshotError as exc:
            self.report.corrupt_rejected += 1
            self.report.blocked.append(
                {
                    "on_clock": self.state.on_clock_overall,
                    "reason": f"corrupt snapshot rejected, state untouched ({exc})",
                    "note": note,
                }
            )
            return
        if not events:
            self.report.duplicate_noops += 1
        self.state = new_state
        for pick in new_state.picks:
            if pick.player_id is not None and pick.team_id is not None:
                self.made.setdefault(pick.overall, (pick.player_id, pick.team_id))

    def _on_act(self, note: str) -> None:
        if self.operator is None or self.state is None or self.identity is None:
            return
        overall = self.state.on_clock_overall
        our_turn = (
            overall is not None
            and self.state.on_clock_team_id == self.identity.team_id
        )
        if our_turn and any(
            p["overall"] == overall and p["status"] == "submitted"
            for p in self.report.our_picks
        ):
            return  # already confirmed this pick (e.g. out-of-order resend)

        round_no, slot = (None, None)
        if overall is not None:
            round_no, slot = derive_turn(int(overall), self.teams)

        # observe → recommend latency, measured on every attempt.
        started = time.perf_counter()
        if round_no is not None:
            self.operator.decide(
                self.state, self.board_rows, round_no, slot, self.now_ms
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        if our_turn:
            self.report.timings.append(
                {"overall": overall, "observe_to_recommend_ms": latency_ms}
            )

        outcome = verify_and_submit(
            self.operator,
            self.actuator,
            self.state,
            self.board_rows,
            round_no,
            slot,
            fetch_snapshot=self._render_snapshot,
            now_fn=lambda: self.now_ms,
            player_lookup=self.lookup,
            audit=self.audit,
        )
        if outcome.status is SubmitStatus.SUBMITTED:
            self.report.our_picks.append(
                {
                    "overall": outcome.intent.expected_overall,
                    "player": outcome.intent.player_name,
                    "player_id": outcome.intent.player_id,
                    "status": "submitted",
                    "reason": outcome.reason,
                }
            )
            # Re-sync our local state from the confirming server view.
            self.state, _ = apply_snapshot(
                self.state, self._render_snapshot(), self.now_ms, self.lookup
            )
        elif outcome.status is SubmitStatus.BLOCKED:
            self.report.blocked.append(
                {"on_clock": overall, "reason": outcome.reason, "note": note}
            )
        else:  # HALT — manual takeover; the harness records and moves on.
            self.report.halts.append(
                {"on_clock": overall, "reason": outcome.reason, "note": note}
            )

    # -- main loop -----------------------------------------------------------

    def run(self, script_path: str | Path) -> ReplayReport:
        lines = Path(script_path).read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            kind = event.get("type")
            note = str(event.get("note", ""))
            self.report.total_events += 1
            if kind == "league":
                self._on_league(event)
            elif kind == "identity":
                self._on_identity(event)
            elif kind == "grant":
                self._on_grant(event)
            elif kind in ("clock", "disconnect"):
                self.now_ms += int(event.get("advance_ms", 0))
            elif kind == "snapshot":
                self._on_snapshot(event, note)
            elif kind == "act":
                self._on_act(note)
            else:
                raise ValueError(f"unknown DraftScript event type: {kind!r}")
        self.report.completed = True
        if self.identity is not None and self.schedule:
            self.report.expected_our_overalls = [
                o
                for o in sorted(self.schedule)
                if self.schedule[o] == self.identity.team_id
            ]
        if self.state is not None:
            self.report.final_picks = [p.to_dict() for p in self.state.picks]
        return self.report


# ---------------------------------------------------------------------------
# Script generation (pure; used by tests, `fantasy-draft replay --generate`
# and the preflight smoke run)
# ---------------------------------------------------------------------------

def generate_script(
    board_rows: Sequence[Mapping[str, Any]],
    out_path: str | Path,
    *,
    rounds: int = 16,
    our_team_id: int = 2,
    pick_order: Sequence[int] = DEFAULT_PICK_ORDER,
    league_id: int = 305025860,
    season: int = 2026,
    alias: str = "synaps1",
    base_ms: int = BASE_MS,
    include_faults: bool = True,
) -> Path:
    """Write a complete snake-draft DraftScript covering every harness proof.

    Opponents mostly draft synthetic (off-board) players; the very first
    opponent snipes our best board player to prove drafted players leave the
    recommendation pool. With ``include_faults`` the script also injects
    duplicate snapshots, one out-of-order resend, one disconnect right before
    our turn, and one corrupt snapshot (red → green recovery).
    """
    teams = len(pick_order)
    total = teams * rounds
    draft_date_ms = base_ms - 3_600_000
    session_id = f"{league_id}-{season}-{draft_date_ms}"

    schedule: dict[int, int] = {}
    for overall in range(1, total + 1):
        round_no, slot = derive_turn(overall, teams)
        schedule[overall] = pick_order[slot - 1]
    our_overalls = [o for o in sorted(schedule) if schedule[o] == our_team_id]

    top_board = max(
        (r for r in board_rows if isinstance(r.get("espn_player_id"), int)),
        key=lambda r: float(r.get("projection", 0.0)),
    )

    events: list[dict[str, Any]] = [
        {
            "type": "league",
            "league": {
                "id": league_id,
                "seasonId": season,
                "settings": {"draftSettings": {"date": draft_date_ms}},
                "draftDetail": {"drafted": False, "inProgress": True},
            },
            "pick_order": list(pick_order),
            "rounds": rounds,
        },
        {
            "type": "identity",
            "alias": alias,
            "league_id": league_id,
            "team_id": our_team_id,
            "season": season,
        },
        {
            "type": "grant",
            "grant": {
                "alias": alias,
                "league_id": league_id,
                "season": season,
                "draft_session_id": session_id,
                "issued_at_ms": base_ms - 60_000,
                "expires_at_ms": base_ms + 6 * 3_600_000,
            },
        },
    ]

    opponent_made: dict[int, tuple[int, int]] = {}

    def snapshot_event(note: str = "") -> dict[str, Any]:
        """Opponent picks so far + the current on-clock slot (ours omitted:
        the harness's own submitted picks live in local state, exactly like
        ESPN including them in later snapshots)."""
        picks = [
            {"overallPickNumber": o, "playerId": pid, "teamId": tid}
            for o, (pid, tid) in sorted(opponent_made.items())
        ]
        made_or_ours = set(opponent_made) | {
            o for o in our_overalls if o < next_overall
        }
        nxt = next((o for o in range(1, total + 1) if o not in made_or_ours), None)
        if nxt is not None:
            picks.append(
                {"overallPickNumber": nxt, "playerId": -1, "teamId": schedule[nxt]}
            )
        event: dict[str, Any] = {"type": "snapshot", "draftDetail": {"picks": picks}}
        if note:
            event["note"] = note
        return event

    next_overall = 1
    events.append(snapshot_event("initial board"))
    stashed_old_snapshot: dict[str, Any] | None = None
    our_turn_index = 0

    for overall in range(1, total + 1):
        next_overall = overall
        team = schedule[overall]
        if team == our_team_id:
            our_turn_index += 1
            events.append({"type": "clock", "advance_ms": 500})
            if include_faults and our_turn_index == 2:
                # Red: disconnect makes state stale -> submission blocked.
                events.append({"type": "disconnect", "advance_ms": 5_000})
                events.append({"type": "act", "note": "act-during-disconnect"})
                # Green: a fresh snapshot restores freshness -> pick goes in.
                events.append(snapshot_event("reconnect refresh"))
            events.append({"type": "act", "note": f"our turn overall {overall}"})
            next_overall = overall + 1
        else:
            if overall == 1:
                pid = int(top_board["espn_player_id"])  # snipe our top player
            else:
                pid = 900_000 + overall  # synthetic off-board opponent pick
            opponent_made[overall] = (pid, team)
            next_overall = overall + 1
            events.append({"type": "clock", "advance_ms": 700})
            if include_faults and overall == 24:
                # Red: corrupt snapshot must be rejected with state untouched.
                events.append(
                    {"type": "snapshot", "draftDetail": None, "note": "corrupt"}
                )
                events.append({"type": "act", "note": "act-after-corrupt"})
            good = snapshot_event(f"after opponent pick {overall}")
            events.append(good)
            if include_faults and overall % 13 == 0:
                events.append(
                    {**good, "note": f"duplicate resend of pick {overall}"}
                )
            if include_faults and overall == 30 and stashed_old_snapshot is not None:
                events.append({**stashed_old_snapshot, "note": "out-of-order resend"})
                events.append({**good, "note": "converge after out-of-order"})
            if include_faults and overall == 27:
                stashed_old_snapshot = good

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")
    return path
