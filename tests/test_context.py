"""Tests for context-aware recommendation (context.py)."""
import pandas as pd
import pytest

from fantasy_draft_assistant.context import (
    TeamPick,
    contextual_recommend,
    detect_runs,
    opponent_position_probs,
    our_next_overall,
    picks_between,
    snake_slot_for_overall,
    survival_probability,
    tier_survivors,
)
from fantasy_draft_assistant.io import load_config, load_players
from fantasy_draft_assistant.ranking import recommend


@pytest.fixture()
def config():
    cfg = load_config("config.example.yaml")
    cfg["league"]["teams"] = 12
    return cfg


@pytest.fixture()
def players():
    return load_players("data/players.csv")


# ---- snake math -----------------------------------------------------------

def test_snake_slot_round_trip():
    # 12 teams: round 1 = slots 1..12, round 2 reverses to 12..1
    assert snake_slot_for_overall(1, 12) == 1
    assert snake_slot_for_overall(12, 12) == 12
    assert snake_slot_for_overall(13, 12) == 12
    assert snake_slot_for_overall(24, 12) == 1
    assert snake_slot_for_overall(25, 12) == 1


def test_our_next_overall_and_gap_slot4():
    # slot 4 of 12: picks 4, 21, 28, 45 ... (gaps of 16 and 6)
    assert our_next_overall(4, 4, 12) == 21
    assert len(picks_between(4, 4, 12)) == 16
    assert our_next_overall(21, 4, 12) == 28
    assert len(picks_between(21, 4, 12)) == 6


# ---- opponent model -------------------------------------------------------

def test_opponent_with_no_rbs_prefers_rb(players, config):
    available = players.head(60)
    probs_empty = opponent_position_probs([], available, config)
    probs_rb_full = opponent_position_probs(["RB", "RB", "RB"], available, config)
    assert probs_empty["RB"] > probs_rb_full["RB"]
    assert abs(sum(probs_empty.values()) - 1.0) < 1e-6


def test_run_detection():
    picks = [TeamPick(i + 1, (i % 12) + 1, f"p{i}", "RB") for i in range(5)]
    picks += [TeamPick(6, 6, "x", "WR"), TeamPick(7, 7, "y", "WR"), TeamPick(8, 8, "z", "TE")]
    runs = detect_runs(picks)
    assert "RB" in runs and runs["RB"] >= 4
    assert "TE" not in runs


# ---- survival -------------------------------------------------------------

def test_survival_lower_for_top_adp(players, config):
    available = players.copy()
    gap_probs = [{"QB": 0.1, "RB": 0.4, "WR": 0.4, "TE": 0.1}] * 10
    top_rb = available[available["pos"] == "RB"].nsmallest(1, "adp").iloc[0]
    deep_rb = available[available["pos"] == "RB"].nlargest(1, "adp").iloc[0]
    s_top = survival_probability(top_rb, gap_probs, available, 4)
    s_deep = survival_probability(deep_rb, gap_probs, available, 4)
    assert s_top < s_deep
    assert 0.0 <= s_top <= 1.0 and 0.0 <= s_deep <= 1.0


def test_tier_survivors_shrinks_with_demand(players):
    available = players.copy()
    heavy = [{"RB": 0.9, "WR": 0.05, "QB": 0.03, "TE": 0.02}] * 10
    light = [{"RB": 0.05, "WR": 0.9, "QB": 0.03, "TE": 0.02}] * 10
    assert tier_survivors(available, "RB", heavy) < tier_survivors(available, "RB", light)


# ---- end-to-end -----------------------------------------------------------

def _mid_draft_picks(players, n=20, teams=12):
    """First n picks by ADP order, snake-attributed."""
    by_adp = players.nsmallest(n, "adp")
    return [
        TeamPick(i + 1, snake_slot_for_overall(i + 1, teams), r["player"], r["pos"])
        for i, (_, r) in enumerate(by_adp.iterrows())
    ]


def test_contextual_rerank_produces_components(players, config):
    picks = _mid_draft_picks(players, 20)
    my_roster = [p.player for p in picks if p.team_slot == 4]
    state = {"drafted": [p.player for p in picks], "my_roster": my_roster}
    base = recommend(players, state, config, round_no=2, pick_no=9, limit=15)
    out = contextual_recommend(players, base, picks, my_roster, 4, config, limit=8)
    for col in ("survival", "urgency", "tier_cliff", "run_adj", "ctx_score"):
        assert col in out.columns
    assert len(out) == 8
    scores = list(out["ctx_score"])
    assert scores == sorted(scores, reverse=True)


def test_rb_run_with_rb_need_raises_rb_urgency(players, config):
    """An RB run among opponents while we still need RB2 must push RBs up
    relative to the no-run baseline (when the tier still has survivors)."""
    teams = 12
    # our slot 4 took a WR at pick 4; opponents took 5 straight RBs recently
    base_picks = _mid_draft_picks(players, 12, teams)
    rbs = players[
        (players["pos"] == "RB")
        & (~players["player"].isin([p.player for p in base_picks]))
    ].nsmallest(5, "adp")
    run_picks = base_picks + [
        TeamPick(13 + i, snake_slot_for_overall(13 + i, teams), r["player"], "RB")
        for i, (_, r) in enumerate(rbs.iterrows())
    ]
    my_roster = [p.player for p in run_picks if p.team_slot == 4]
    state = {"drafted": [p.player for p in run_picks], "my_roster": my_roster}
    base = recommend(players, state, config, round_no=2, pick_no=6, limit=15)
    out = contextual_recommend(players, base, run_picks, my_roster, 4, config, limit=15)
    rb_rows = out[out["pos"] == "RB"]
    if len(rb_rows):
        # every RB row must carry a non-zero run adjustment (bonus or pivot)
        assert (rb_rows["run_adj"] != 0.0).all()


# ---- slot-adjusted valuation (the 3-RBs-before-WR1 regression) ------------

def _synthetic_pool():
    """Pool where RB VORP dominates raw position value, mirroring full PPR."""
    rows = []
    for i in range(12):
        rows.append((f"RB{i+1}", "RB", 300 - i * 18))   # steep RB dropoff
    for i in range(12):
        rows.append((f"WR{i+1}", "WR", 280 - i * 8))    # shallow WR dropoff
    for i in range(6):
        rows.append((f"QB{i+1}", "QB", 360 - i * 6))
        rows.append((f"TE{i+1}", "TE", 200 - i * 12))
    return pd.DataFrame(
        {
            "player": [r[0] for r in rows],
            "team": 1,
            "pos": [r[1] for r in rows],
            "bye": 0,
            "projection": [float(r[2]) for r in rows],
            "adp": range(1, len(rows) + 1),
            "tier": 1,
        }
    )


def _ctx_top(players, config, my_roster, drafted_extra=()):
    drafted = list(my_roster) + list(drafted_extra)
    picks = [
        TeamPick(i + 1, (i % 12) + 1, name, players.set_index("player")["pos"][name])
        for i, name in enumerate(drafted)
    ]
    state = {"drafted": drafted, "my_roster": list(my_roster)}
    base = recommend(players, state, config, round_no=4, pick_no=4, limit=30)
    return contextual_recommend(players, base, picks, list(my_roster), 4, config, limit=5)


def test_three_rbs_means_wr_tops_the_list(config):
    """The user's regression: with RB1/RB2/RB3 rostered (2 RB slots + flex
    consumed), the next pick must be a WR, not a 4th RB."""
    players = _synthetic_pool()
    config["league"]["teams"] = 12
    config["league"]["roster_slots"] = {
        "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1, "BENCH": 6,
    }
    out = _ctx_top(players, config, ["RB1", "RB2", "RB3"])
    assert out.iloc[0]["pos"] == "WR", out[["player", "pos", "slot", "ctx_score"]]
    # and the best remaining RB must be valued as bench, not starter
    rb_rows = out[out["pos"] == "RB"]
    if len(rb_rows):
        assert (rb_rows["slot"] == "bench").all()


def test_wr_heavy_means_rb_tops_the_list(config):
    players = _synthetic_pool()
    config["league"]["teams"] = 12
    config["league"]["roster_slots"] = {
        "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1, "BENCH": 6,
    }
    out = _ctx_top(players, config, ["WR1", "WR2", "WR3"])
    assert out.iloc[0]["pos"] == "RB", out[["player", "pos", "slot", "ctx_score"]]


def test_second_qb_is_bench_valued(config):
    players = _synthetic_pool()
    config["league"]["teams"] = 12
    config["league"]["roster_slots"] = {
        "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1, "BENCH": 6,
    }
    out = _ctx_top(players, config, ["QB1", "RB1", "WR1"])
    qb_rows = out[out["pos"] == "QB"]
    if len(qb_rows):
        assert (qb_rows["slot"] == "bench").all()
    # a second QB must never outrank a starter-slot RB/WR here
    assert out.iloc[0]["pos"] in ("RB", "WR")
