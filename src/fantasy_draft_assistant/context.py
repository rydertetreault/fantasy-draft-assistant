"""Context-aware pick recommendation: compares the whole draft state — other
teams' rosters, who picks between our turns, positional runs, tier cliffs,
and survival odds — to find the best pick *for this roster at this pick*.

Layered on top of ranking.recommend()'s per-player base score. Every component
is exposed in the output frame so a human (or agent) can audit the reasoning.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pandas as pd

from .ranking import FLEX_POSITIONS, max_starters, roster_need_score

CORE_POSITIONS = ("QB", "RB", "WR", "TE")
RUN_WINDOW = 8  # recent picks considered for run detection
RUN_THRESHOLD = 4  # >= this many same-pos picks in the window is a run

# replacement-level rank per position (starters x teams + typical bench carry)
REPLACEMENT_MULT = {"QB": 1.2, "RB": 2.6, "WR": 2.6, "TE": 1.2, "K": 1.0, "DST": 1.0}


def replacement_levels(players: pd.DataFrame, teams: int) -> dict[str, float]:
    """Projection of the replacement-level player at each position: the value
    freely available at the draft's end. VORP = projection - replacement."""
    levels: dict[str, float] = {}
    for pos, group in players.groupby("pos"):
        rank = max(1, int(teams * REPLACEMENT_MULT.get(str(pos), 1.0)))
        ordered = group.sort_values("projection", ascending=False)
        idx = min(rank, len(ordered)) - 1
        levels[str(pos)] = float(ordered["projection"].iloc[idx])
    return levels


def slot_adjusted_vorp(
    pos: str,
    projection: float,
    my_roster: list[str],
    players: pd.DataFrame,
    config: dict,
    replacement: dict[str, float],
) -> tuple[float, str]:
    """VORP valued at the lineup slot this candidate would actually fill.

    - empty dedicated slot     -> projection - replacement[pos] (full VORP)
    - dedicated full, flex open -> projection - best flex replacement
      (a 3rd RB competes for ONE flex spot against WRs/TEs, not for RB2)
    - lineup full at pos       -> 30% of VORP (bench depth/bye/upside)
    Returns (value, slot_label) so the reasoning is auditable.
    """
    from .ranking import roster_counts

    slots = config["league"]["roster_slots"]
    counts = roster_counts(my_roster, players)
    dedicated = int(slots.get(pos, 0))
    if counts[pos] < dedicated:
        return projection - replacement.get(pos, 0.0), "starter"
    if pos in FLEX_POSITIONS and int(slots.get("FLEX", 0)) > 0:
        flex_used = sum(
            max(0, counts[p] - int(slots.get(p, 0))) for p in FLEX_POSITIONS
        )
        if flex_used < int(slots.get("FLEX", 0)):
            flex_repl = max(replacement.get(p, 0.0) for p in FLEX_POSITIONS)
            return projection - flex_repl, "flex"
    return 0.3 * (projection - replacement.get(pos, 0.0)), "bench"


@dataclass(frozen=True)
class TeamPick:
    """One completed pick with team attribution."""

    overall: int
    team_slot: int  # 1-based draft-order slot, NOT ESPN team id
    player: str
    pos: str


def snake_slot_for_overall(overall: int, teams: int) -> int:
    """1-based draft-order slot that owns a 1-based overall pick."""
    rnd, idx = divmod(overall - 1, teams)
    return (idx + 1) if rnd % 2 == 0 else (teams - idx)


def our_next_overall(current_overall: int, our_slot: int, teams: int) -> int:
    """Smallest overall > current_overall that belongs to our_slot."""
    o = current_overall + 1
    while snake_slot_for_overall(o, teams) != our_slot:
        o += 1
    return o


def picks_between(current_overall: int, our_slot: int, teams: int) -> list[int]:
    """Overall picks strictly after current, strictly before our next turn."""
    nxt = our_next_overall(current_overall, our_slot, teams)
    return list(range(current_overall + 1, nxt))


def opponent_position_probs(
    roster_positions: list[str], available: pd.DataFrame, config: dict
) -> dict[str, float]:
    """P(this opponent drafts pos next), from their unfilled starters plus the
    board pressure of what is actually available near the top."""
    counts = Counter(roster_positions)
    weights: dict[str, float] = {}
    top = available.nsmallest(12, "adp") if "adp" in available else available.head(12)
    top_share = top["pos"].value_counts(normalize=True).to_dict()
    for pos in CORE_POSITIONS:
        starters = max_starters(pos, config)
        unfilled = max(0, starters - counts[pos])
        need = unfilled / starters if starters else 0.0
        # 60% roster need, 40% board pressure (opponents take value too)
        weights[pos] = 0.6 * need + 0.4 * float(top_share.get(pos, 0.0))
    total = sum(weights.values()) or 1.0
    return {p: w / total for p, w in weights.items()}


def survival_probability(
    row: pd.Series,
    gap_probs: list[dict[str, float]],
    available: pd.DataFrame,
    current_overall: int,
) -> float:
    """P(candidate survives to our next pick). An opponent expected to draft
    this position takes the best ADP remaining at it; our candidate is at risk
    in proportion to how close to that front-of-queue spot they sit."""
    pos = str(row["pos"])
    ahead = available[
        (available["pos"] == pos) & (available["adp"] < float(row["adp"]))
    ].shape[0]
    p_survive = 1.0
    expected_pos_takes = 0.0
    for probs in gap_probs:
        expected_pos_takes += probs.get(pos, 0.0)
        # candidate is consumed once expected takes at pos exceed players ahead
        if expected_pos_takes > ahead:
            p_survive *= 1.0 - min(1.0, probs.get(pos, 0.0))
    # ADP pressure: players priced at/inside the gap rarely survive it
    gap_end = current_overall + len(gap_probs) + 1
    if float(row["adp"]) <= gap_end:
        p_survive *= 0.5 ** max(1.0, (gap_end - float(row["adp"])) / 6.0)
    return max(0.0, min(1.0, p_survive))


def detect_runs(recent: list[TeamPick]) -> dict[str, int]:
    """Positions taken >= RUN_THRESHOLD times in the last RUN_WINDOW picks."""
    window = recent[-RUN_WINDOW:]
    counts = Counter(p.pos for p in window)
    return {pos: n for pos, n in counts.items() if n >= RUN_THRESHOLD}


def tier_survivors(
    available: pd.DataFrame, pos: str, gap_probs: list[dict[str, float]]
) -> float:
    """Expected players left in pos's best current tier at our next pick."""
    at_pos = available[available["pos"] == pos]
    if at_pos.empty:
        return 0.0
    best_tier = at_pos["tier"].min()
    in_tier = float((at_pos["tier"] == best_tier).sum())
    expected_taken = sum(p.get(pos, 0.0) for p in gap_probs)
    return in_tier - expected_taken


def contextual_recommend(
    players: pd.DataFrame,
    base_recommendations: pd.DataFrame,
    all_picks: list[TeamPick],
    my_roster: list[str],
    our_slot: int,
    config: dict,
    limit: int = 10,
) -> pd.DataFrame:
    """Re-rank the engine's base recommendations using full draft context.

    Final score = base engine score
                + urgency:   (1 - survival) * value-over-next-available
                + cliff:     bonus when the pos's best tier empties in the gap
                + run:       bonus when a run at a needed pos is in progress,
                             small penalty when the run already gutted the tier
                             (pivot to the abandoned position instead).
    """
    teams = int(config["league"]["teams"])
    current_overall = len(all_picks)
    gap = picks_between(current_overall, our_slot, teams)

    drafted = {p.player for p in all_picks}
    available = players[~players["player"].isin(drafted)]

    # opponent need model for every pick in the gap
    rosters_by_slot: dict[int, list[str]] = {}
    for p in all_picks:
        rosters_by_slot.setdefault(p.team_slot, []).append(p.pos)
    gap_probs = [
        opponent_position_probs(
            rosters_by_slot.get(snake_slot_for_overall(o, teams), []),
            available,
            config,
        )
        for o in gap
    ]

    runs = detect_runs(all_picks)
    replacement = replacement_levels(players, teams)
    out = base_recommendations.copy()
    urgency_col, cliff_col, run_col, surv_col, vorp_col, slot_col, ctx_col = (
        [], [], [], [], [], [], []
    )

    for _, row in out.iterrows():
        pos = str(row["pos"])
        surv = survival_probability(row, gap_probs, available, current_overall)
        # value over next available at this position if we wait
        at_pos = available[
            (available["pos"] == pos) & (available["player"] != row["player"])
        ].sort_values("projection", ascending=False)
        next_best = float(at_pos["projection"].iloc[0]) if len(at_pos) else 0.0
        vona = max(0.0, float(row["projection"]) - next_best)
        urgency = (1.0 - surv) * vona

        survivors = tier_survivors(available, pos, gap_probs)
        need = roster_need_score(pos, my_roster, players, config)
        cliff = 12.0 * need if survivors < 1.0 else 0.0

        run_adj = 0.0
        if pos in runs:
            # run in progress: urgent if we still need the pos and the tier
            # holds; if the run already emptied the tier, pivot away instead.
            run_adj = 8.0 * need if survivors >= 1.0 else -6.0

        # Slot-adjusted VORP: value at the lineup slot actually being filled.
        # Kills both failure modes seen in rehearsal: WR-stacking (raw
        # projection) and RB-stacking (position VORP blind to filled slots).
        vorp_slot, slot_label = slot_adjusted_vorp(
            pos, float(row["projection"]), my_roster, players, config, replacement
        )
        engine_adj = float(row["score"]) - float(row["projection"])
        # run/cliff urgency only matters for players who improve the lineup
        if slot_label == "bench":
            cliff, run_adj = 0.0, min(0.0, run_adj)

        urgency_col.append(round(urgency, 2))
        cliff_col.append(round(cliff, 2))
        run_col.append(round(run_adj, 2))
        surv_col.append(round(surv, 3))
        vorp_col.append(round(vorp_slot, 2))
        slot_col.append(slot_label)
        ctx_col.append(round(vorp_slot + engine_adj + urgency + cliff + run_adj, 2))

    out["vorp"] = vorp_col
    out["slot"] = slot_col
    out["survival"] = surv_col
    out["urgency"] = urgency_col
    out["tier_cliff"] = cliff_col
    out["run_adj"] = run_col
    out["ctx_score"] = ctx_col
    return out.sort_values("ctx_score", ascending=False).head(limit)
