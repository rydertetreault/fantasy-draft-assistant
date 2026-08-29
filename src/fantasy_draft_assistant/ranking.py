from __future__ import annotations

from collections import Counter

import pandas as pd

STARTER_POSITIONS = {"QB", "RB", "WR", "TE", "DST", "K"}
FLEX_POSITIONS = {"RB", "WR", "TE"}


def roster_counts(roster: list[str], players: pd.DataFrame) -> Counter:
    lookup = players.set_index("player")["pos"].to_dict()
    return Counter(lookup.get(name) for name in roster if lookup.get(name))


def max_starters(pos: str, config: dict) -> int:
    slots = config["league"]["roster_slots"]
    base = int(slots.get(pos, 0))
    if pos in FLEX_POSITIONS:
        base += int(slots.get("FLEX", 0))
    return base


def roster_need_score(pos: str, my_roster: list[str], players: pd.DataFrame, config: dict) -> float:
    counts = roster_counts(my_roster, players)
    starters = max_starters(pos, config)
    if starters == 0:
        return 0.0
    filled = counts[pos]
    if filled < starters:
        return (starters - filled) / starters
    bench_slots = int(config["league"]["roster_slots"].get("BENCH", 0))
    total_roster_size = sum(v for k, v in config["league"]["roster_slots"].items() if k != "FLEX") + int(config["league"]["roster_slots"].get("FLEX", 0))
    if len(my_roster) < total_roster_size and pos in {"RB", "WR"}:
        return 0.15
    if len(my_roster) < total_roster_size and bench_slots and pos in {"QB", "TE"} and counts[pos] < starters + 1:
        return 0.05
    return 0.0


def scarcity_scores(available: pd.DataFrame) -> dict[str, float]:
    scores: dict[str, float] = {}
    for pos, group in available.groupby("pos"):
        top = group.sort_values("projection", ascending=False).head(12)
        if len(top) <= 1:
            scores[pos] = 1.0
            continue
        dropoff = float(top["projection"].iloc[0] - top["projection"].median())
        scores[pos] = min(1.0, dropoff / max(1.0, top["projection"].iloc[0] * 0.25))
    return scores


def bye_penalty(row: pd.Series, my_roster: list[str], players: pd.DataFrame) -> float:
    if not my_roster:
        return 0.0
    mine = players[players["player"].isin(my_roster)]
    same_bye_same_pos = mine[(mine["bye"] == row["bye"]) & (mine["pos"] == row["pos"])]
    return min(1.0, len(same_bye_same_pos) * 0.35)


def recommend(players: pd.DataFrame, state: dict, config: dict, round_no: int, pick_no: int, limit: int = 15) -> pd.DataFrame:
    drafted = set(state.get("drafted", []))
    my_roster = state.get("my_roster", [])
    available = players[~players["player"].isin(drafted)].copy()
    if available.empty:
        return available

    strat = config["strategy"]
    scarcity = scarcity_scores(available)
    current_overall_pick = (round_no - 1) * int(config["league"]["teams"]) + pick_no

    def score(row: pd.Series) -> float:
        base = float(row["projection"])
        value = max(0.0, float(row["adp"]) - current_overall_pick) / 12.0
        need = roster_need_score(str(row["pos"]), my_roster, players, config)
        scarce = scarcity.get(str(row["pos"]), 0.0)
        penalty = bye_penalty(row, my_roster, players)
        wait_round = config["strategy"].get("wait_until_round", {}).get(str(row["pos"]))
        early_penalty = 0.0
        if wait_round and round_no < int(wait_round):
            early_penalty = 30.0
        return (
            base
            + strat["value_weight"] * value
            + strat["roster_need_weight"] * need
            + strat["scarcity_weight"] * scarce
            - strat["bye_penalty_weight"] * penalty
            - early_penalty
        )

    available["score"] = available.apply(score, axis=1)
    available["value_vs_pick"] = available["adp"] - current_overall_pick
    columns = ["player", "team", "pos", "bye", "projection", "adp", "tier", "value_vs_pick", "score"]
    return available.sort_values(["score", "projection"], ascending=False)[columns].head(limit)
