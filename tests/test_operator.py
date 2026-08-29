"""Operator mode tests (Checkpoint 2, Task 5).

Default OBSERVE; AUTOPICK only via a valid session-specific grant; every
failed guard yields Blocked (never an exception, never a submission).
"""

import dataclasses
import json

import pytest

from fantasy_draft_assistant.models import DraftState
from fantasy_draft_assistant.observer import apply_snapshot
from fantasy_draft_assistant.operator import (
    AuthorizationGrant,
    Blocked,
    Mode,
    Operator,
    SubmitIntent,
    grant_is_valid,
    load_grant,
)
from fantasy_draft_assistant.safety import Allowlist, TeamIdentity

NOW = 1_756_400_000_000
LEAGUE, TEAM, SEASON = 305025860, 2, 2026

CONFIG = {
    "espn": {
        "league_id": LEAGUE,
        "team_id": TEAM,
        "season_id": SEASON,
        "authorized_team": "Synaps1",
    },
    "league": {
        "teams": 10,
        "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1},
    },
    "strategy": {"wait_until_round": {"DST": 14, "K": 15}},
}

BOARD = [
    {"player": "Jahmyr Gibbs", "espn_player_id": 101, "pos": "RB", "projection": 360.0, "tier": 1, "adp": 1.4},
    {"player": "Puka Nacua", "espn_player_id": 102, "pos": "WR", "projection": 350.0, "tier": 1, "adp": 5.2},
    {"player": "Bijan Robinson", "espn_player_id": 103, "pos": "RB", "projection": 348.0, "tier": 1, "adp": 2.4},
    {"player": "Josh Allen", "espn_player_id": 104, "pos": "QB", "projection": 369.0, "tier": 1, "adp": 21.6},
]

LOOKUP = {r["espn_player_id"]: r for r in BOARD}


def identity() -> TeamIdentity:
    return TeamIdentity(alias="synaps1", league_id=LEAGUE, team_id=TEAM, season=SEASON)


@pytest.fixture
def allowlist() -> Allowlist:
    return Allowlist([identity()])


def grant(**overrides) -> AuthorizationGrant:
    kwargs = dict(
        alias="synaps1",
        league_id=LEAGUE,
        season=SEASON,
        draft_session_id="draft-2026-08-29",
        issued_at_ms=NOW - 1000,
        expires_at_ms=NOW + 3_600_000,
    )
    kwargs.update(overrides)
    return AuthorizationGrant(**kwargs)


def slot_entry(overall, team_id, player_id=-1):
    return {"overallPickNumber": overall, "playerId": player_id, "teamId": team_id}


def fresh_state(*picks, on_clock_team=TEAM):
    """State synced at NOW with given made picks; our team on the clock."""
    state = DraftState(team="synaps1", league_id=LEAGUE, season=SEASON)
    entries = list(picks)
    entries.append(slot_entry(len(entries) + 1, on_clock_team))
    snap = {"draftDetail": {"picks": entries}}
    new_state, _ = apply_snapshot(state, snap, NOW, LOOKUP)
    return new_state


class TestModes:
    def test_default_mode_is_observe(self, allowlist):
        assert Operator(CONFIG, allowlist).mode is Mode.OBSERVE

    def test_autopick_with_valid_grant(self, allowlist):
        op = Operator(CONFIG, allowlist, Mode.AUTOPICK, grant=grant(), now_ms=NOW)
        assert op.mode is Mode.AUTOPICK

    def test_autopick_without_grant_falls_back_to_advisory(self, allowlist):
        op = Operator(CONFIG, allowlist, Mode.AUTOPICK, grant=None, now_ms=NOW)
        assert op.mode is Mode.ADVISORY

    def test_expired_grant_falls_back_to_advisory(self, allowlist):
        expired = grant(expires_at_ms=NOW - 1)
        op = Operator(CONFIG, allowlist, Mode.AUTOPICK, grant=expired, now_ms=NOW)
        assert op.mode is Mode.ADVISORY

    def test_mismatched_grant_falls_back_to_advisory(self, allowlist):
        wrong = grant(alias="synaps2")
        op = Operator(CONFIG, allowlist, Mode.AUTOPICK, grant=wrong, now_ms=NOW)
        assert op.mode is Mode.ADVISORY

    def test_restart_is_fresh_no_persisted_autopick(self, allowlist):
        op1 = Operator(CONFIG, allowlist, Mode.AUTOPICK, grant=grant(), now_ms=NOW)
        assert op1.mode is Mode.AUTOPICK
        # "restart": brand-new operator, no grant supplied again
        op2 = Operator(CONFIG, allowlist)
        assert op2.mode is Mode.OBSERVE


class TestGrant:
    def test_load_grant_roundtrip(self, tmp_path):
        path = tmp_path / "grant.json"
        path.write_text(json.dumps(dataclasses.asdict(grant())))
        loaded = load_grant(path)
        assert loaded == grant()

    @pytest.mark.parametrize(
        "content", ["", "not json", "{}", '{"alias": "synaps1"}', '{"alias": null}']
    )
    def test_malformed_grant_file_loads_as_none(self, tmp_path, content):
        path = tmp_path / "grant.json"
        path.write_text(content)
        assert load_grant(path) is None

    def test_missing_grant_file_loads_as_none(self, tmp_path):
        assert load_grant(tmp_path / "nope.json") is None

    def test_grant_validity_window(self):
        g = grant()
        assert grant_is_valid(g, identity(), NOW) is True
        assert grant_is_valid(g, identity(), g.expires_at_ms) is False
        assert grant_is_valid(g, identity(), g.issued_at_ms - 1) is False

    def test_grant_wrong_league_or_season_invalid(self):
        assert grant_is_valid(grant(league_id=1), identity(), NOW) is False
        assert grant_is_valid(grant(season=2025), identity(), NOW) is False

    def test_grant_blank_session_id_invalid(self):
        assert grant_is_valid(grant(draft_session_id="  "), identity(), NOW) is False


class TestDecide:
    def test_decide_returns_recommendation_in_every_mode(self, allowlist):
        state = fresh_state()
        for mode in (Mode.OBSERVE, Mode.ADVISORY):
            op = Operator(CONFIG, allowlist, mode)
            rec = op.decide(state, BOARD, round_no=1, slot=1, now_ms=NOW)
            assert rec.primary is not None
            assert len(rec.fallbacks) >= 2

    def test_decide_excludes_drafted_players(self, allowlist):
        state = fresh_state(slot_entry(1, 5, 101))  # Gibbs gone
        op = Operator(CONFIG, allowlist)
        rec = op.decide(state, BOARD, round_no=1, slot=2, now_ms=NOW)
        assert all(c.player != "Jahmyr Gibbs" for c in rec.candidates)


class TestSubmitIntentGuards:
    def autopick_op(self, allowlist, **grant_overrides):
        return Operator(
            CONFIG, allowlist, Mode.AUTOPICK, grant=grant(**grant_overrides), now_ms=NOW
        )

    def test_happy_path_returns_intent(self, allowlist):
        op = self.autopick_op(allowlist)
        intent = op.submit_intent(fresh_state(), BOARD, round_no=1, slot=1, now_ms=NOW)
        assert isinstance(intent, SubmitIntent)
        assert intent.player_id in LOOKUP
        assert intent.identity == identity()
        assert intent.expected_overall == 1
        assert "our-turn" in intent.checks and "grant-valid" in intent.checks

    def test_observe_and_advisory_modes_block(self, allowlist):
        state = fresh_state()
        for mode in (Mode.OBSERVE, Mode.ADVISORY):
            op = Operator(CONFIG, allowlist, mode)
            result = op.submit_intent(state, BOARD, 1, 1, NOW)
            assert isinstance(result, Blocked)
            assert "mode" in result.reason

    def test_grant_expiring_mid_session_blocks(self, allowlist):
        op = self.autopick_op(allowlist)
        later = op.grant.expires_at_ms + 1
        state = fresh_state()
        state.last_sync_ms = later  # keep state fresh; only the grant expires
        result = op.submit_intent(state, BOARD, 1, 1, later)
        assert isinstance(result, Blocked)
        assert "grant" in result.reason

    def test_stale_state_blocks(self, allowlist):
        op = self.autopick_op(allowlist)
        result = op.submit_intent(fresh_state(), BOARD, 1, 1, NOW + 10_000)
        assert isinstance(result, Blocked)
        assert "freshness" in result.reason

    def test_clock_skew_blocks(self, allowlist):
        op = self.autopick_op(allowlist)
        result = op.submit_intent(fresh_state(), BOARD, 1, 1, NOW - 10_000)
        assert isinstance(result, Blocked)

    def test_not_our_turn_blocks(self, allowlist):
        op = self.autopick_op(allowlist)
        state = fresh_state(on_clock_team=7)
        result = op.submit_intent(state, BOARD, 1, 1, NOW)
        assert isinstance(result, Blocked)
        assert "not our turn" in result.reason

    def test_wrong_league_binding_blocks(self, allowlist):
        op = self.autopick_op(allowlist)
        state = fresh_state()
        state.league_id = 999
        result = op.submit_intent(state, BOARD, 1, 1, NOW)
        assert isinstance(result, Blocked)
        assert "league" in result.reason

    def test_no_candidate_blocks(self, allowlist):
        op = self.autopick_op(allowlist)
        result = op.submit_intent(fresh_state(), [], 1, 1, NOW)
        assert isinstance(result, Blocked)

    def test_unallowlisted_identity_blocks(self):
        empty = Allowlist([])
        op = Operator(CONFIG, empty, Mode.AUTOPICK, grant=grant(), now_ms=NOW)
        result = op.submit_intent(fresh_state(), BOARD, 1, 1, NOW)
        assert isinstance(result, Blocked)

    def test_internal_errors_become_blocked_not_raised(self, allowlist):
        op = self.autopick_op(allowlist)
        result = op.submit_intent(fresh_state(), object(), 1, 1, NOW)  # bogus board
        assert isinstance(result, Blocked)
        assert "internal error" in result.reason
