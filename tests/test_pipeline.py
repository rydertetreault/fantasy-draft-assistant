"""Data pipeline tests (Checkpoint 2, Task 2).

Fixture-driven: tests/fixtures/players_sample.json is a valid ~30-player
subset of the real ESPN kona_player_info payload. Malformed rows are built
inline to prove visible rejection (stderr + rejects report) — never silent
coercion.
"""

import io
import json
from pathlib import Path

import pytest

from fantasy_draft_assistant import board
from fantasy_draft_assistant.pipeline import (
    BOARD_COLUMNS,
    BoardRow,
    Position,
    assign_tiers,
    build_board,
    load_board,
    parse_players,
)

FIXTURE = Path(__file__).parent / "fixtures" / "players_sample.json"


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(FIXTURE.read_text())


def make_entry(**overrides):
    player = {
        "id": 12345,
        "fullName": "Test Player",
        "defaultPositionId": 2,
        "proTeamId": 8,
        "injuryStatus": "ACTIVE",
        "ownership": {"averageDraftPosition": 10.5, "percentOwned": 99.0},
        "stats": [
            {"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0, "appliedTotal": 200.0},
            {"seasonId": 2025, "statSourceId": 0, "statSplitTypeId": 0, "appliedTotal": 180.0},
        ],
    }
    player.update(overrides)
    return {"player": player}


class TestParseFixture:
    def test_all_fixture_rows_validate(self, raw):
        rows, rejects = parse_players(raw)
        assert len(rows) == 30
        assert rejects == []

    def test_rows_have_closed_enum_positions(self, raw):
        rows, _ = parse_players(raw)
        valid = {p.value for p in Position}
        assert {r.pos for r in rows} <= valid

    def test_rows_carry_projection_adp_and_ids(self, raw):
        rows, _ = parse_players(raw)
        for r in rows:
            assert r.projection > 0
            assert isinstance(r.espn_player_id, int)
            assert r.player


class TestVisibleRejection:
    def test_unknown_position_id_is_rejected(self):
        rows, rejects = parse_players({"players": [make_entry(defaultPositionId=7)]})
        assert rows == []
        assert len(rejects) == 1
        assert "closed enum" in rejects[0].reason

    def test_missing_projection_is_rejected(self):
        entry = make_entry(stats=[])
        rows, rejects = parse_players({"players": [entry]})
        assert rows == []
        assert "projection" in rejects[0].reason

    def test_non_numeric_projection_is_rejected_not_coerced(self):
        entry = make_entry(
            stats=[{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0, "appliedTotal": "lots"}]
        )
        rows, rejects = parse_players({"players": [entry]})
        assert rows == []
        assert "projection" in rejects[0].reason

    def test_missing_name_is_rejected(self):
        rows, rejects = parse_players({"players": [make_entry(fullName="")]})
        assert rows == []
        assert "fullName" in rejects[0].reason

    def test_entry_without_player_object_is_rejected(self):
        rows, rejects = parse_players({"players": [{"junk": 1}]})
        assert rows == []
        assert rejects[0].reason == "entry has no player object"

    def test_payload_without_players_list_raises(self):
        with pytest.raises(ValueError):
            parse_players({"nope": []})


class TestTiers:
    def test_gap_opens_new_tier_per_position(self):
        rows = [
            BoardRow("A", 1, "RB", 1, 300.0, None, None, None, "ACTIVE"),
            BoardRow("B", 2, "RB", 1, 295.0, None, None, None, "ACTIVE"),
            BoardRow("C", 3, "RB", 1, 250.0, None, None, None, "ACTIVE"),  # cliff
            BoardRow("Q", 4, "QB", 1, 260.0, None, None, None, "ACTIVE"),
        ]
        tiered = {r.player: r.tier for r in assign_tiers(rows, min_gap=8.0)}
        assert tiered["A"] == 1 and tiered["B"] == 1
        assert tiered["C"] == 2
        assert tiered["Q"] == 1  # tiers are per-position

    def test_tiers_monotonic_with_projection_within_position(self, raw):
        rows, _ = parse_players(raw)
        tiered = assign_tiers(rows)
        by_pos: dict[str, list] = {}
        for r in tiered:
            by_pos.setdefault(r.pos, []).append(r)
        for pos_rows in by_pos.values():
            pos_rows.sort(key=lambda r: -r.projection)
            tiers = [r.tier for r in pos_rows]
            assert tiers == sorted(tiers)
            assert tiers[0] == 1


class TestBuildBoard:
    def test_build_emits_csv_meta_and_rejects_report(self, tmp_path):
        raw = {"players": [make_entry(), make_entry(id=2, fullName="Bad Pos", defaultPositionId=9)]}
        raw_path = tmp_path / "players.json"
        raw_path.write_text(json.dumps(raw))
        err = io.StringIO()
        board_path = build_board(raw_path, "synaps1", tmp_path / "data", stderr=err)

        assert board_path == tmp_path / "data" / "synaps1" / "board.csv"
        assert board_path.exists()
        assert "REJECT: Bad Pos" in err.getvalue()

        rejects = (tmp_path / "data" / "synaps1" / "rejects.csv").read_text()
        assert "Bad Pos" in rejects

        meta = json.loads((tmp_path / "data" / "synaps1" / "board_meta.json").read_text())
        assert meta["rows"] == 1 and meta["rejects"] == 1
        assert "source_timestamp" in meta and "T" in meta["source_timestamp"]

    def test_board_csv_columns_and_roundtrip(self, tmp_path):
        raw_path = tmp_path / "players.json"
        raw_path.write_text(FIXTURE.read_text())
        board_path = build_board(raw_path, "synaps1", tmp_path / "data", stderr=io.StringIO())
        header = board_path.read_text().splitlines()[0]
        assert header.split(",") == BOARD_COLUMNS
        rows = load_board(board_path)
        assert len(rows) == 30
        assert all(isinstance(r["projection"], float) for r in rows)

    def test_board_is_team_scoped(self, tmp_path):
        raw_path = tmp_path / "players.json"
        raw_path.write_text(FIXTURE.read_text())
        p1 = build_board(raw_path, "synaps1", tmp_path / "data", stderr=io.StringIO())
        p2 = build_board(raw_path, "synaps2", tmp_path / "data", stderr=io.StringIO())
        assert p1 != p2 and "synaps2" not in str(p1)


class TestBoardFeedsRecommend:
    def test_recommend_accepts_pipeline_rows(self, tmp_path, raw):
        raw_path = tmp_path / "players.json"
        raw_path.write_text(FIXTURE.read_text())
        board_path = build_board(raw_path, "synaps1", tmp_path / "data", stderr=io.StringIO())
        rows = load_board(board_path)
        config = {
            "league": {
                "teams": 10,
                "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1},
            },
            "strategy": {"wait_until_round": {"DST": 14, "K": 15}},
        }
        rec = board.recommend(rows, {"drafted": [], "my_roster": []}, config, round_no=1, pick_no=1)
        assert rec.primary is not None
        assert len(rec.fallbacks) >= 2
        assert rec.primary.position in {"QB", "RB", "WR", "TE"}  # DST/K wait policy
