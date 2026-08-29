"""Draft-day dashboard (Checkpoint 3, Task 8).

Snapshot-rendered purely from files — no browser, no network. Shows, at a
glance, everything the plan requires for manual-takeover awareness: mode,
identity, state freshness (with an explicit STALE flag), who is on the
clock, our roster so far, the current top-3 candidates with reasons, the
last verified action, and our next-turn overall.

``render_dashboard`` is a pure function of its inputs (golden-testable);
``build_dashboard`` does the file loading.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from . import board as board_engine
from .audit import AuditLog
from .models import DraftState
from .observer import state_age_ms
from .operator import derive_turn
from .safety import MAX_STATE_AGE_MS, _normalize_alias


def our_next_turn_overall(
    on_clock_overall: int | None,
    our_slot: int | None,
    teams: int,
    rounds: int = 16,
) -> int | None:
    """Smallest overall >= the current on-clock pick that belongs to our slot."""
    if on_clock_overall is None or our_slot is None:
        return None
    for overall in range(on_clock_overall, teams * rounds + 1):
        _, slot = derive_turn(overall, teams)
        if slot == our_slot:
            return overall
    return None


def slot_from_pick_order(pick_order: Sequence[int] | None, team_id: Any) -> int | None:
    if not pick_order or team_id not in pick_order:
        return None
    return list(pick_order).index(team_id) + 1


def _mode_from_audit(audit_events: Sequence[Mapping[str, Any]]) -> str:
    for event in reversed(audit_events):
        if event.get("event") == "operator.init" and event.get("mode"):
            return str(event["mode"])
    return "observe (default)"


def _last_verified_action(audit_events: Sequence[Mapping[str, Any]]) -> str:
    for event in reversed(audit_events):
        if event.get("event") == "actuate.result" and event.get("status") == "submitted":
            return (
                f"{event.get('player')} confirmed at overall "
                f"{event.get('expected_overall')} ({event.get('ts', 'no ts')})"
            )
    return "none"


def render_dashboard(
    *,
    team: str,
    config: Mapping[str, Any],
    state: DraftState,
    board_rows: Sequence[Mapping[str, Any]],
    audit_events: Sequence[Mapping[str, Any]],
    now_ms: int,
    pick_order: Sequence[int] | None = None,
) -> str:
    espn = config.get("espn", {})
    teams = int(config["league"]["teams"])
    team_id = espn.get("team_id")

    age = state_age_ms(state, now_ms)
    stale = age > MAX_STATE_AGE_MS
    freshness_flag = "STALE — manual takeover if drafting" if stale else "FRESH"

    drafted = [p.player for p in state.picks]
    mine = [p for p in state.picks if p.team_id == team_id]

    on_clock = state.on_clock_overall
    if on_clock is not None:
        round_no, _slot = derive_turn(int(on_clock), teams)
        pick_no = (int(on_clock) - 1) % teams + 1
    else:
        round_no, pick_no = 1, 1
    rec = board_engine.recommend(
        board_rows,
        {"drafted": drafted, "my_roster": [p.player for p in mine]},
        config,
        round_no=round_no,
        pick_no=pick_no,
    )

    our_slot = slot_from_pick_order(pick_order, team_id)
    next_turn = our_next_turn_overall(on_clock, our_slot, teams)

    lines: list[str] = []
    lines.append(f"=== fantasy-draft dashboard: {_normalize_alias(team)} ===")
    lines.append(f"mode:        {_mode_from_audit(audit_events)}")
    lines.append(
        "identity:    "
        f"{espn.get('authorized_team')} | league={espn.get('league_id')} "
        f"team={team_id} season={espn.get('season_id')}"
    )
    lines.append(f"state:       age_ms={age} [{freshness_flag}] saved_at={state.saved_at}")
    if on_clock is not None:
        lines.append(
            f"on clock:    team {state.on_clock_team_id} @ overall {on_clock} "
            f"(round {round_no})"
        )
    else:
        lines.append("on clock:    unknown (no scheduled pick in state)")
    lines.append(f"our roster:  {len(mine)} pick(s)")
    for pick in mine:
        lines.append(f"  - overall {pick.overall}: {pick.player} ({pick.position})")
    lines.append("top candidates:")
    for idx, cand in enumerate(rec.candidates[:3], start=1):
        lines.append(
            f"  {idx}. {cand.player} ({cand.position}, tier {cand.tier}) — {cand.reason}"
        )
    if not rec.candidates:
        lines.append("  (no legal candidates on the board)")
    lines.append(f"last verified action: {_last_verified_action(audit_events)}")
    lines.append(
        f"next turn:   overall {next_turn}" if next_turn is not None
        else "next turn:   unknown (draft slot not derivable)"
    )
    return "\n".join(lines)


def build_dashboard(
    *,
    team: str,
    data_dir: str | Path = "data",
    config_path: str | Path | None = None,
    now_ms: int | None = None,
) -> str:
    """Load everything from files and render. No browser, no network."""
    import time

    alias = _normalize_alias(team)
    config = yaml.safe_load(Path(config_path or f"config.{alias}.yaml").read_text())
    state = DraftState.load(data_dir, alias)
    board_path = Path(data_dir) / alias / "board.csv"
    if board_path.exists():
        from .pipeline import load_board

        board_rows: Sequence[Mapping[str, Any]] = load_board(board_path)
    else:
        board_rows = []
    audit_events = AuditLog(data_dir, alias).read_all()
    pick_order = None
    league_settings = Path(data_dir) / "raw" / "league_settings.json"
    if league_settings.exists():
        try:
            raw = json.loads(league_settings.read_text(encoding="utf-8"))
            pick_order = (
                raw.get("settings", {}).get("draftSettings", {}).get("pickOrder")
            )
        except (json.JSONDecodeError, AttributeError):
            pick_order = None
    return render_dashboard(
        team=alias,
        config=config,
        state=state,
        board_rows=board_rows,
        audit_events=audit_events,
        now_ms=now_ms if now_ms is not None else int(time.time() * 1000),
        pick_order=pick_order,
    )
