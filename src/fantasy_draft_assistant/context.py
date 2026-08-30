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


def expected_position_takes(
    gap_probs: list[dict[str, float]], runs: dict[str, int]
) -> dict[str, float]:
    """Expected number of players taken at each position before our next
    pick, from live opponent-need modeling. An active run at a position is
    live evidence the drain rate is hotter than the need model says."""
    takes: dict[str, float] = {}
    for pos in CORE_POSITIONS:
        takes[pos] = sum(p.get(pos, 0.0) for p in gap_probs)
        if pos in runs:
            takes[pos] += 1.0
    return takes


def expected_next_best(
    available: pd.DataFrame, pos: str, takes: float
) -> float:
    """Expected projection of the best player left at pos at our next pick,
    after `takes` expected picks come off the top (linear interpolation)."""
    projs = (
        available[available["pos"] == pos]
        .sort_values("projection", ascending=False)["projection"]
        .tolist()
    )
    if not projs:
        return 0.0
    lo = min(int(takes), len(projs) - 1)
    hi = min(lo + 1, len(projs) - 1)
    frac = min(1.0, max(0.0, takes - lo))
    return float(projs[lo] * (1 - frac) + projs[hi] * frac)


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

    Primary signal is WAIT-LOSS, computed live from this draft — no preset
    round rules:
        wait_loss = candidate projection - E[best projection left at their
                    position at our NEXT pick], where the expectation comes
                    from opponent-need modeling of every team picking in the
                    gap, heated further by live run detection.
    Final score = wait_loss + 0.25 * slot_adjusted_vorp     (lineup-relevant)
                = 0.30 * slot_adjusted_vorp                  (bench-only)
    A flat position curve or saturated opponents drive wait_loss to ~0 and
    the pick naturally waits; a draining scarce tier screams NOW.
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
    takes = expected_position_takes(gap_probs, runs)
    next_best_at = {
        pos: expected_next_best(available, pos, takes.get(pos, 0.0))
        for pos in CORE_POSITIONS
    }
    replacement = replacement_levels(players, teams)
    out = base_recommendations.copy()
    wait_col, run_col, surv_col, vorp_col, slot_col, ctx_col = (
        [], [], [], [], [], []
    )

    for _, row in out.iterrows():
        pos = str(row["pos"])
        surv = survival_probability(row, gap_probs, available, current_overall)

        vorp_slot, slot_label = slot_adjusted_vorp(
            pos, float(row["projection"]), my_roster, players, config, replacement
        )
        wait_loss = max(
            0.0, float(row["projection"]) - next_best_at.get(pos, 0.0)
        )
        run_pressure = 1.0 if pos in runs else 0.0

        if slot_label == "bench":
            ctx = 0.30 * vorp_slot  # depth value only; waiting costs nothing
            wait_loss = 0.0
        else:
            ctx = wait_loss + 0.25 * vorp_slot

        wait_col.append(round(wait_loss, 2))
        run_col.append(run_pressure)
        surv_col.append(round(surv, 3))
        vorp_col.append(round(vorp_slot, 2))
        slot_col.append(slot_label)
        ctx_col.append(round(ctx, 2))

    out["vorp"] = vorp_col
    out["slot"] = slot_col
    out["survival"] = surv_col
    out["wait_loss"] = wait_col
    out["run_pressure"] = run_col
    out["ctx_score"] = ctx_col
    return out.sort_values("ctx_score", ascending=False).head(limit)
