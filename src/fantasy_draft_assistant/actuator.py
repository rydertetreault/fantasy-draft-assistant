"""Verified pick submission (Checkpoint 2, Task 6).

The actuator boundary: everything that can actually click a browser lives
behind :class:`BrowserActuator`. ``verify_and_submit`` is the only flow that
may call it, and it enforces:

- Intent checks are re-run against a FRESH snapshot immediately before the
  submit call.
- Exactly ONE submit call per intent; a failed/unconfirmed submit is NEVER
  retried (no blind clicks) — the flow halts for manual takeover.
- After submitting, a confirming snapshot must show our player_id at the
  expected overall pick for our team before the flow continues.
- A fallback candidate is used only when the fresh snapshot proves the
  primary is gone AND every safety check still passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence

from .models import DraftState
from .observer import SnapshotError, apply_snapshot
from .operator import Blocked, Operator, SubmitIntent


class SubmitStatus(Enum):
    SUBMITTED = "submitted"  # verified against a confirming snapshot
    BLOCKED = "blocked"      # refused before any click
    HALT = "halt"            # manual takeover required; no retry


@dataclass(frozen=True, slots=True)
class SubmitResult:
    """What the browser actuator reports back for one submit call."""

    accepted: bool
    detail: str = ""


class BrowserActuator(Protocol):
    """Anything that can physically submit a pick (browser, fake, replay)."""

    def submit(self, intent: SubmitIntent) -> SubmitResult:  # pragma: no cover
        ...


class FakeActuator:
    """Test double: records every submit call, returns a scripted result."""

    def __init__(self, results: Sequence[SubmitResult] | None = None) -> None:
        self.calls: list[SubmitIntent] = []
        self._results = list(results or [])

    def submit(self, intent: SubmitIntent) -> SubmitResult:
        self.calls.append(intent)
        if self._results:
            return self._results.pop(0)
        return SubmitResult(accepted=True, detail="fake")


@dataclass(frozen=True, slots=True)
class Outcome:
    """Result of one verify-and-submit attempt."""

    status: SubmitStatus
    reason: str
    intent: SubmitIntent | None = None
    submit_calls: int = 0


def _pick_confirmed(state: DraftState, intent: SubmitIntent) -> bool:
    for pick in state.picks:
        if pick.overall == intent.expected_overall:
            return (
                pick.player_id == intent.player_id
                and pick.team_id == intent.identity.team_id
            )
    return False


def verify_and_submit(
    operator: Operator,
    actuator: BrowserActuator,
    state: DraftState,
    board_rows: Sequence[Mapping[str, Any]],
    round_no: int,
    slot: int,
    fetch_snapshot: Callable[[], Mapping[str, Any]],
    now_fn: Callable[[], int],
    player_lookup: Mapping[int, Mapping[str, Any]] | None = None,
) -> Outcome:
    """Submit at most one verified pick. Never clicks twice, never retries."""
    # 1. Initial intent from the caller's state — all guards must pass.
    initial = operator.submit_intent(state, board_rows, round_no, slot, now_fn())
    if isinstance(initial, Blocked):
        return Outcome(SubmitStatus.BLOCKED, initial.reason)

    # 2. Refresh from a brand-new snapshot immediately before submitting.
    try:
        fresh_state, _ = apply_snapshot(state, fetch_snapshot(), now_fn(), player_lookup)
    except SnapshotError as exc:
        return Outcome(SubmitStatus.BLOCKED, f"pre-submit snapshot malformed: {exc}")

    # 3. Re-run every check against the fresh state.
    final = operator.submit_intent(fresh_state, board_rows, round_no, slot, now_fn())
    if isinstance(final, Blocked):
        return Outcome(SubmitStatus.BLOCKED, f"pre-submit re-check failed: {final.reason}")

    if final.player_id != initial.player_id:
        # Fallback path: only legal if the fresh snapshot PROVES the primary
        # is gone. (Safety of clock/state was just re-proven by the re-check.)
        drafted_ids = {p.player_id for p in fresh_state.picks}
        if initial.player_id not in drafted_ids:
            return Outcome(
                SubmitStatus.BLOCKED,
                "candidate changed without snapshot evidence that the primary is gone",
            )

    # 4. Exactly one submit call for this intent.
    result = actuator.submit(final)
    if not result.accepted:
        return Outcome(
            SubmitStatus.HALT,
            f"submit not accepted ({result.detail or 'no detail'}); "
            "manual takeover — no retry",
            intent=final,
            submit_calls=1,
        )

    # 5. Require a confirming snapshot before continuing. Missing/erroring
    #    confirmation halts for manual takeover; the click is never repeated.
    try:
        confirmed_state, _ = apply_snapshot(
            fresh_state, fetch_snapshot(), now_fn(), player_lookup
        )
    except SnapshotError as exc:
        return Outcome(
            SubmitStatus.HALT,
            f"confirmation snapshot malformed: {exc}; manual takeover — no retry",
            intent=final,
            submit_calls=1,
        )
    if not _pick_confirmed(confirmed_state, final):
        return Outcome(
            SubmitStatus.HALT,
            f"pick {final.player_name!r} not confirmed at overall "
            f"{final.expected_overall}; manual takeover — no retry",
            intent=final,
            submit_calls=1,
        )
    return Outcome(
        SubmitStatus.SUBMITTED,
        f"verified {final.player_name!r} at overall {final.expected_overall}",
        intent=final,
        submit_calls=1,
    )
