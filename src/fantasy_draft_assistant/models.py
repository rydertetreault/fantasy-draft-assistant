"""Per-team draft state with strict file isolation (Checkpoint 1, Task 1).

Each team alias persists its state to ``<data_dir>/<alias>/draft_state.json``.
Loading or saving one team's state never reads or writes another team's files,
and every load returns fully independent objects (no shared mutable storage).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
    """A single recorded draft pick."""

    overall: int
    player: str
    position: str

    def to_dict(self) -> dict[str, Any]:
        return {"overall": self.overall, "player": self.player, "position": self.position}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pick":
        return cls(
            overall=int(data["overall"]),
            player=str(data["player"]),
            position=str(data["position"]),
        )


@dataclass(slots=True)
class DraftState:
    """Draft state scoped to exactly one team alias.

    A fresh state is empty. Each instance owns its own pick list; loads
    construct new objects from disk, so two loads never share storage.
    """

    team: str
    picks: list[Pick] = field(default_factory=list)

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
        payload = {"team": self.team, "picks": [p.to_dict() for p in self.picks]}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, data_dir: str | Path, team: str) -> "DraftState":
        """Load a team's state; missing files yield a fresh empty state.

        Every call returns an independent object with its own pick storage.
        """
        alias = _validate_alias(team)
        path = Path(data_dir) / alias / STATE_FILENAME
        if not path.exists():
            return cls(team=alias)
        payload = json.loads(path.read_text(encoding="utf-8"))
        stored_team = _validate_alias(payload.get("team", alias))
        if stored_team != alias:
            raise ValueError(
                f"state file at {path} belongs to {stored_team!r}, not {alias!r}"
            )
        picks = [Pick.from_dict(p) for p in payload.get("picks", [])]
        return cls(team=alias, picks=picks)
