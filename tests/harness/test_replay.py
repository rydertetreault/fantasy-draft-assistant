"""Unattended replay harness tests (Checkpoint 3, Task 7).

Proves, without a human and without live ESPN:
- a COMPLETE 10-team, 16-round snake draft with our team on an ephemeral
  valid grant: every one of our picks is legal and confirmed;
- duplicate and out-of-order snapshots converge;
- a disconnect (stale age) blocks submission until a fresh snapshot (red→green);
- a deliberately corrupt event yields Blocked with state untouched, then the
  recovery path continues (red→green);
- a forbidden-team script (alias roughrydas) is refused at Allowlist
  construction;
- observe→recommend latency stays under the 3000 ms budget for every pick.
"""

import dataclasses
import json
from pathlib import Path

import pytest
import yaml

from fantasy_draft_assistant.pipeline import assign_tiers, parse_players
from fantasy_draft_assistant.replay import (
    BASE_MS,
    DEFAULT_PICK_ORDER,
    LATENCY_BUDGET_MS,
    ReplayRunner,
    generate_script,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "players_sample.json"

LEAGUE, OUR_TEAM, SEASON = 305025860, 2, 2026
SESSION = f"{LEAGUE}-{SEASON}-{BASE_MS - 3_600_000}"


@pytest.fixture(scope="module")
def board_rows():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows, rejects = parse_players(raw)
    assert rows and not rejects
    return [dataclasses.asdict(r) for r in assign_tiers(rows)]


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((REPO / "config.synaps1.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def full_report(board_rows, config, tmp_path_factory):
    script = tmp_path_factory.mktemp("scripts") / "full_draft.jsonl"
    generate_script(board_rows, script, rounds=16, include_faults=True)
    return ReplayRunner(config, board_rows).run(script)


def script_header(alias="synaps1"):
    return [
        {
            "type": "league",
            "league": {
                "id": LEAGUE,
                "seasonId": SEASON,
                "settings": {"draftSettings": {"date": BASE_MS - 3_600_000}},
            },
            "pick_order": list(DEFAULT_PICK_ORDER),
            "rounds": 2,
        },
        {
            "type": "identity",
            "alias": alias,
            "league_id": LEAGUE,
            "team_id": OUR_TEAM,
            "season": SEASON,
        },
        {
            "type": "grant",
            "grant": {
                "alias": alias,
                "league_id": LEAGUE,
                "season": SEASON,
                "draft_session_id": SESSION,
                "issued_at_ms": BASE_MS - 60_000,
                "expires_at_ms": BASE_MS + 3_600_000,
            },
        },
    ]


def snapshot(*picks, note=""):
    ev = {"type": "snapshot", "draftDetail": {"picks": list(picks)}}
    if note:
        ev["note"] = note
    return ev


def entry(overall, team, player_id=-1):
    return {"overallPickNumber": overall, "playerId": player_id, "teamId": team}


def write_script(tmp_path, events, name="script.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


class TestFullDraft:
    def test_complete_draft_all_our_picks_legal_and_confirmed(
        self, full_report, board_rows
    ):
        report = full_report
        assert report.completed
        assert report.halts == []
        # Slot 2 in the real pick order -> 16 snake turns.
        assert len(report.expected_our_overalls) == 16
        confirmed = [p for p in report.our_picks if p["status"] == "submitted"]
        assert [p["overall"] for p in confirmed] == report.expected_our_overalls
        # Legal: unique real board players, never the pre-sniped top player.
        names = [p["player"] for p in confirmed]
        assert len(set(names)) == 16
        board_names = {r["player"] for r in board_rows}
        assert set(names) <= board_names
        sniped = max(board_rows, key=lambda r: r["projection"])["player"]
        assert sniped not in names
        # Every confirmed pick is recorded for OUR team in the final state.
        by_overall = {p["overall"]: p for p in report.final_picks}
        for pick in confirmed:
            assert by_overall[pick["overall"]]["team_id"] == OUR_TEAM
            assert by_overall[pick["overall"]]["player_id"] == pick["player_id"]
        assert report.ok

    def test_duplicate_and_out_of_order_snapshots_converged(self, full_report):
        # Duplicates + out-of-order resends were applied as no-ops and the
        # final state holds every scheduled pick exactly once.
        assert full_report.duplicate_noops >= 3
        overalls = [p["overall"] for p in full_report.final_picks]
        assert len(overalls) == len(set(overalls)) == 160

    def test_disconnect_blocked_then_recovered(self, full_report):
        stale_blocks = [
            b
            for b in full_report.blocked
            if b.get("note") == "act-during-disconnect"
        ]
        assert len(stale_blocks) == 1
        assert "freshness" in stale_blocks[0]["reason"]
        # Green half: the same overall was later confirmed.
        assert any(
            p["overall"] == stale_blocks[0]["on_clock"] and p["status"] == "submitted"
            for p in full_report.our_picks
        )

    def test_corrupt_snapshot_rejected_then_recovered(self, full_report):
        assert full_report.corrupt_rejected == 1
        corrupt = [
            b for b in full_report.blocked if "corrupt snapshot" in b["reason"]
        ]
        assert len(corrupt) == 1
        # The act right after the corrupt event was refused...
        after = [
            b for b in full_report.blocked if b.get("note") == "act-after-corrupt"
        ]
        assert len(after) == 1
        # ...and the draft still completed (recovery path continued).
        assert full_report.ok

    def test_timing_budget_under_3s_for_every_pick(self, full_report):
        assert len(full_report.timings) >= 16
        for timing in full_report.timings:
            assert timing["observe_to_recommend_ms"] < LATENCY_BUDGET_MS
        assert full_report.max_latency_ms < LATENCY_BUDGET_MS


class TestForbiddenTeamScript:
    @pytest.mark.parametrize("alias", ["roughrydas", "RoughRydas", " ROUGHRYDAS "])
    def test_refused_at_allowlist_construction(
        self, tmp_path, board_rows, config, alias
    ):
        events = script_header(alias=alias)
        path = write_script(tmp_path, events)
        runner = ReplayRunner(config, board_rows)
        with pytest.raises(PermissionError):
            runner.run(path)
        # Nothing was observed or submitted for the forbidden team.
        assert runner.state is None
        assert runner.actuator.calls == []


class TestScriptedFaults:
    def test_disconnect_blocks_until_fresh_snapshot(
        self, tmp_path, board_rows, config
    ):
        events = script_header()
        # Opponent (team 5) took overall 1; we are on the clock at overall 2.
        events.append(snapshot(entry(1, 5, 900_001), entry(2, OUR_TEAM)))
        events.append({"type": "disconnect", "advance_ms": 10_000})
        events.append({"type": "act", "note": "stale"})  # red
        events.append(snapshot(entry(1, 5, 900_001), entry(2, OUR_TEAM), note="fresh"))
        events.append({"type": "act", "note": "fresh"})  # green
        report = ReplayRunner(config, board_rows).run(write_script(tmp_path, events))
        assert len(report.blocked) == 1
        assert "freshness" in report.blocked[0]["reason"]
        assert [p["status"] for p in report.our_picks] == ["submitted"]
        assert report.our_picks[0]["overall"] == 2

    def test_corrupt_event_blocked_then_recovery_continues(
        self, tmp_path, board_rows, config
    ):
        events = script_header()
        events.append(snapshot(entry(1, 5, 900_001), entry(2, OUR_TEAM)))
        events.append({"type": "snapshot", "draftDetail": "garbage", "note": "corrupt"})
        events.append({"type": "act", "note": "after-corrupt"})
        report = ReplayRunner(config, board_rows).run(write_script(tmp_path, events))
        assert report.corrupt_rejected == 1
        # State untouched by the corrupt event: still our turn, pick confirmed.
        assert [p["status"] for p in report.our_picks] == ["submitted"]
        assert report.our_picks[0]["overall"] == 2

    def test_duplicate_snapshots_are_noops(self, tmp_path, board_rows, config):
        first = snapshot(entry(1, 5, 900_001), entry(2, OUR_TEAM))
        events = script_header() + [first, first, first]
        runner = ReplayRunner(config, board_rows)
        report = runner.run(write_script(tmp_path, events))
        assert report.duplicate_noops == 2
        assert len(runner.state.picks) == 1

    def test_expired_grant_blocks_submission(self, tmp_path, board_rows, config):
        events = script_header()
        events[2]["grant"]["expires_at_ms"] = BASE_MS - 1  # already expired
        events.append(snapshot(entry(1, OUR_TEAM)))
        events.append({"type": "act"})
        report = ReplayRunner(config, board_rows).run(write_script(tmp_path, events))
        assert report.our_picks == []
        assert len(report.blocked) == 1
        # Expired grant caps the operator at advisory: never autopick.
        assert "mode is advisory" in report.blocked[0]["reason"]

    def test_grant_for_wrong_session_blocks(self, tmp_path, board_rows, config):
        events = script_header()
        events[2]["grant"]["draft_session_id"] = "some-other-draft"
        events.append(snapshot(entry(1, OUR_TEAM)))
        events.append({"type": "act"})
        report = ReplayRunner(config, board_rows).run(write_script(tmp_path, events))
        assert report.our_picks == []
        assert len(report.blocked) == 1
