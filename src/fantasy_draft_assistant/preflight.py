"""Draft-day preflight (Checkpoint 3, Task 9 + CP2 carried feedback 4).

`fantasy-draft preflight --team synaps1` runs every unattended readiness
check and writes a timestamped report to ``data/<team>/preflight_report.json``:

- config + board exist and parse; raw source / board staleness warning when
  older than ``--max-age-hours`` (default 12h — CP2 verdict, LOW).
- identity is complete and exactly allowlisted; RoughRydas refusal
  self-test (Allowlist construction MUST raise PermissionError).
- observed draft-session id derived from ``data/raw/league_settings.json``
  and printed — grants must carry exactly this id (CP2 verdict, MEDIUM).
- optional grant file validated against identity + observed session.
- replay smoke: a generated 3-round DraftScript must complete with every
  one of our picks confirmed, and stay inside the 3000 ms decide budget.

Statuses: ``pass`` / ``warn`` (soft) / ``fail`` (hard; nonzero exit).
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .observer import derive_session_id
from .operator import grant_is_valid, load_grant
from .replay import LATENCY_BUDGET_MS, ReplayRunner, generate_script
from .safety import Allowlist, TeamIdentity, _normalize_alias


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str  # "pass" | "warn" | "fail"
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _age_hours(path: Path, now: float) -> float:
    return (now - path.stat().st_mtime) / 3600.0


def _freshness_check(name: str, path: Path, max_age_hours: float, now: float) -> Check:
    if not path.exists():
        return Check(name, "fail", f"{path} is missing")
    age = _age_hours(path, now)
    if age > max_age_hours:
        return Check(
            name,
            "warn",
            f"{path} is {age:.1f}h old (max {max_age_hours:.0f}h) — refresh before draft",
        )
    return Check(name, "pass", f"{path} is {age:.1f}h old (max {max_age_hours:.0f}h)")


def run_preflight(
    team: str,
    *,
    config_path: str | Path,
    data_dir: str | Path = "data",
    grant_path: str | Path | None = None,
    max_age_hours: float = 12.0,
    now: float | None = None,
) -> dict[str, Any]:
    """Run all checks; write and return the timestamped report dict."""
    alias = _normalize_alias(team)
    data_dir = Path(data_dir)
    now = now if now is not None else time.time()
    now_ms = int(now * 1000)
    checks: list[Check] = []

    # 1. Config exists, parses, and yields a complete identity.
    config: dict[str, Any] | None = None
    identity: TeamIdentity | None = None
    config_path = Path(config_path)
    if not config_path.exists():
        checks.append(Check("config", "fail", f"{config_path} is missing"))
    else:
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            espn = config["espn"]
            identity = TeamIdentity(
                alias=_normalize_alias(espn.get("authorized_team")),
                league_id=espn.get("league_id"),
                team_id=espn.get("team_id"),
                season=espn.get("season_id"),
            )
            if identity.is_complete:
                checks.append(
                    Check(
                        "config",
                        "pass",
                        f"{config_path} ok; identity {identity.normalized_alias} "
                        f"league={identity.league_id} team={identity.team_id} "
                        f"season={identity.season}",
                    )
                )
            else:
                checks.append(
                    Check("config", "fail", f"identity in {config_path} is incomplete")
                )
                identity = None
        except Exception as exc:
            checks.append(
                Check("config", "fail", f"{config_path} unparseable: {type(exc).__name__}")
            )

    # 2. Identity is exactly allowlistable + membership holds.
    if identity is not None:
        try:
            allowlist = Allowlist([identity])
            checks.append(
                Check(
                    "identity-allowlist",
                    "pass" if identity in allowlist else "fail",
                    f"{identity.normalized_alias} exact-matches its allowlist entry",
                )
            )
        except (PermissionError, ValueError) as exc:
            checks.append(Check("identity-allowlist", "fail", str(exc)))

    # 3. RoughRydas refusal self-test: MUST raise at Allowlist construction.
    forbidden = TeamIdentity(
        alias="RoughRydas", league_id=305025860, team_id=1, season=2026
    )
    try:
        Allowlist([forbidden])
        checks.append(
            Check(
                "roughrydas-selftest",
                "fail",
                "CRITICAL: forbidden alias was accepted into an Allowlist",
            )
        )
    except PermissionError:
        checks.append(
            Check(
                "roughrydas-selftest",
                "pass",
                "Allowlist construction raised PermissionError for RoughRydas",
            )
        )

    # 4. Board exists/loads + freshness of board and raw source (feedback 4).
    board_path = data_dir / alias / "board.csv"
    board_rows: list[dict[str, Any]] = []
    if not board_path.exists():
        checks.append(Check("board", "fail", f"{board_path} is missing"))
    else:
        try:
            from .pipeline import load_board

            board_rows = load_board(board_path)
            if board_rows:
                checks.append(Check("board", "pass", f"{board_path}: {len(board_rows)} rows"))
            else:
                checks.append(Check("board", "fail", f"{board_path} has no rows"))
        except Exception as exc:
            checks.append(
                Check("board", "fail", f"{board_path} unparseable: {type(exc).__name__}")
            )
        checks.append(
            _freshness_check("board-freshness", board_path, max_age_hours, now)
        )
    raw_source = data_dir / "raw" / "players.json"
    meta_path = data_dir / alias / "board_meta.json"
    if meta_path.exists():
        try:
            meta_source = json.loads(meta_path.read_text(encoding="utf-8")).get("source")
            if meta_source:
                raw_source = Path(meta_source)
        except json.JSONDecodeError:
            pass
    checks.append(
        _freshness_check("raw-source-freshness", raw_source, max_age_hours, now)
    )

    # 5. Observed draft-session id (grants must name exactly this).
    observed_session_id: str | None = None
    league_settings = data_dir / "raw" / "league_settings.json"
    if league_settings.exists():
        try:
            raw = json.loads(league_settings.read_text(encoding="utf-8"))
            observed_session_id = derive_session_id(raw)
        except json.JSONDecodeError:
            observed_session_id = None
        if observed_session_id is None:
            checks.append(
                Check("draft-session", "warn", f"{league_settings} yielded no session id")
            )
        elif identity is not None and not observed_session_id.startswith(
            f"{identity.league_id}-{identity.season}-"
        ):
            checks.append(
                Check(
                    "draft-session",
                    "fail",
                    f"session {observed_session_id} does not match configured "
                    f"league/season {identity.league_id}/{identity.season}",
                )
            )
        else:
            checks.append(
                Check(
                    "draft-session",
                    "pass",
                    f"observed session id: {observed_session_id} "
                    "(grants must set draft_session_id to exactly this)",
                )
            )
    else:
        checks.append(
            Check(
                "draft-session",
                "warn",
                f"{league_settings} missing — session unknown; refresh league "
                "settings before issuing an autopick grant",
            )
        )

    # 6. Optional grant file validation.
    if grant_path is not None:
        grant = load_grant(grant_path)
        if grant is None:
            checks.append(Check("grant", "fail", f"{grant_path} unreadable/malformed"))
        elif identity is None:
            checks.append(Check("grant", "fail", "cannot validate grant without identity"))
        elif grant_is_valid(grant, identity, now_ms, observed_session_id):
            remaining_min = (grant.expires_at_ms - now_ms) / 60_000
            checks.append(
                Check(
                    "grant",
                    "pass",
                    f"grant valid for session {grant.draft_session_id}; "
                    f"expires in {remaining_min:.0f} min",
                )
            )
        else:
            checks.append(
                Check(
                    "grant",
                    "fail",
                    "grant is expired, mismatched, or not bound to the observed "
                    f"session ({observed_session_id})",
                )
            )

    # 7. Replay smoke (3 rounds) + timing budget.
    if config is not None and board_rows and identity is not None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                script = generate_script(
                    board_rows,
                    Path(tmp) / "smoke.jsonl",
                    rounds=3,
                    our_team_id=identity.team_id,
                    league_id=identity.league_id,
                    season=identity.season,
                    alias=identity.normalized_alias,
                    include_faults=False,
                )
                report = ReplayRunner(config, board_rows).run(script)
            if report.ok:
                checks.append(
                    Check(
                        "replay-smoke",
                        "pass",
                        f"{len(report.our_picks)}/{len(report.expected_our_overalls)} "
                        "picks confirmed in a 3-round unattended replay",
                    )
                )
            else:
                checks.append(
                    Check(
                        "replay-smoke",
                        "fail",
                        f"replay not ok: confirmed={len(report.our_picks)} "
                        f"halts={len(report.halts)} blocked={len(report.blocked)}",
                    )
                )
            checks.append(
                Check(
                    "timing-budget",
                    "pass" if report.max_latency_ms < LATENCY_BUDGET_MS else "fail",
                    f"max observe->recommend {report.max_latency_ms:.1f} ms "
                    f"(budget {LATENCY_BUDGET_MS} ms)",
                )
            )
        except Exception as exc:
            checks.append(
                Check("replay-smoke", "fail", f"replay crashed: {type(exc).__name__}")
            )
    else:
        checks.append(
            Check("replay-smoke", "fail", "skipped: needs valid config, board, identity")
        )

    ok = all(c.status != "fail" for c in checks)
    report_path = data_dir / alias / "preflight_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "team": alias,
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(
            timespec="seconds"
        ),
        "observed_session_id": observed_session_id,
        "max_age_hours": max_age_hours,
        "checks": [c.to_dict() for c in checks],
        "ok": ok,
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    payload["report_path"] = str(report_path)
    return payload
