"""Dashboard tests (Checkpoint 3, Task 8): snapshot/golden render from
files only, with an explicit STALE flag and per-team audit sourcing."""

import pytest

from fantasy_draft_assistant.dashboard import (
    build_dashboard,
    our_next_turn_overall,
    render_dashboard,
    slot_from_pick_order,
)
from fantasy_draft_assistant.models import DraftState
from fantasy_draft_assistant.observer import apply_snapshot

from test_operator import BOARD, CONFIG, LEAGUE, LOOKUP, NOW, SEASON, TEAM, slot_entry

PICK_ORDER = [5, 2, 6, 1, 3, 8, 7, 9, 10, 11]

AUDIT_EVENTS = [
    {"event": "operator.init", "mode": "advisory", "ts": "2026-08-29T21:58:00+00:00"},
    {
        "event": "actuate.result",
        "status": "submitted",
        "player": "Jahmyr Gibbs",
        "expected_overall": 2,
        "ts": "2026-08-29T22:01:30+00:00",
    },
]


def make_state():
    state = DraftState(team="synaps1", league_id=LEAGUE, season=SEASON)
    snap = {
        "draftDetail": {
            "picks": [
                slot_entry(1, 5, 104),      # Josh Allen to team 5
                slot_entry(2, TEAM, 101),   # Gibbs to us
                slot_entry(3, 6),           # team 6 on the clock
            ]
        }
    }
    state, _ = apply_snapshot(state, snap, NOW, LOOKUP)
    state.saved_at = "2026-08-29T22:01:31+00:00"
    return state


GOLDEN = """\
=== fantasy-draft dashboard: synaps1 ===
mode:        advisory
identity:    Synaps1 | league=305025860 team=2 season=2026
state:       age_ms=1500 [FRESH] saved_at=2026-08-29T22:01:31+00:00
on clock:    team 6 @ overall 3 (round 1)
our roster:  1 pick(s)
  - overall 2: Jahmyr Gibbs (RB)
top candidates:
  1. Puka Nacua (WR, tier 1) — fills open starting WR slot
  2. Bijan Robinson (RB, tier 1) — best projection available (348 pts)
last verified action: Jahmyr Gibbs confirmed at overall 2 (2026-08-29T22:01:30+00:00)
next turn:   overall 19"""


class TestGoldenRender:
    def test_snapshot_output_matches_golden(self):
        text = render_dashboard(
            team="synaps1",
            config=CONFIG,
            state=make_state(),
            board_rows=BOARD,
            audit_events=AUDIT_EVENTS,
            now_ms=NOW + 1500,
            pick_order=PICK_ORDER,
        )
        assert text == GOLDEN

    def test_stale_state_is_flagged_loudly(self):
        text = render_dashboard(
            team="synaps1",
            config=CONFIG,
            state=make_state(),
            board_rows=BOARD,
            audit_events=[],
            now_ms=NOW + 60_000,
            pick_order=PICK_ORDER,
        )
        assert "STALE — manual takeover if drafting" in text
        assert "mode:        observe (default)" in text
        assert "last verified action: none" in text


class TestTurnMath:
    def test_slot_from_pick_order(self):
        assert slot_from_pick_order(PICK_ORDER, 2) == 2
        assert slot_from_pick_order(PICK_ORDER, 999) is None
        assert slot_from_pick_order(None, 2) is None

    @pytest.mark.parametrize(
        "on_clock,expected",
        [(1, 2), (2, 2), (3, 19), (19, 19), (20, 22), (159, 159), (160, None)],
    )
    def test_our_next_turn_overall(self, on_clock, expected):
        assert our_next_turn_overall(on_clock, 2, 10) == expected

    def test_unknown_inputs_give_none(self):
        assert our_next_turn_overall(None, 2, 10) is None
        assert our_next_turn_overall(5, None, 10) is None


class TestFileRender:
    def test_build_dashboard_reads_files_only(self, tmp_path):
        # Per-team files in an isolated data dir; no browser, no network.
        import json

        from fantasy_draft_assistant.audit import AuditLog

        config_path = tmp_path / "config.synaps1.yaml"
        import yaml

        config_path.write_text(yaml.safe_dump(CONFIG))
        state = make_state()
        state.save(tmp_path)
        AuditLog(tmp_path, "synaps1").log("operator.init", mode="observe")
        (tmp_path / "raw").mkdir()
        (tmp_path / "raw" / "league_settings.json").write_text(
            json.dumps(
                {"settings": {"draftSettings": {"pickOrder": PICK_ORDER}}}
            )
        )
        text = build_dashboard(
            team="synaps1",
            data_dir=tmp_path,
            config_path=config_path,
            now_ms=NOW + 1000,
        )
        assert "=== fantasy-draft dashboard: synaps1 ===" in text
        assert "age_ms=1000 [FRESH]" in text
        assert "next turn:   overall 19" in text
