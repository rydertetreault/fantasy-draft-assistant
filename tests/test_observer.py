"""Observer tests (Checkpoint 2, Task 4): idempotent snapshot reduction.

Snapshots are shaped like ESPN mDraftDetail: draftDetail.picks entries with
overallPickNumber/playerId/teamId; playerId -1 marks a scheduled-but-unmade
pick (as captured in data/raw/league_settings.json pre-draft).
"""

import copy

import pytest

from fantasy_draft_assistant.models import DraftState
from fantasy_draft_assistant.observer import (
    STALE_AGE_MS,
    SnapshotError,
    apply_snapshot,
    state_age_ms,
)

NOW = 1_756_400_000_000


def slot(overall, team_id, player_id=-1):
    return {"overallPickNumber": overall, "playerId": player_id, "teamId": team_id}


def snap(*picks):
    return {"draftDetail": {"drafted": False, "inProgress": True, "picks": list(picks)}}


LOOKUP = {
    101: {"player": "Jahmyr Gibbs", "pos": "RB"},
    102: {"player": "Puka Nacua", "pos": "WR"},
    103: {"player": "Josh Allen", "pos": "QB"},
}


@pytest.fixture
def state() -> DraftState:
    return DraftState(team="synaps1", league_id=305025860, season=2026)


class TestBasicReduction:
    def test_made_picks_are_recorded_in_order(self, state):
        s2, events = apply_snapshot(
            state, snap(slot(1, 5, 101), slot(2, 3, 102), slot(3, 2)), NOW, LOOKUP
        )
        assert [p.overall for p in s2.picks] == [1, 2]
        assert s2.picks[0].player == "Jahmyr Gibbs"
        assert s2.picks[0].team_id == 5
        assert [e.kind for e in events] == ["pick", "pick"]

    def test_input_state_is_not_mutated(self, state):
        before = copy.deepcopy(state.picks)
        apply_snapshot(state, snap(slot(1, 5, 101)), NOW, LOOKUP)
        assert state.picks == before
        assert state.last_sync_ms is None

    def test_unmade_placeholder_picks_are_never_invented(self, state):
        s2, events = apply_snapshot(state, snap(slot(1, 5), slot(2, 3)), NOW)
        assert s2.picks == []
        assert events == []

    def test_on_clock_fields_come_from_first_unmade_pick(self, state):
        s2, _ = apply_snapshot(
            state, snap(slot(1, 5, 101), slot(2, 2), slot(3, 3)), NOW, LOOKUP
        )
        assert s2.on_clock_overall == 2
        assert s2.on_clock_team_id == 2

    def test_last_sync_ms_is_updated(self, state):
        s2, _ = apply_snapshot(state, snap(slot(1, 5, 101)), NOW, LOOKUP)
        assert s2.last_sync_ms == NOW


class TestIdempotencyAndConvergence:
    def test_same_snapshot_twice_is_a_noop(self, state):
        payload = snap(slot(1, 5, 101), slot(2, 3, 102), slot(3, 2))
        s2, ev1 = apply_snapshot(state, payload, NOW, LOOKUP)
        s3, ev2 = apply_snapshot(s2, payload, NOW + 1000, LOOKUP)
        assert s3.picks == s2.picks
        assert ev2 == []
        assert len(ev1) == 2

    def test_out_of_order_snapshots_converge(self, state):
        ordered = snap(slot(1, 5, 101), slot(2, 3, 102))
        reversed_ = snap(slot(2, 3, 102), slot(1, 5, 101))
        a, _ = apply_snapshot(state, ordered, NOW, LOOKUP)
        b, _ = apply_snapshot(state, reversed_, NOW, LOOKUP)
        assert a.picks == b.picks

    def test_duplicate_pick_entries_converge(self, state):
        payload = snap(slot(1, 5, 101), slot(1, 5, 101))
        s2, events = apply_snapshot(state, payload, NOW, LOOKUP)
        assert len(s2.picks) == 1
        assert len(events) == 1

    def test_conflicting_pick_is_corrected_by_snapshot(self, state):
        s2, _ = apply_snapshot(state, snap(slot(1, 5, 101)), NOW, LOOKUP)
        s3, events = apply_snapshot(s2, snap(slot(1, 3, 102)), NOW + 500, LOOKUP)
        assert len(s3.picks) == 1
        assert s3.picks[0].player_id == 102
        assert events[0].kind == "corrected"


class TestUnknownPlayers:
    def test_unknown_player_id_recorded_with_placeholder(self, state):
        s2, events = apply_snapshot(state, snap(slot(1, 5, 999999)), NOW)
        assert s2.picks[0].player == "unknown-player-999999"
        assert s2.picks[0].position == "UNK"
        assert s2.picks[0].player_id == 999999
        assert events[0].kind == "pick"


class TestMalformedSnapshots:
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"draftDetail": None},
            {"draftDetail": {"picks": None}},
            {"draftDetail": {"picks": "nope"}},
            {"draftDetail": {"picks": [{"overallPickNumber": 1}]}},
            {"draftDetail": {"picks": [{"overallPickNumber": "1", "playerId": 101, "teamId": 5}]}},
            {"draftDetail": {"picks": [{"overallPickNumber": 0, "playerId": 101, "teamId": 5}]}},
            {"draftDetail": {"picks": [{"overallPickNumber": 1, "playerId": True, "teamId": 5}]}},
            {"draftDetail": {"picks": ["junk"]}},
            "not a dict",
        ],
    )
    def test_malformed_snapshot_raises_and_leaves_state_alone(self, state, payload):
        with pytest.raises(SnapshotError):
            apply_snapshot(state, payload, NOW)
        assert state.picks == []
        assert state.last_sync_ms is None


class TestFreshness:
    def test_age_is_now_minus_last_sync(self, state):
        s2, _ = apply_snapshot(state, snap(slot(1, 5, 101)), NOW, LOOKUP)
        assert state_age_ms(s2, NOW + 2500) == 2500

    def test_never_synced_state_is_very_stale(self, state):
        assert state_age_ms(state, NOW) == STALE_AGE_MS

    def test_clock_skew_never_returns_negative(self, state):
        s2, _ = apply_snapshot(state, snap(slot(1, 5, 101)), NOW, LOOKUP)
        age = state_age_ms(s2, NOW - 5000)  # clock went backwards
        assert age >= 0
        assert age == STALE_AGE_MS  # unknown freshness = very stale

    def test_stale_age_blocks_can_submit(self, state):
        from fantasy_draft_assistant.safety import Allowlist, TeamIdentity, can_submit

        ident = TeamIdentity(alias="synaps1", league_id=305025860, team_id=2, season=2026)
        allow = Allowlist([ident])
        s2, _ = apply_snapshot(state, snap(slot(1, 5, 101)), NOW, LOOKUP)
        assert can_submit(ident, allow, state_age_ms(s2, NOW - 1)) is False
        assert can_submit(ident, allow, state_age_ms(s2, NOW + 1000)) is True
