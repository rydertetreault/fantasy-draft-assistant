"""Identity guard for ESPN write actions (Checkpoint 1, Task 1).

Contract (docs/live-draft-operator.spec.md, TEAM_SAFETY.md):

- Exact allowlist match on every identity field before any write action.
- Default deny for unknown teams; RoughRydas can NEVER pass or be allowlisted.
- Partial/ambiguous identities fail closed.
- Stale state (age > 3000 ms) blocks writes even for allowlisted identities.

All functions here are pure decision functions with no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

# The one team we must never touch. Comparison is done on a normalized alias
# (lowercase, whitespace stripped) so case/spacing tricks cannot bypass it.
FORBIDDEN_ALIASES: frozenset[str] = frozenset({"roughrydas"})

#: Maximum acceptable draft-state age for a write action, in milliseconds.
MAX_STATE_AGE_MS: int = 3_000


def _normalize_alias(alias: object) -> str:
    """Normalize a team alias for comparison (lowercase, stripped)."""
    if not isinstance(alias, str):
        return ""
    return alias.strip().lower()


@dataclass(frozen=True, slots=True)
class TeamIdentity:
    """Immutable ESPN team identity.

    Fields may be ``None``/empty when identity capture is incomplete
    (e.g. Synaps2 before mapping); such identities are *complete=False*
    and always fail the write guard.
    """

    alias: str | None
    league_id: int | None
    team_id: int | None
    season: int | None

    @property
    def normalized_alias(self) -> str:
        return _normalize_alias(self.alias)

    @property
    def is_forbidden(self) -> bool:
        """True when this identity refers to a protected (never-touch) team."""
        return self.normalized_alias in FORBIDDEN_ALIASES

    @property
    def is_complete(self) -> bool:
        """True when every identity field is present and unambiguous."""
        return (
            bool(self.normalized_alias)
            and isinstance(self.league_id, int)
            and isinstance(self.team_id, int)
            and isinstance(self.season, int)
        )

    def _match_key(self) -> tuple[str, int | None, int | None, int | None]:
        return (self.normalized_alias, self.league_id, self.team_id, self.season)


class Allowlist:
    """Explicit allowlist of exact team identities.

    Membership (`identity in allowlist`) requires an exact match on all four
    fields. Forbidden aliases (RoughRydas) are refused at construction, and
    incomplete identities cannot be allowlisted — fail closed everywhere.
    """

    def __init__(self, identities: Iterable[TeamIdentity]) -> None:
        entries: list[TeamIdentity] = []
        for identity in identities:
            if not isinstance(identity, TeamIdentity):
                raise TypeError(
                    f"Allowlist entries must be TeamIdentity, got {type(identity)!r}"
                )
            if identity.is_forbidden:
                raise PermissionError(
                    f"Refusing to allowlist protected team {identity.alias!r}"
                )
            if not identity.is_complete:
                raise ValueError(
                    f"Refusing to allowlist incomplete identity {identity!r}"
                )
            entries.append(identity)
        self._entries: frozenset[tuple[str, int | None, int | None, int | None]] = (
            frozenset(e._match_key() for e in entries)
        )
        self._identities: tuple[TeamIdentity, ...] = tuple(entries)

    def __contains__(self, identity: object) -> bool:
        if not isinstance(identity, TeamIdentity):
            return False
        if identity.is_forbidden or not identity.is_complete:
            return False
        return identity._match_key() in self._entries

    def __iter__(self) -> Iterator[TeamIdentity]:
        return iter(self._identities)

    def __len__(self) -> int:
        return len(self._identities)


def can_submit(identity: TeamIdentity, allowlist: Allowlist, state_age_ms: int) -> bool:
    """Return True only for a fresh, exactly-allowlisted identity."""
    return identity in allowlist and state_age_ms <= MAX_STATE_AGE_MS
