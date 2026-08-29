"""Decision engine: snake-order math and explainable recommendations.

Implements Checkpoint 1, Task 3 (docs/live-draft-operator.plan.md) following
docs/draft-strategy.md: score available players by projection, replacement /
tier-cliff scarcity, value versus the current overall pick, and roster need.
Output is a primary candidate plus at least two fallbacks, each carrying a
numeric scarcity signal and a human-readable reason.

Pure functions only — no files, network, or browser access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

FLEX_POSITIONS = frozenset({"RB", "WR", "TE"})

#: Default candidate count (primary + fallbacks). Spec requires >= 3 legal
#: candidates queued before each turn; we surface a few extra for pivots.
DEFAULT_CANDIDATES = 5


# ---------------------------------------------------------------------------
# Snake-order math
# ---------------------------------------------------------------------------

def snake_overall_pick(slot: int, round_no: int, teams: int) -> int:
    """Overall pick number for ``slot`` in ``round_no`` of a snake draft.

    Odd rounds run 1..teams; even rounds reverse. Example: 10 teams,
    slot 3, round 1 -> overall 3; round 2 -> overall 18.
    """
    if not (1 <= slot <= teams):
        raise ValueError(f"slot {slot} out of range for {teams}-team league")
    if round_no < 1:
        raise ValueError(f"round_no must be >= 1, got {round_no}")
    base = (round_no - 1) * teams
    if round_no % 2 == 1:
        return base + slot
    return base + (teams - slot + 1)


def next_turn_overall(slot: int, current_round: int, teams: int) -> int:
    """Overall pick number of ``slot``'s next turn after ``current_round``."""
    return snake_overall_pick(slot=slot, round_no=current_round + 1, teams=teams)


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Candidate:
    """One recommended player with its decision signals."""

    player: str
    position: str
    projection: float
    tier: int
    scarcity: float
    reason: str
    score: float
    adp: float | None = None


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Ordered recommendation: one primary and at least two fallbacks."""

    primary: Candidate | None
    fallbacks: tuple[Candidate, ...] = field(default_factory=tuple)

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        if self.primary is None:
            return tuple(self.fallbacks)
        return (self.primary, *self.fallbacks)


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------

def _as_rows(players: Any) -> list[dict[str, Any]]:
    """Normalize player input (list of dicts or DataFrame) to plain dicts."""
    if hasattr(players, "to_dict"):  # pandas DataFrame
        players = players.to_dict("records")
    rows: list[dict[str, Any]] = []
    for p in players:
        pos = str(p.get("position", p.get("pos", ""))).upper()
        rows.append(
            {
                "player": str(p["player"]),
                "position": pos,
                "projection": float(p.get("projection", 0.0)),
                "tier": int(p.get("tier", 99)),
                "adp": float(p["adp"]) if p.get("adp") is not None else None,
            }
        )
    return rows


def _starter_slots(position: str, config: Mapping[str, Any]) -> int:
    slots = config["league"]["roster_slots"]
    base = int(slots.get(position, 0))
    if position in FLEX_POSITIONS:
        base += int(slots.get("FLEX", 0))
    return base


def _roster_need(
    position: str,
    my_roster: Sequence[str],
    position_of: Mapping[str, str],
    config: Mapping[str, Any],
) -> float:
    """0..1 need signal: open starter/FLEX slots at this position."""
    starters = _starter_slots(position, config)
    if starters <= 0:
        return 0.0
    filled = sum(1 for name in my_roster if position_of.get(name) == position)
    if filled < starters:
        return (starters - filled) / starters
    # Bench depth: high-upside RB/WR bets remain mildly valuable (strategy doc).
    if position in {"RB", "WR"}:
        return 0.15
    return 0.0


def _scarcity_signals(available: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Tier-cliff scarcity per player name.

    For each player: the projection drop from that player's tier to the best
    available player in a *worse* tier at the same position, divided by how
    many same-tier-or-better options remain. The last player of a tier before
    a cliff therefore carries the highest scarcity at its position.
    """
    signals: dict[str, float] = {}
    by_pos: dict[str, list[dict[str, Any]]] = {}
    for row in available:
        by_pos.setdefault(row["position"], []).append(row)
    for rows in by_pos.values():
        for row in rows:
            tier = row["tier"]
            worse = [r["projection"] for r in rows if r["tier"] > tier]
            same_tier = [r for r in rows if r["tier"] == tier]
            if worse:
                dropoff = max(0.0, row["projection"] - max(worse))
            else:
                dropoff = 0.0
            signals[row["player"]] = dropoff / max(1, len(same_tier))
    return signals


def _replacement_levels(
    available: Sequence[dict[str, Any]], config: Mapping[str, Any]
) -> dict[str, float]:
    """Approximate replacement projection per position: the projection of the
    (teams * starter slots)-th best available player, or the worst available."""
    teams = int(config["league"]["teams"])
    levels: dict[str, float] = {}
    by_pos: dict[str, list[float]] = {}
    for row in available:
        by_pos.setdefault(row["position"], []).append(row["projection"])
    for pos, projections in by_pos.items():
        projections.sort(reverse=True)
        k = min(len(projections), max(1, teams * _starter_slots(pos, config)))
        levels[pos] = projections[k - 1]
    return levels


def _reason(
    row: dict[str, Any],
    scarcity: float,
    last_in_tier: bool,
    par: float,
    value_vs_pick: float,
    need: float,
) -> str:
    if last_in_tier and scarcity > 0:
        return f"last tier-{row['tier']} {row['position']}"
    if value_vs_pick >= 10.0:
        return f"high value vs ADP (+{value_vs_pick:.0f} picks)"
    if par >= 20.0:
        return f"+{par:.0f} points over replacement at {row['position']}"
    if need >= 1.0:
        return f"fills open starting {row['position']} slot"
    return f"best projection available ({row['projection']:.0f} pts)"


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------

def recommend(
    players: Any,
    state: Mapping[str, Any],
    config: Mapping[str, Any],
    round_no: int,
    pick_no: int,
    limit: int = DEFAULT_CANDIDATES,
) -> Recommendation:
    """Rank available players and return a primary plus >= 2 fallbacks.

    - Never recommends drafted or already-rostered players.
    - Respects ``strategy.wait_until_round`` for DST/K while other legal
      options exist; if they are the only legal options, they are returned.
    - Deterministic for identical inputs.
    """
    rows = _as_rows(players)
    drafted = set(state.get("drafted", ()))
    my_roster = list(state.get("my_roster", ()))
    unavailable = drafted | set(my_roster)
    available = [r for r in rows if r["player"] not in unavailable]
    if not available:
        return Recommendation(primary=None, fallbacks=())

    strat = config["strategy"]
    wait_until = {
        str(pos).upper(): int(rnd)
        for pos, rnd in strat.get("wait_until_round", {}).items()
    }
    eligible = [
        r
        for r in available
        if round_no >= wait_until.get(r["position"], 0)
    ]
    if not eligible:
        # DST/K (or whatever remains) are the only legal options: still pick.
        eligible = available

    teams = int(config["league"]["teams"])
    current_overall = (round_no - 1) * teams + pick_no
    scarcity = _scarcity_signals(available)
    replacement = _replacement_levels(available, config)
    position_of = {r["player"]: r["position"] for r in rows}

    tier_counts: dict[tuple[str, int], int] = {}
    for r in available:
        key = (r["position"], r["tier"])
        tier_counts[key] = tier_counts.get(key, 0) + 1

    def build(row: dict[str, Any]) -> Candidate:
        pos = row["position"]
        scarce = scarcity.get(row["player"], 0.0)
        par = row["projection"] - replacement.get(pos, row["projection"])
        need = _roster_need(pos, my_roster, position_of, config)
        value = (
            max(0.0, row["adp"] - current_overall) if row["adp"] is not None else 0.0
        )
        score = (
            row["projection"]
            + 0.1 * par
            + float(strat.get("scarcity_weight", 6.0)) * min(1.0, scarce / 50.0)
            + float(strat.get("value_weight", 4.0)) * (value / 12.0)
            + float(strat.get("roster_need_weight", 8.0)) * need
        )
        last_in_tier = tier_counts.get((pos, row["tier"]), 0) == 1
        reason = _reason(row, scarce, last_in_tier, par, value, need)
        return Candidate(
            player=row["player"],
            position=pos,
            projection=row["projection"],
            tier=row["tier"],
            scarcity=scarce,
            reason=reason,
            score=score,
            adp=row["adp"],
        )

    candidates = sorted(
        (build(r) for r in eligible),
        key=lambda c: (-c.score, -c.projection, c.player),
    )[: max(3, limit)]

    return Recommendation(primary=candidates[0], fallbacks=tuple(candidates[1:]))
