"""Operational modes for the live draft operator (Checkpoint 2, Task 5).

- Modes: OBSERVE (default), ADVISORY, AUTOPICK.
- AUTOPICK requires a session-specific :class:`AuthorizationGrant` loaded
  from an ephemeral JSON file. An expired/mismatched/absent grant caps the
  mode at ADVISORY — never AUTOPICK.
- Nothing about autopick is ever persisted: a restart constructs a fresh
  Operator which starts in OBSERVE unless a valid grant is supplied again.
- ``decide`` always returns a Recommendation (read-only, any mode).
- ``submit_intent`` returns a SubmitIntent ONLY when every guard passes;
  any failed check returns a :class:`Blocked` value — it never raises past
  the boundary and never submits anything itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from . import board as board_engine
from .board import Recommendation, snake_overall_pick
from .observer import state_age_ms
from .models import DraftState
from .safety import Allowlist, TeamIdentity, can_submit, _normalize_alias


class Mode(Enum):
    OBSERVE = "observe"
    ADVISORY = "advisory"
    AUTOPICK = "autopick"


class AuditLogLike(Protocol):
    """Structural type for :class:`fantasy_draft_assistant.audit.AuditLog`."""

    def log(self, event: str, **fields: Any) -> Mapping[str, Any]:  # pragma: no cover
        ...


@dataclass(frozen=True, slots=True)
class AuthorizationGrant:
    """Ephemeral, session-specific authorization for autopick."""

    alias: str
    league_id: int
    season: int
    draft_session_id: str
    issued_at_ms: int
    expires_at_ms: int


def load_grant(path: str | Path) -> AuthorizationGrant | None:
    """Load a grant from an ephemeral JSON file; malformed -> None (no grant)."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return AuthorizationGrant(
            alias=str(payload["alias"]),
            league_id=int(payload["league_id"]),
            season=int(payload["season"]),
            draft_session_id=str(payload["draft_session_id"]),
            issued_at_ms=int(payload["issued_at_ms"]),
            expires_at_ms=int(payload["expires_at_ms"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def grant_is_valid(
    grant: AuthorizationGrant | None,
    identity: TeamIdentity,
    now_ms: int,
    observed_session_id: str | None = None,
) -> bool:
    """True only for a live grant naming this exact identity and session.

    When the observer has derived the live draft-session id
    (``observed_session_id``), the grant MUST match it exactly (CP2 verdict,
    MEDIUM: grants are bound to the observed draft session). When the session
    is not yet known, the grant still needs a non-blank session id, exact
    identity fields, and a live validity window.
    """
    if grant is None:
        return False
    if _normalize_alias(grant.alias) != identity.normalized_alias:
        return False
    if grant.league_id != identity.league_id or grant.season != identity.season:
        return False
    if not isinstance(grant.draft_session_id, str) or not grant.draft_session_id.strip():
        return False
    if observed_session_id is not None and grant.draft_session_id != observed_session_id:
        return False
    return grant.issued_at_ms <= now_ms < grant.expires_at_ms


def derive_turn(overall: int, teams: int) -> tuple[int, int]:
    """(round_no, slot) for an overall pick in a ``teams``-team snake draft.

    Inverse of :func:`board.snake_overall_pick`; never trusts caller-supplied
    round/slot (CP2 verdict, LOW).
    """
    if not isinstance(overall, int) or isinstance(overall, bool) or overall < 1:
        raise ValueError(f"overall pick must be a positive int, got {overall!r}")
    if not isinstance(teams, int) or isinstance(teams, bool) or teams < 1:
        raise ValueError(f"teams must be a positive int, got {teams!r}")
    round_no = (overall - 1) // teams + 1
    index_in_round = (overall - 1) % teams + 1
    slot = index_in_round if round_no % 2 == 1 else teams - index_in_round + 1
    return round_no, slot


@dataclass(frozen=True, slots=True)
class Blocked:
    """A refused submission. Carries the human-readable reason."""

    reason: str


@dataclass(frozen=True, slots=True)
class SubmitIntent:
    """A fully guarded intention to submit one specific pick."""

    player_id: int
    player_name: str
    identity: TeamIdentity
    checks: tuple[str, ...]
    expected_overall: int


class Operator:
    """Mode-aware draft operator for exactly one allowlisted identity."""

    def __init__(
        self,
        config: Mapping[str, Any],
        allowlist: Allowlist,
        mode: Mode = Mode.OBSERVE,
        grant: AuthorizationGrant | None = None,
        now_ms: int | None = None,
        *,
        observed_session_id: str | None = None,
        audit: "AuditLogLike | None" = None,
    ) -> None:
        self.config = config
        self.allowlist = allowlist
        self.observed_session_id = observed_session_id
        self._audit = audit
        espn = config["espn"]
        self.identity = TeamIdentity(
            alias=_normalize_alias(espn.get("authorized_team")),
            league_id=espn.get("league_id"),
            team_id=espn.get("team_id"),
            season=espn.get("season_id"),
        )
        self.grant = grant
        # AUTOPICK is only reachable with a currently valid grant; anything
        # else caps at ADVISORY. Default (no explicit request) is OBSERVE.
        if mode is Mode.AUTOPICK:
            if now_ms is not None and grant_is_valid(
                grant, self.identity, now_ms, observed_session_id
            ):
                self.mode = Mode.AUTOPICK
            else:
                self.mode = Mode.ADVISORY
        else:
            self.mode = mode
        if self._audit is not None:
            self._audit.log(
                "operator.init",
                mode=self.mode.value,
                observed_session_id=self.observed_session_id,
            )

    # -- read-only ----------------------------------------------------------

    def _drafted_and_mine(self, state: DraftState) -> tuple[list[str], list[str]]:
        drafted = [p.player for p in state.picks]
        mine = [p.player for p in state.picks if p.team_id == self.identity.team_id]
        return drafted, mine

    def decide(
        self,
        state: DraftState,
        board_rows: Sequence[Mapping[str, Any]],
        round_no: int,
        slot: int,
        now_ms: int,
    ) -> Recommendation:
        """Always available, in every mode. Never writes anything."""
        drafted, mine = self._drafted_and_mine(state)
        teams = int(self.config["league"]["teams"])
        overall = snake_overall_pick(slot=slot, round_no=round_no, teams=teams)
        pick_no = overall - (round_no - 1) * teams
        return board_engine.recommend(
            board_rows,
            {"drafted": drafted, "my_roster": mine},
            self.config,
            round_no=round_no,
            pick_no=pick_no,
        )

    # -- guarded write path --------------------------------------------------

    def submit_intent(
        self,
        state: DraftState,
        board_rows: Sequence[Mapping[str, Any]],
        round_no: int | None,
        slot: int | None,
        now_ms: int,
    ) -> SubmitIntent | Blocked:
        """Return a SubmitIntent only when EVERY guard passes; else Blocked.

        Never raises past this boundary and never performs the submission.
        Round and slot are DERIVED from ``state.on_clock_overall`` via snake
        math; caller-supplied values are cross-checked only (mismatch blocks,
        pass ``None`` to skip the cross-check). Internal errors surface as a
        generic Blocked reason; full detail goes to the audit log only.
        """
        try:
            result = self._guarded_submit_intent(state, board_rows, round_no, slot, now_ms)
        except Exception as exc:  # boundary: never raise, never submit
            if self._audit is not None:
                self._audit.log(
                    "submit.internal_error",
                    error_type=type(exc).__name__,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            result = Blocked(
                f"internal error ({type(exc).__name__}); submission refused — "
                "full detail in audit log"
            )
        if self._audit is not None:
            if isinstance(result, Blocked):
                self._audit.log("submit.blocked", reason=result.reason)
            else:
                self._audit.log(
                    "submit.intent",
                    player=result.player_name,
                    player_id=result.player_id,
                    expected_overall=result.expected_overall,
                    checks=list(result.checks),
                )
        return result

    def _guarded_submit_intent(
        self,
        state: DraftState,
        board_rows: Sequence[Mapping[str, Any]],
        round_no: int | None,
        slot: int | None,
        now_ms: int,
    ) -> SubmitIntent | Blocked:
        checks: list[str] = []
        if self.mode is not Mode.AUTOPICK:
            return Blocked(f"mode is {self.mode.value}, not autopick")
        checks.append("mode=autopick")

        if not grant_is_valid(
            self.grant, self.identity, now_ms, self.observed_session_id
        ):
            return Blocked(
                "authorization grant missing, expired, or mismatched "
                "(must name the observed draft session)"
            )
        checks.append("grant-valid")

        age = state_age_ms(state, now_ms)
        if not can_submit(self.identity, self.allowlist, age):
            return Blocked(
                f"identity/freshness guard refused (state_age_ms={age})"
            )
        checks.append("identity-allowlisted-and-fresh")

        if state.league_id != self.identity.league_id or (
            state.season != self.identity.season
        ):
            return Blocked("draft state is bound to a different league/season")
        checks.append("state-binding")

        if state.on_clock_team_id != self.identity.team_id:
            return Blocked(
                f"not our turn (on the clock: team {state.on_clock_team_id})"
            )
        if state.on_clock_overall is None:
            return Blocked("no on-the-clock pick in latest state")
        checks.append("our-turn")

        # Never trust caller round/slot: derive them from the observed
        # on-clock overall pick (CP2 verdict, LOW).
        teams = int(self.config["league"]["teams"])
        derived_round, derived_slot = derive_turn(int(state.on_clock_overall), teams)
        if round_no is not None and round_no != derived_round:
            return Blocked(
                f"caller round {round_no} disagrees with observed on-clock "
                f"overall {state.on_clock_overall} (round {derived_round})"
            )
        if slot is not None and slot != derived_slot:
            return Blocked(
                f"caller slot {slot} disagrees with observed on-clock "
                f"overall {state.on_clock_overall} (slot {derived_slot})"
            )
        checks.append("turn-derived-from-observed-state")

        rec = self.decide(state, board_rows, derived_round, derived_slot, now_ms)
        primary = rec.primary
        if primary is None:
            return Blocked("no candidate available")
        drafted, _ = self._drafted_and_mine(state)
        if primary.player in drafted:
            return Blocked(f"candidate {primary.player!r} is no longer available")
        row = next(
            (r for r in board_rows if r.get("player") == primary.player), None
        )
        if row is None or not isinstance(row.get("espn_player_id"), int):
            return Blocked(
                f"candidate {primary.player!r} has no ESPN player id on the board"
            )
        checks.append("candidate-available")

        return SubmitIntent(
            player_id=int(row["espn_player_id"]),
            player_name=primary.player,
            identity=self.identity,
            checks=tuple(checks),
            expected_overall=int(state.on_clock_overall),
        )
