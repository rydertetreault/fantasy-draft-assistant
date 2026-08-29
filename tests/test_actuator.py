"""Verified submission tests (Checkpoint 2, Task 6).

Exactly one click per intent, pre-click re-verification against a fresh
snapshot, mandatory post-click confirmation, HALT (never retry) on missing
confirmation, and evidence-gated fallback.
"""

import pytest

from fantasy_draft_assistant.actuator import (
    FakeActuator,
    Outcome,
    SubmitResult,
    SubmitStatus,
    verify_and_submit,
)
from fantasy_draft_assistant.models import DraftState
from fantasy_draft_assistant.observer import apply_snapshot
from fantasy_draft_assistant.operator import Mode, Operator
from fantasy_draft_assistant.safety import Allowlist, TeamIdentity

from test_operator import BOARD, CONFIG, LEAGUE, LOOKUP, NOW, SEASON, TEAM, grant, slot_entry


def identity() -> TeamIdentity:
    return TeamIdentity(alias="synaps1", league_id=LEAGUE, team_id=TEAM, season=SEASON)


@pytest.fixture
def allowlist() -> Allowlist:
    return Allowlist([identity()])


@pytest.fixture
def op(allowlist) -> Operator:
    return Operator(CONFIG, allowlist, Mode.AUTOPICK, grant=grant(), now_ms=NOW)


def snap(*picks):
    return {"draftDetail": {"picks": list(picks)}}


def base_snapshot():
    """Our team (2) on the clock at overall 1."""
    return snap(slot_entry(1, TEAM))


def synced_state(snapshot=None):
    state = DraftState(team="synaps1", league_id=LEAGUE, season=SEASON)
    new_state, _ = apply_snapshot(state, snapshot or base_snapshot(), NOW, LOOKUP)
    return new_state


class SnapshotFeed:
    """Scripted fetch_snapshot: returns queued snapshots, repeats the last."""

    def __init__(self, *snapshots):
        self.queue = list(snapshots)
        self.fetches = 0

    def __call__(self):
        self.fetches += 1
        if len(self.queue) > 1:
            return self.queue.pop(0)
        return self.queue[0]


def run(op, actuator, feed, state=None):
    return verify_and_submit(
        op, actuator, state or synced_state(), BOARD,
        round_no=1, slot=1, fetch_snapshot=feed, now_fn=lambda: NOW,
        player_lookup=LOOKUP,
    )


def confirmed_snapshot(player_id):
    """Snapshot proving player_id was drafted by our team at overall 1."""
    return snap(slot_entry(1, TEAM, player_id), slot_entry(2, 5))


PRIMARY_ID = 104  # Josh Allen — highest score on the test BOARD


class TestHappyPath:
    def test_verified_submit_is_exactly_one_click(self, op):
        actuator = FakeActuator()
        feed = SnapshotFeed(base_snapshot(), confirmed_snapshot(PRIMARY_ID))
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.SUBMITTED
        assert outcome.submit_calls == 1
        assert len(actuator.calls) == 1
        assert actuator.calls[0].player_id == PRIMARY_ID

    def test_confirmation_requires_matching_overall_and_team(self, op):
        # Right player, wrong team recorded -> NOT confirmed.
        actuator = FakeActuator()
        feed = SnapshotFeed(base_snapshot(), snap(slot_entry(1, 7, PRIMARY_ID)))
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.HALT


class TestBlockedBeforeClick:
    def test_blocked_intent_never_touches_actuator(self, allowlist):
        observer_op = Operator(CONFIG, allowlist, Mode.OBSERVE)
        actuator = FakeActuator()
        outcome = run(observer_op, actuator, SnapshotFeed(base_snapshot()))
        assert outcome.status is SubmitStatus.BLOCKED
        assert actuator.calls == []

    def test_fresh_snapshot_showing_not_our_turn_blocks(self, op):
        actuator = FakeActuator()
        # Fresh snapshot: someone else on the clock now.
        feed = SnapshotFeed(snap(slot_entry(1, TEAM, 999), slot_entry(2, 5)))
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.BLOCKED
        assert actuator.calls == []

    def test_malformed_presubmit_snapshot_blocks_without_click(self, op):
        actuator = FakeActuator()
        outcome = run(op, actuator, SnapshotFeed({"junk": True}))
        assert outcome.status is SubmitStatus.BLOCKED
        assert "malformed" in outcome.reason
        assert actuator.calls == []


class TestHaltNoRetry:
    def test_rejected_submit_halts_without_second_click(self, op):
        actuator = FakeActuator([SubmitResult(accepted=False, detail="ESPN said no")])
        feed = SnapshotFeed(base_snapshot(), confirmed_snapshot(PRIMARY_ID))
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.HALT
        assert "no retry" in outcome.reason
        assert len(actuator.calls) == 1

    def test_missing_confirmation_halts_without_second_click(self, op):
        actuator = FakeActuator()
        # Confirmation snapshot still shows our slot unmade.
        feed = SnapshotFeed(base_snapshot(), base_snapshot())
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.HALT
        assert len(actuator.calls) == 1

    def test_malformed_confirmation_snapshot_halts(self, op):
        actuator = FakeActuator()
        feed = SnapshotFeed(base_snapshot(), base_snapshot(), {"bad": 1})
        # queue: pre-submit ok, confirmation malformed
        feed.queue = [base_snapshot(), {"bad": 1}]
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.HALT
        assert len(actuator.calls) == 1

    def test_wrong_player_confirmed_halts(self, op):
        actuator = FakeActuator()
        feed = SnapshotFeed(base_snapshot(), confirmed_snapshot(101))  # not our pick
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.HALT
        assert len(actuator.calls) == 1


class TestFallback:
    def test_fallback_used_when_snapshot_proves_primary_gone(self, op):
        actuator = FakeActuator()
        # Fresh snapshot: primary (Josh Allen, 104) sniped at overall 1;
        # we are on the clock at overall 2.
        primary_gone = snap(slot_entry(1, 5, PRIMARY_ID), slot_entry(2, TEAM))
        fallback_id = 101  # Gibbs, next-best on this board
        confirm = snap(
            slot_entry(1, 5, PRIMARY_ID), slot_entry(2, TEAM, fallback_id), slot_entry(3, 7)
        )
        feed = SnapshotFeed(primary_gone, confirm)
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.SUBMITTED
        assert len(actuator.calls) == 1
        assert actuator.calls[0].player_id == fallback_id

    def test_candidate_change_without_evidence_blocks(self, op, monkeypatch):
        # Force decide() to swap candidates while the primary is still free.
        actuator = FakeActuator()
        real = Operator.submit_intent
        calls = {"n": 0}

        def flaky(self, state, board_rows, round_no, slot, now_ms):
            calls["n"] += 1
            if calls["n"] == 1:
                return real(self, state, board_rows, round_no, slot, now_ms)
            reduced = [r for r in board_rows if r["espn_player_id"] != PRIMARY_ID]
            return real(self, state, reduced, round_no, slot, now_ms)

        monkeypatch.setattr(Operator, "submit_intent", flaky)
        feed = SnapshotFeed(base_snapshot())
        outcome = run(op, actuator, feed)
        assert outcome.status is SubmitStatus.BLOCKED
        assert "without snapshot evidence" in outcome.reason
        assert actuator.calls == []


class TestFakeActuator:
    def test_records_calls_and_scripts_results(self):
        fake = FakeActuator([SubmitResult(False, "x")])
        assert fake.submit(None) == SubmitResult(False, "x")
        assert fake.submit(None).accepted is True  # default after script runs out
        assert len(fake.calls) == 2
