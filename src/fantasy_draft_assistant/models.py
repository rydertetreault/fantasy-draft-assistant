"""Per-team draft state with strict file isolation (Checkpoint 1, Task 1).

Each team alias persists its state to ``<data_dir>/<alias>/draft_state.json``.
Loading or saving one team's state never reads or writes another team's files,
and every load returns fully independent objects (no shared mutable storage).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILENAME = "draft_state.json"

_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_alias(team: str) -> str:
    """Validate a team alias as a safe path slug (no traversal, no surprises)."""
    if not isinstance(team, str) or not team:
        raise ValueError("team alias must be a non-empty string")
    alias = team.strip().lower()
    if not _ALIAS_RE.match(alias):
        raise ValueError(
            f"team alias {team!r} is not a safe slug "
            "(lowercase letters, digits, '-', '_' only)"
        )
    return alias


@dataclass(frozen=True, slots=True)
class Pick:
    """A single recorded draft pick.

    ``player_id``/``team_id`` are ESPN identifiers when known (observer-fed
    picks); manually recorded picks may leave them ``None``.
    """

    overall: int
    player: str
    position: str
    player_id: int | None = None
    team_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "player": self.player,
            "position": self.position,
            "player_id": self.player_id,
            "team_id": self.team_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pick":
        return cls(
            overall=int(data["overall"]),
            player=str(data["player"]),
            position=str(data["position"]),
            player_id=data.get("player_id"),
            team_id=data.get("team_id"),
        )


@dataclass(slots=True)
class DraftState:
    """Draft state scoped to exactly one team alias.

    A fresh state is empty. Each instance owns its own pick list; loads
    construct new objects from disk, so two loads never share storage.

    ``league_id``/``season`` bind the state to one ESPN draft; ``saved_at``
    is an ISO-8601 UTC timestamp written on save. ``last_sync_ms`` is the
    epoch-ms wall time of the last successful observer sync (None = never).
    ``on_clock_team_id``/``on_clock_overall`` describe the next unmade pick
    as reported by the latest snapshot.
    """

    team: str
    picks: list[Pick] = field(default_factory=list)
    league_id: int | None = None
    season: int | None = None
    saved_at: str | None = None
    last_sync_ms: int | None = None
    on_clock_team_id: int | None = None
    on_clock_overall: int | None = None

    def __post_init__(self) -> None:
        self.team = _validate_alias(self.team)
        # Defensive copy: never adopt a caller's mutable list.
        self.picks = [p if isinstance(p, Pick) else Pick.from_dict(p) for p in self.picks]

    def record_pick(self, overall: int, player: str, position: str) -> Pick:
        pick = Pick(overall=overall, player=player, position=position)
        self.picks.append(pick)
        return pick

    # -- persistence ---------------------------------------------------------

    def state_path(self, data_dir: str | Path) -> Path:
        """Path to this team's state file: ``<data_dir>/<alias>/draft_state.json``."""
        return Path(data_dir) / self.team / STATE_FILENAME

    def save(self, data_dir: str | Path) -> Path:
        """Persist this team's state, touching only this team's directory."""
        path = self.state_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {
            "team": self.team,
            "picks": [p.to_dict() for p in self.picks],
            "league_id": self.league_id,
            "season": self.season,
            "saved_at": self.saved_at,
            "last_sync_ms": self.last_sync_ms,
            "on_clock_team_id": self.on_clock_team_id,
            "on_clock_overall": self.on_clock_overall,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(
        cls,
        data_dir: str | Path,
        team: str,
        *,
        league_id: int | None = None,
        season: int | None = None,
    ) -> "DraftState":
        """Load a team's state; missing files yield a fresh empty state.

        When ``league_id``/``season`` are given, a stored state bound to a
        *different* league or season is refused (fail closed) — one team's
        state can never be replayed into another draft.

        Every call returns an independent object with its own pick storage.
        """
        alias = _validate_alias(team)
        path = Path(data_dir) / alias / STATE_FILENAME
        if not path.exists():
            return cls(team=alias, league_id=league_id, season=season)
        payload = json.loads(path.read_text(encoding="utf-8"))
        stored_team = _validate_alias(payload.get("team", alias))
        if stored_team != alias:
            raise ValueError(
                f"state file at {path} belongs to {stored_team!r}, not {alias!r}"
            )
        stored_league = payload.get("league_id")
        stored_season = payload.get("season")
        if league_id is not None and stored_league not in (None, league_id):
            raise ValueError(
                f"state file at {path} is bound to league {stored_league!r}, "
                f"expected {league_id!r}"
            )
        if season is not None and stored_season not in (None, season):
            raise ValueError(
                f"state file at {path} is bound to season {stored_season!r}, "
                f"expected {season!r}"
            )
        picks = [Pick.from_dict(p) for p in payload.get("picks", [])]
        return cls(
            team=alias,
            picks=picks,
            league_id=stored_league if stored_league is not None else league_id,
            season=stored_season if stored_season is not None else season,
            saved_at=payload.get("saved_at"),
            last_sync_ms=payload.get("last_sync_ms"),
            on_clock_team_id=payload.get("on_clock_team_id"),
            on_clock_overall=payload.get("on_clock_overall"),
        )
