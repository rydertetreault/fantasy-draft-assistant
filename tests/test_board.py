"""Behavioral scenarios: ranking/board behavior (Checkpoint 1, Task 3).

Contract under test (per docs/live-draft-operator.spec.md, docs/draft-strategy.md,
and docs/live-draft-operator.plan.md Task 3):

    from fantasy_draft_assistant.board import recommend, snake_overall_pick, next_turn_overall

    result = recommend(players, state, config, round_no=1, pick_no=3)
    result.primary            # a Candidate
    result.fallbacks          # list of >= 2 Candidates, all currently available
    candidate.player          # player name
    candidate.position        # e.g. "RB"
    candidate.reason          # human-readable explanation string
    candidate.scarcity        # tier-cliff / scarcity signal (numeric)

    snake_overall_pick(slot=3, round_no=1, teams=10) == 3
    next_turn_overall(slot=3, current_round=1, teams=10) == 18

All fixtures are small, inline, and deterministic. No files, network, or browser.
"""

import pytest

from fantasy_draft_assistant.board import next_turn_overall, recommend, snake_overall_pick


# ---------------------------------------------------------------------------
# Inline deterministic fixtures
# ---------------------------------------------------------------------------

def make_players():
    """Small player table: name, position, projected points, tier."""
    rows = [
        # RBs — tier 1 has exactly one player left after CMC is drafted
        ("Christian McCaffrey", "RB", 320.0, 1),
        ("Bijan Robinson",      "RB", 305.0, 1),
        ("Breece Hall",         "RB", 260.0, 2),
        ("Jonathan Taylor",     "RB", 255.0, 2),
        ("Rachaad White",       "RB", 200.0, 3),
        # WRs
        ("Justin Jefferson",    "WR", 310.0, 1),
        ("Ja'Marr Chase",       "WR", 300.0, 1),
        ("Puka Nacua",          "WR", 265.0, 2),
        ("Chris Olave",         "WR", 240.0, 2),
        ("Jerry Jeudy",         "WR", 190.0, 3),
        # QB / TE
        ("Josh Allen",          "QB", 380.0, 1),
        ("Jared Goff",          "QB", 300.0, 2),
        ("Sam LaPorta",         "TE", 210.0, 1),
        ("Cole Kmet",           "TE", 150.0, 2),
        # DST / K — deliberately given inflated projections to tempt the ranker
        ("49ers D/ST",          "DST", 400.0, 1),
        ("Justin Tucker",       "K",   400.0, 1),
    ]
    return [
        {"player": name, "position": pos, "projection": proj, "tier": tier}
        for name, pos, proj, tier in rows
    ]


def make_config():
    """Mirror of config.synaps1.yaml league/strategy settings."""
    return {
        "league": {
            "teams": 10,
            "scoring": "ppr",
            "draft_type": "snake",
            "seconds_per_pick": 90,
            "roster_slots": {
                "QB": 1, "RB": 2, "WR": 2, "TE": 1,
                "FLEX": 1, "DST": 1, "K": 1, "BENCH": 7, "IR": 1,
            },
        },
        "strategy": {
            "roster_need_weight": 8.0,
            "scarcity_weight": 6.0,
            "value_weight": 4.0,
            "bye_penalty_weight": 1.5,
            "wait_until_round": {"DST": 14, "K": 15},
        },
    }


@pytest.fixture
def players():
    return make_players()


@pytest.fixture
def config():
    return make_config()


def all_candidates(result):
    return [result.primary] + list(result.fallbacks)


def candidate_names(result):
    return [c.player for c in all_candidates(result)]


# ---------------------------------------------------------------------------
# Primary + at least two fallbacks, all currently available
# ---------------------------------------------------------------------------

class TestRecommendationShape:
    def test_primary_plus_at_least_two_fallbacks(self, players, config):
        state = {"drafted": [], "my_roster": []}
        result = recommend(players, state, config, round_no=1, pick_no=3)
        assert result.primary is not None
        assert len(result.fallbacks) >= 2

    def test_all_recommended_players_are_currently_available(self, players, config):
        drafted = ["Christian McCaffrey", "Justin Jefferson", "Josh Allen"]
        state = {"drafted": list(drafted), "my_roster": []}
        result = recommend(players, state, config, round_no=1, pick_no=4)
        available = {p["player"] for p in players} - set(drafted)
        for name in candidate_names(result):
            assert name in available, f"{name} is not on the available board"

    def test_recommendations_are_distinct_players(self, players, config):
        state = {"drafted": [], "my_roster": []}
        result = recommend(players, state, config, round_no=1, pick_no=3)
        names = candidate_names(result)
        assert len(names) == len(set(names)), "duplicate players recommended"

    def test_deterministic_for_identical_inputs(self, players, config):
        state = {"drafted": ["Christian McCaffrey"], "my_roster": []}
        a = recommend(players, state, config, round_no=1, pick_no=3)
        b = recommend(players, state, config, round_no=1, pick_no=3)
        assert candidate_names(a) == candidate_names(b)


# ---------------------------------------------------------------------------
# Drafted players are never recommended
# ---------------------------------------------------------------------------

class TestDraftedNeverRecommended:
    def test_drafted_player_excluded_from_primary_and_fallbacks(self, players, config):
        state = {"drafted": ["Christian McCaffrey", "Bijan Robinson"], "my_roster": []}
        result = recommend(players, state, config, round_no=1, pick_no=5)
        names = candidate_names(result)
        assert "Christian McCaffrey" not in names
        assert "Bijan Robinson" not in names

    def test_our_own_roster_players_are_not_re_recommended(self, players, config):
        state = {
            "drafted": ["Christian McCaffrey", "Justin Jefferson"],
            "my_roster": ["Justin Jefferson"],
        }
        result = recommend(players, state, config, round_no=2, pick_no=18)
        assert "Justin Jefferson" not in candidate_names(result)

    def test_recommendations_survive_heavy_board_depletion(self, players, config):
        # Draft everything except three skill players + DST/K; the three
        # remaining legal players must be exactly the recommendation set.
        remaining = {"Rachaad White", "Jerry Jeudy", "Cole Kmet"}
        drafted = [
            p["player"] for p in players
            if p["player"] not in remaining and p["position"] not in ("DST", "K")
        ]
        state = {"drafted": drafted, "my_roster": []}
        result = recommend(players, state, config, round_no=8, pick_no=73)
        assert set(candidate_names(result)) == remaining


# ---------------------------------------------------------------------------
# Snake-order next-pick math (10 teams)
# ---------------------------------------------------------------------------

class TestSnakeOrder:
    def test_slot3_round1_is_overall_pick_3(self):
        assert snake_overall_pick(slot=3, round_no=1, teams=10) == 3

    def test_slot3_next_turn_after_round1_is_overall_18(self):
        # 10-team snake: slot 3 picks 3rd in round 1, then 8th in round 2
        # -> overall pick 10 + 8 = 18.
        assert next_turn_overall(slot=3, current_round=1, teams=10) == 18

    @pytest.mark.parametrize(
        "slot,round_no,expected",
        [
            (1, 1, 1),
            (1, 2, 20),   # turn pick: first slot waits the longest
            (1, 3, 21),
            (10, 1, 10),
            (10, 2, 11),  # wheel: back-to-back picks
            (10, 3, 30),
            (5, 1, 5),
            (5, 2, 16),
            (3, 2, 18),
            (3, 3, 23),
        ],
    )
    def test_overall_pick_for_slot_and_round(self, slot, round_no, expected):
        assert snake_overall_pick(slot=slot, round_no=round_no, teams=10) == expected

    def test_each_round_is_a_permutation_of_all_ten_slots(self):
        # Property: across any round, the 10 slots occupy overall picks
        # (round-1)*10+1 .. round*10 exactly once.
        for round_no in range(1, 16):
            picks = sorted(
                snake_overall_pick(slot=s, round_no=round_no, teams=10)
                for s in range(1, 11)
            )
            lo = (round_no - 1) * 10 + 1
            assert picks == list(range(lo, lo + 10))


# ---------------------------------------------------------------------------
# DST/K waiting policy
# ---------------------------------------------------------------------------

class TestDstKickerWaitPolicy:
    @pytest.mark.parametrize("round_no,pick_no", [(1, 3), (5, 43), (10, 98), (13, 123)])
    def test_dst_and_k_not_recommended_before_wait_rounds(
        self, players, config, round_no, pick_no
    ):
        # DST/K carry absurdly high projections in the fixture, but the
        # configured policy (DST: round 14, K: round 15) must hold while
        # other legal options exist.
        state = {"drafted": [], "my_roster": []}
        result = recommend(players, state, config, round_no=round_no, pick_no=pick_no)
        positions = {c.position for c in all_candidates(result)}
        assert "DST" not in positions
        assert "K" not in positions

    def test_dst_allowed_once_wait_round_reached(self, players, config):
        state = {"drafted": [], "my_roster": []}
        result = recommend(players, state, config, round_no=14, pick_no=138)
        # Not required to be picked, but must no longer be categorically
        # excluded: with a 400-point DST on the board at round 14 it should
        # appear somewhere in the candidate set.
        assert "DST" in {c.position for c in all_candidates(result)}

    def test_dst_recommended_when_it_is_the_only_legal_option(self, players, config):
        # Policy must not silently override the only legal case: everything
        # except DST/K is gone, so the board must still produce a primary.
        drafted = [p["player"] for p in players if p["position"] not in ("DST", "K")]
        state = {"drafted": drafted, "my_roster": []}
        result = recommend(players, state, config, round_no=9, pick_no=83)
        assert result.primary is not None
        assert result.primary.position in ("DST", "K")


# ---------------------------------------------------------------------------
# Tier-cliff / scarcity signal and human-readable reasons
# ---------------------------------------------------------------------------

class TestScarcityAndReasons:
    def test_scarcity_signal_exposed_on_every_candidate(self, players, config):
        state = {"drafted": ["Christian McCaffrey"], "my_roster": []}
        result = recommend(players, state, config, round_no=1, pick_no=3)
        for cand in all_candidates(result):
            assert hasattr(cand, "scarcity"), "candidate missing scarcity signal"
            assert cand.scarcity is not None
            float(cand.scarcity)  # must be numeric / coercible

    def test_last_player_in_tier_has_higher_scarcity_than_deep_tier(self, players, config):
        # CMC drafted -> Bijan is the LAST tier-1 RB. Two tier-1 WRs remain,
        # so the tier-cliff signal for Bijan must exceed the top WR's.
        state = {"drafted": ["Christian McCaffrey"], "my_roster": []}
        result = recommend(players, state, config, round_no=1, pick_no=3)
        by_name = {c.player: c for c in all_candidates(result)}
        assert "Bijan Robinson" in by_name, "last tier-1 RB should be a candidate"
        bijan = by_name["Bijan Robinson"]
        wr_cands = [c for c in all_candidates(result) if c.position == "WR"]
        assert wr_cands, "at least one WR expected among candidates"
        assert float(bijan.scarcity) > max(float(c.scarcity) for c in wr_cands)

    def test_every_candidate_has_a_human_readable_reason(self, players, config):
        state = {"drafted": ["Christian McCaffrey"], "my_roster": []}
        result = recommend(players, state, config, round_no=1, pick_no=3)
        for cand in all_candidates(result):
            assert isinstance(cand.reason, str)
            assert len(cand.reason.strip()) >= 5, (
                f"reason for {cand.player} is not a meaningful explanation: "
                f"{cand.reason!r}"
            )
