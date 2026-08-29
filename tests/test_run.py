"""Live run-loop tests (`fantasy-draft run` glue).

The iteration function is exercised with fixture snapshots and a
FakeActuator only — no subprocess, no browser. Subprocess-spawning tests
are marked ``@pytest.mark.browser``.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fantasy_draft_assistant.actuator import FakeActuator, SubmitResult
from fantasy_draft_assistant.cli import build_parser
from fantasy_draft_assistant.models import DraftState
from fantasy_draft_assistant.operator import Mode
from fantasy_draft_assistant.runner import (
    HALT_BANNER,
    IterationResult,
    LiveSession,
    RunStatus,
    SubprocessActuator,
    draft_complete,
    newest_snapshot,
)
from fantasy_draft_assistant.safety import TeamIdentity

from test_operator import BOARD, CONFIG, LEAGUE, NOW, SEASON, TEAM, grant, slot_entry

REPO = Path(__file__).resolve().parents[1]


def snap(*picks, drafted=False):
    return {"draftDetail": {"drafted": drafted, "picks": list(picks)}}


def our_turn_snapshot():
    """Our team (2) on the clock at overall 1."""
    return snap(slot_entry(1, TEAM))


def confirm_snapshot(player_id=104):
    """Our pick made at overall 1; another team on the clock."""
    return snap(slot_entry(1, TEAM, player_id=player_id), slot_entry(2, 3))


class SnapshotFeed:
    """Scripted fetch_snapshot: returns queued snapshots, repeats the last."""

    def __init__(self, *snapshots):
        self.queue = list(snapshots)
        self.last = snapshots[-1] if snapshots else None

    def __call__(self):
        if self.queue:
            self.last = self.queue.pop(0)
        return self.last


def make_session(tmp_path, mode=Mode.ADVISORY, actuator=None, the_grant=None, rounds=16):
    return LiveSession(
        CONFIG,
        team="synaps1",
        data_dir=tmp_path,
        mode=mode,
        board_rows=BOARD,
        actuator=actuator if actuator is not None else FakeActuator(),
        grant=the_grant,
        rounds=rounds,
    )


class TestAdvisory:
    def test_our_turn_prints_recommendation(self, tmp_path):
        session = make_session(tmp_path, Mode.ADVISORY)
        result = session.iterate(our_turn_snapshot(), NOW, NOW)
        assert result.status is RunStatus.ADVISED
        text = "\n".join(result.messages)
        assert "OUR TURN" in text
        assert "PICK : Josh Allen" in text  # primary from BOARD fixture
        assert "alt 1" in text and "alt 2" in text  # two fallbacks

    def test_updates_dashboard_state_file(self, tmp_path):
        session = make_session(tmp_path, Mode.ADVISORY)
        session.iterate(confirm_snapshot(), NOW, NOW)
        loaded = DraftState.load(tmp_path, "synaps1")
        assert [p.player for p in loaded.picks] == ["Josh Allen"]
        assert loaded.on_clock_team_id == 3
        assert loaded.last_sync_ms == NOW

    def test_not_our_turn_is_observed_only(self, tmp_path):
        session = make_session(tmp_path, Mode.ADVISORY)
        result = session.iterate(snap(slot_entry(1, 7)), NOW, NOW)
        assert result.status is RunStatus.OBSERVED
        assert "OUR TURN" not in "\n".join(result.messages)

    def test_observe_mode_never_recommends(self, tmp_path):
        session = make_session(tmp_path, Mode.OBSERVE)
        result = session.iterate(our_turn_snapshot(), NOW, NOW)
        assert result.status is RunStatus.OBSERVED

    def test_recommendation_logged_to_audit(self, tmp_path):
        session = make_session(tmp_path, Mode.ADVISORY)
        session.iterate(our_turn_snapshot(), NOW, NOW)
        events = [e["event"] for e in session.audit.read_all()]
        assert "run.recommendation" in events


class TestAutopick:
    def test_valid_grant_submits_once_and_verifies(self, tmp_path):
        actuator = FakeActuator()
        session = make_session(tmp_path, Mode.AUTOPICK, actuator, grant())
        feed = SnapshotFeed(our_turn_snapshot(), confirm_snapshot())
        result = session.iterate(our_turn_snapshot(), NOW, NOW, fetch_snapshot=feed)
        assert result.status is RunStatus.SUBMITTED
        assert len(actuator.calls) == 1
        assert actuator.calls[0].player_id == 104
        assert "SUBMITTED + VERIFIED" in "\n".join(result.messages)

    def test_same_overall_never_attempted_twice(self, tmp_path):
        actuator = FakeActuator()
        session = make_session(tmp_path, Mode.AUTOPICK, actuator, grant())
        feed = SnapshotFeed(our_turn_snapshot(), confirm_snapshot())
        first = session.iterate(our_turn_snapshot(), NOW, NOW, fetch_snapshot=feed)
        assert first.status is RunStatus.SUBMITTED
        # A late re-poll of the SAME on-clock snapshot must not click again.
        again = session.iterate(our_turn_snapshot(), NOW + 100, NOW + 100)
        assert again.status is RunStatus.ADVISED
        assert len(actuator.calls) == 1
        assert "no retry" in "\n".join(again.messages)

    def test_no_grant_caps_at_advisory(self, tmp_path):
        actuator = FakeActuator()
        session = make_session(tmp_path, Mode.AUTOPICK, actuator, the_grant=None)
        result = session.iterate(our_turn_snapshot(), NOW, NOW)
        assert result.status is RunStatus.ADVISED
        assert actuator.calls == []

    def test_stale_snapshot_blocks_submission(self, tmp_path):
        actuator = FakeActuator()
        session = make_session(tmp_path, Mode.AUTOPICK, actuator, grant())
        result = session.iterate(our_turn_snapshot(), NOW - 10_000, NOW)
        assert result.status is RunStatus.BLOCKED
        assert actuator.calls == []  # refused before any click
        text = "\n".join(result.messages)
        assert "stale" in text.lower() or "freshness" in text.lower()


class TestHalt:
    def test_halt_prints_banner_and_drops_to_advisory_permanently(self, tmp_path):
        actuator = FakeActuator([SubmitResult(accepted=False, detail="rejected")])
        session = make_session(tmp_path, Mode.AUTOPICK, actuator, grant())
        feed = SnapshotFeed(our_turn_snapshot())
        result = session.iterate(our_turn_snapshot(), NOW, NOW, fetch_snapshot=feed)
        assert result.status is RunStatus.HALTED
        assert session.halted is True
        assert HALT_BANNER in result.messages
        assert len(actuator.calls) == 1

        # Even a brand-new on-clock turn with a live grant must NOT submit.
        next_turn = snap(slot_entry(1, TEAM, player_id=104), slot_entry(2, TEAM))
        again = session.iterate(next_turn, NOW + 1000, NOW + 1000)
        assert again.status is RunStatus.ADVISED
        assert len(actuator.calls) == 1  # still exactly one click, ever
        assert session.operator.mode is Mode.ADVISORY
        events = [e["event"] for e in session.audit.read_all()]
        assert "run.halt" in events


class TestCompletionAndErrors:
    def test_drafted_flag_completes(self, tmp_path):
        session = make_session(tmp_path, Mode.ADVISORY)
        result = session.iterate(
            snap(slot_entry(1, TEAM, player_id=101), drafted=True), NOW, NOW
        )
        assert result.status is RunStatus.COMPLETE

    def test_all_picks_made_completes(self, tmp_path):
        session = make_session(tmp_path, Mode.ADVISORY, rounds=1)
        picks = [slot_entry(i, (i % 10) + 1, player_id=1000 + i) for i in range(1, 11)]
        result = session.iterate(snap(*picks), NOW, NOW)
        assert result.status is RunStatus.COMPLETE
        assert "draft complete" in "\n".join(result.messages)

    def test_partial_draft_is_not_complete(self):
        picks = [slot_entry(1, 1, player_id=1001), slot_entry(2, 2)]
        assert not draft_complete({"draftDetail": {"picks": picks}}, 10, 16)

    def test_malformed_snapshot_leaves_state_untouched(self, tmp_path):
        session = make_session(tmp_path, Mode.ADVISORY)
        session.iterate(confirm_snapshot(), NOW, NOW)
        before = list(session.state.picks)
        result = session.iterate({"draftDetail": {"picks": "garbage"}}, NOW + 1, NOW + 1)
        assert result.status is RunStatus.SNAPSHOT_ERROR
        assert session.state.picks == before
        assert session.state.last_sync_ms == NOW  # freshness NOT refreshed


class TestSnapshotFiles:
    def test_newest_snapshot_by_filename_epoch(self, tmp_path):
        for ts in (1000, 3000, 2000):
            (tmp_path / f"{ts}.json").write_text("{}")
        found = newest_snapshot(tmp_path)
        assert found is not None
        path, ts = found
        assert path.name == "3000.json" and ts == 3000

    def test_missing_dir_and_empty_dir_yield_none(self, tmp_path):
        assert newest_snapshot(tmp_path / "nope") is None
        assert newest_snapshot(tmp_path) is None


class TestSubprocessActuator:
    def intent(self):
        from fantasy_draft_assistant.operator import SubmitIntent

        return SubmitIntent(
            player_id=101,
            player_name="Jahmyr Gibbs",
            identity=TeamIdentity(
                alias="synaps1", league_id=LEAGUE, team_id=TEAM, season=SEASON
            ),
            checks=("all",),
            expected_overall=1,
        )

    def test_build_command_shape(self, tmp_path):
        act = SubprocessActuator(grant_file=tmp_path / "grant.json")
        cmd = act.build_command(self.intent())
        assert cmd[0] == "node" and cmd[1].endswith("espn_actuate.mjs")
        assert "--grant-file" in cmd and "--live" in cmd
        payload = json.loads(cmd[2])
        assert payload == {
            "playerId": 101,
            "playerName": "Jahmyr Gibbs",
            "leagueId": LEAGUE,
            "teamId": TEAM,
        }

    def test_nonzero_exit_is_rejected(self, tmp_path):
        def fake_runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 6, stdout="", stderr="REFUSED: no row")

        act = SubprocessActuator(grant_file=tmp_path / "g.json", runner=fake_runner)
        result = act.submit(self.intent())
        assert result.accepted is False
        assert "exit 6" in result.detail and "no row" in result.detail

    def test_zero_exit_is_accepted(self, tmp_path):
        def fake_runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="LIVE: clicked", stderr="")

        act = SubprocessActuator(grant_file=tmp_path / "g.json", runner=fake_runner)
        result = act.submit(self.intent())
        assert result.accepted is True

    def test_spawn_failure_is_rejected(self, tmp_path):
        def fake_runner(cmd, **kwargs):
            raise OSError("node not found")

        act = SubprocessActuator(grant_file=tmp_path / "g.json", runner=fake_runner)
        assert act.submit(self.intent()).accepted is False

    @pytest.mark.browser
    @pytest.mark.skipif(shutil.which("node") is None, reason="node not found")
    def test_real_node_refusal_maps_to_rejected(self, tmp_path):
        """Real subprocess: the actuate script refuses an unreadable grant."""
        act = SubprocessActuator(
            grant_file=tmp_path / "missing_grant.json",
            script=REPO / "scripts" / "espn_actuate.mjs",
        )
        result = act.submit(self.intent())
        assert result.accepted is False
        assert "REFUSED" in result.detail


class TestCli:
    def test_run_subcommand_parses(self):
        args = build_parser().parse_args(
            ["run", "--team", "synaps1", "--mode", "advisory"]
        )
        assert args.func.__name__ == "cmd_run"
        assert args.poll_ms == 2000 and args.snapshot_dir is None

    def test_run_requires_known_mode(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["run", "--team", "synaps1", "--mode", "yolo"])
