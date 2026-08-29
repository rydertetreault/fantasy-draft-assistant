"""Idempotent ESPN draft observation (Checkpoint 2, Task 4).

Converts ESPN mDraftDetail snapshots into normalized ``DraftState`` picks:

- ``apply_snapshot(state, snapshot, now_ms)`` is a pure reducer: it returns
  a NEW state plus a list of events and never mutates its input.
- Applying the same snapshot twice is a no-op (idempotent); duplicate and
  out-of-order picks converge to the same state (keyed by overall pick
  number, snapshot wins on conflict with a visible "corrected" event).
- Unknown player ids are still recorded, with an explicit placeholder name.
- A malformed snapshot raises :class:`SnapshotError` and NEVER invents
  picks or touches state.
- Freshness: state carries ``last_sync_ms``; ``state_age_ms`` never returns
  a negative age — clock skew is treated as very stale (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .models import DraftState, Pick

#: Age reported when freshness is unknown (no sync yet, or clock skew).
STALE_AGE_MS: int = 10**12

#: ESPN uses -1 (sometimes 0) as the playerId of a not-yet-made pick.
_UNMADE_PLAYER_IDS = frozenset({-1, 0})


class SnapshotError(ValueError):
    """Raised when a snapshot cannot be trusted; state is left untouched."""


@dataclass(frozen=True, slots=True)
class ObserverEvent:
    """One normalized observation event (for the audit log)."""

    kind: str  # "pick" | "corrected"
    overall: int
    player_id: int
    team_id: int
    player: str


def _placeholder_name(player_id: int) -> str:
    return f"unknown-player-{player_id}"


def _require_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SnapshotError(f"snapshot pick field {field!r} is not an int: {value!r}")
    return value


def _parse_picks(snapshot: Mapping[str, Any]) -> list[dict[str, int]]:
    """Extract made picks from a snapshot; malformed input raises."""
    if not isinstance(snapshot, Mapping):
        raise SnapshotError("snapshot is not a mapping")
    detail = snapshot.get("draftDetail")
    if not isinstance(detail, Mapping):
        raise SnapshotError("snapshot has no draftDetail object")
    picks = detail.get("picks")
    if not isinstance(picks, list):
        raise SnapshotError("draftDetail.picks is not a list")
    made: list[dict[str, int]] = []
    for raw in picks:
        if not isinstance(raw, Mapping):
            raise SnapshotError(f"draftDetail.picks entry is not an object: {raw!r}")
        overall = _require_int(raw.get("overallPickNumber"), "overallPickNumber")
        player_id = _require_int(raw.get("playerId"), "playerId")
        team_id = _require_int(raw.get("teamId"), "teamId")
        if overall < 1:
            raise SnapshotError(f"overallPickNumber must be >= 1, got {overall}")
        if player_id in _UNMADE_PLAYER_IDS:
            continue  # scheduled slot, pick not made yet — never invent picks
        made.append({"overall": overall, "player_id": player_id, "team_id": team_id})
    return made


def _next_unmade(snapshot: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """(overall, teamId) of the first scheduled-but-unmade pick, if any."""
    picks = snapshot["draftDetail"]["picks"]
    unmade = [
        p
        for p in picks
        if isinstance(p.get("playerId"), int) and p["playerId"] in _UNMADE_PLAYER_IDS
    ]
    if not unmade:
        return None, None
    first = min(unmade, key=lambda p: p["overallPickNumber"])
    return first["overallPickNumber"], first.get("teamId")


def apply_snapshot(
    state: DraftState,
    snapshot: Mapping[str, Any],
    now_ms: int,
    player_lookup: Mapping[int, Mapping[str, Any]] | None = None,
) -> tuple[DraftState, list[ObserverEvent]]:
    """Reduce a raw mDraftDetail snapshot into a new DraftState + events.

    ``player_lookup`` maps espn_player_id -> board row (player/pos) so real
    names are recorded; unknown ids get an explicit placeholder.
    """
    made = _parse_picks(snapshot)  # raises before any state is touched
    lookup = player_lookup or {}

    by_overall: dict[int, Pick] = {p.overall: p for p in state.picks}
    events: list[ObserverEvent] = []
    for entry in sorted(made, key=lambda e: e["overall"]):
        overall, player_id, team_id = entry["overall"], entry["player_id"], entry["team_id"]
        row = lookup.get(player_id)
        name = str(row["player"]) if row else _placeholder_name(player_id)
        position = str(row.get("pos", row.get("position", "UNK"))) if row else "UNK"
        pick = Pick(
            overall=overall, player=name, position=position,
            player_id=player_id, team_id=team_id,
        )
        existing = by_overall.get(overall)
        if existing is not None:
            if existing.player_id == player_id and existing.team_id == team_id:
                continue  # duplicate — idempotent no-op
            events.append(ObserverEvent("corrected", overall, player_id, team_id, name))
        else:
            events.append(ObserverEvent("pick", overall, player_id, team_id, name))
        by_overall[overall] = pick

    on_clock_overall, on_clock_team_id = _next_unmade(snapshot)
    new_state = replace(
        state,
        picks=[by_overall[k] for k in sorted(by_overall)],
        last_sync_ms=now_ms,
        on_clock_overall=on_clock_overall,
        on_clock_team_id=on_clock_team_id,
    )
    return new_state, events


def state_age_ms(state: DraftState, now_ms: int) -> int:
    """Milliseconds since the last successful sync; NEVER negative.

    No sync yet, or a last-sync timestamp in the future (clock skew), means
    freshness is unknown -> report very stale so guards fail closed.
    """
    last = state.last_sync_ms
    if last is None or not isinstance(last, int) or isinstance(last, bool):
        return STALE_AGE_MS
    age = now_ms - last
    if age < 0:
        return STALE_AGE_MS
    return age
