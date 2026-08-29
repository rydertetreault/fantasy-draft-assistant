"""Identity guard for Yahoo Fantasy write actions (Yahoo adapter scaffold).

Mirrors :mod:`fantasy_draft_assistant.safety` (the battle-tested ESPN guard)
with Yahoo-shaped identities, and REUSES its primitives without modifying it:

- Exact allowlist match on every identity field before any write action.
- Default deny for unknown teams; forbidden aliases (RoughRydas) can NEVER
  pass or be allowlisted — same normalized-alias comparison as ESPN.
- Partial/ambiguous identities fail closed.
- Stale state (age > 3000 ms, same budget as ESPN) blocks writes even for
  allowlisted identities; negative age (clock skew) fails closed.

Yahoo-specific shape: teams are identified by a *team key*
``{game_key}.l.{league_id}.t.{team_id}`` (e.g. ``461.l.123456.t.7``), so the
identity carries ``game_key`` (per-season integer game id as a string, or the
code ``"nfl"``) in addition to the numeric league/team ids and season.

THE ALLOWLIST IS EMPTY. No real Yahoo league exists yet. Until the user
supplies and confirms exact ids, ``build_default_allowlist()`` returns an
empty allowlist and every guard refuses.

All functions here are pure decision functions with no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator

# Reuse the ESPN guard's building blocks verbatim — never re-implement the
# forbidden-team logic in two places.
from .safety import (
    FORBIDDEN_ALIASES,
    MAX_STATE_AGE_MS,
    _is_real_int,
    _normalize_alias,
)

__all__ = [
    "YahooTeamIdentity",
    "YahooAllowlist",
    "build_default_allowlist",
    "can_submit_yahoo",
    "MAX_STATE_AGE_MS",
]

# A valid Yahoo game_key is a per-season integer id ("461") or a game code
# ("nfl"). Anything else is ambiguous and fails closed.
_GAME_KEY_RE = re.compile(r"^(?:[0-9]+|[a-z]+)$")


def _normalize_game_key(game_key: object) -> str:
    if not isinstance(game_key, str):
        return ""
    key = game_key.strip().lower()
    return key if _GAME_KEY_RE.fullmatch(key) else ""


@dataclass(frozen=True, slots=True)
class YahooTeamIdentity:
    """Immutable Yahoo team identity.

    Fields may be ``None``/empty while identity capture is incomplete (which
    is the case for ALL Yahoo teams today); such identities are
    *complete=False* and always fail the write guard.
    """

    alias: str | None
    game_key: str | None  # e.g. "461" (2026 NFL game id) — TODO(verify)
    league_id: int | None
    team_id: int | None
    season: int | None

    @property
    def normalized_alias(self) -> str:
        return _normalize_alias(self.alias)

    @property
    def normalized_game_key(self) -> str:
        return _normalize_game_key(self.game_key)

    @property
    def is_forbidden(self) -> bool:
        """True when this identity refers to a protected (never-touch) team."""
        return self.normalized_alias in FORBIDDEN_ALIASES

    @property
    def is_complete(self) -> bool:
        """True when every identity field is present and unambiguous.

        Booleans are *not* valid ids (``bool`` subclasses ``int`` — same data
        bug the ESPN guard rejects).
        """
        return (
            bool(self.normalized_alias)
            and bool(self.normalized_game_key)
            and _is_real_int(self.league_id)
            and _is_real_int(self.team_id)
            and _is_real_int(self.season)
        )

    @property
    def team_key(self) -> str | None:
        """The Yahoo team key ``{game_key}.l.{league}.t.{team}``, or ``None``
        while the identity is incomplete (never build keys from partial ids).
        """
        if not self.is_complete:
            return None
        return f"{self.normalized_game_key}.l.{self.league_id}.t.{self.team_id}"

    def _match_key(self) -> tuple[str, str, int | None, int | None, int | None]:
        return (
            self.normalized_alias,
            self.normalized_game_key,
            self.league_id,
            self.team_id,
            self.season,
        )


class YahooAllowlist:
    """Explicit allowlist of exact Yahoo team identities.

    Same semantics as :class:`fantasy_draft_assistant.safety.Allowlist`:
    membership requires an exact match on all five fields, forbidden aliases
    are refused at construction (``PermissionError``), incomplete identities
    cannot be allowlisted (``ValueError``) — fail closed everywhere.
    """

    def __init__(self, identities: Iterable[YahooTeamIdentity]) -> None:
        entries: list[YahooTeamIdentity] = []
        for identity in identities:
            if not isinstance(identity, YahooTeamIdentity):
                raise TypeError(
                    f"YahooAllowlist entries must be YahooTeamIdentity, got {type(identity)!r}"
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
        self._entries: frozenset[
            tuple[str, str, int | None, int | None, int | None]
        ] = frozenset(e._match_key() for e in entries)
        self._identities: tuple[YahooTeamIdentity, ...] = tuple(entries)

    def __contains__(self, identity: object) -> bool:
        if not isinstance(identity, YahooTeamIdentity):
            return False
        if identity.is_forbidden or not identity.is_complete:
            return False
        return identity._match_key() in self._entries

    def __iter__(self) -> Iterator[YahooTeamIdentity]:
        return iter(self._identities)

    def __len__(self) -> int:
        return len(self._identities)


def build_default_allowlist() -> YahooAllowlist:
    """The project's Yahoo allowlist. INTENTIONALLY EMPTY.

    No Yahoo league/team ids exist yet. Until the user supplies exact,
    confirmed ids (league id, team id, season game_key) this returns an empty
    allowlist, so :func:`can_submit_yahoo` refuses everything. Adding an
    entry here is a deliberate, reviewed act — mirror TEAM_SAFETY.md when the
    time comes and NEVER add anything resembling RoughRydas.
    """
    return YahooAllowlist([])


def can_submit_yahoo(
    identity: YahooTeamIdentity, allowlist: YahooAllowlist, state_age_ms: int
) -> bool:
    """Return True only for a fresh, exactly-allowlisted Yahoo identity.

    Identical contract to :func:`fantasy_draft_assistant.safety.can_submit`:
    negative ``state_age_ms`` means clock skew → freshness unknown → refuse,
    exactly like stale state. With the default (empty) allowlist this is
    always ``False``.
    """
    if not _is_real_int(state_age_ms):
        return False
    return identity in allowlist and 0 <= state_age_ms <= MAX_STATE_AGE_MS
