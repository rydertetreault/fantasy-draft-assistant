"""Carried CP2-verdict fixes (Checkpoint 3 entry gate).

1. MEDIUM — grants are bound to the observed draft session id derived from
   the league snapshot; exact match required once the session is known.
2. LOW — submit_intent derives round/slot from ``state.on_clock_overall``
   via snake math and blocks on caller mismatch.
3. LOW — raw exception text never leaks into Blocked reasons; full detail
   goes to the audit log only.

(4. LOW — board/raw staleness warnings live in preflight; see
tests/test_preflight.py.)
"""

import json

import pytest

from fantasy_draft_assistant.audit import AuditLog
from fantasy_draft_assistant.models import DraftState
from fantasy_draft_assistant.observer import apply_snapshot, derive_session_id
from fantasy_draft_assistant.operator import (
    Blocked,
    Mode,
    Operator,
    SubmitIntent,
    derive_turn,
    grant_is_valid,
)
from fantasy_draft_assistant.safety import Allowlist

from test_operator import (
    BOARD,
    CONFIG,
    LEAGUE,
    LOOKUP,
    NOW,
    SEASON,
    TEAM,
    fresh_state,
    grant,
    identity,
    slot_entry,
)

SESSION = f"{LEAGUE}-{SEASON}-1788040800000"


def league_snapshot(date_ms=1788040800000, **detail):
    payload = {
        "id": LEAGUE,
        "seasonId": SEASON,
        "draftDetail": {"drafted": False, "inProgress": False, **detail},
    }
    if date_ms is not None:
        payload["settings"] = {"draftSettings": {"date": date_ms}}
    return payload


class TestDeriveSessionId:
    def test_uses_league_season_and_draft_date(self):
        assert derive_session_id(league_snapshot()) == SESSION

    def test_falls_back_to_draft_phase_markers(self):
        assert (
            derive_session_id(league_snapshot(date_ms=None))
            == f"{LEAGUE}-{SEASON}-pending"
        )
        assert (
            derive_session_id(league_snapshot(date_ms=None, inProgress=True))
            == f"{LEAGUE}-{SEASON}-in-progress"
        )
        assert (
            derive_session_id(league_snapshot(date_ms=None, drafted=True))
            == f"{LEAGUE}-{SEASON}-drafted"
        )

    @pytest.mark.parametrize(
        "payload", [None, {}, {"id": "x", "seasonId": 2026}, {"id": 1, "seasonId": True}]
    )
    def test_unidentifiable_payload_returns_none(self, payload):
        assert derive_session_id(payload) is None

    def test_real_fixture_shape(self):
        raw = json.loads(
            '{"id": 305025860, "seasonId": 2026, '
            '"settings": {"draftSettings": {"date": 1788040800000}}, '
            '"draftDetail": {"drafted": false, "inProgress": false}}'
        )
        assert derive_session_id(raw) == "305025860-2026-1788040800000"


class TestGrantSessionBinding:
    def test_matching_observed_session_is_valid(self):
        g = grant(draft_session_id=SESSION)
        assert grant_is_valid(g, identity(), NOW, SESSION) is True

    def test_mismatched_observed_session_is_refused(self):
        g = grant(draft_session_id="draft-2026-08-29")
        assert grant_is_valid(g, identity(), NOW, SESSION) is False

    def test_unknown_session_still_requires_everything_else(self):
        # Session not yet observed: identity/window checks still apply.
        assert grant_is_valid(grant(), identity(), NOW, None) is True
        assert grant_is_valid(grant(alias="synaps2"), identity(), NOW, None) is False

    def test_operator_with_observed_session_caps_mismatched_grant(self):
        allowlist = Allowlist([identity()])
        op = Operator(
            CONFIG,
            allowlist,
            Mode.AUTOPICK,
            grant=grant(draft_session_id="some-other-session"),
            now_ms=NOW,
            observed_session_id=SESSION,
        )
        assert op.mode is Mode.ADVISORY

    def test_operator_submit_blocks_when_session_diverges_mid_draft(self):
        allowlist = Allowlist([identity()])
        op = Operator(
            CONFIG, allowlist, Mode.AUTOPICK, grant=grant(), now_ms=NOW
        )
        # The observer later pins the live session; the old grant no longer names it.
        op.observed_session_id = SESSION
        result = op.submit_intent(fresh_state(), BOARD, 1, 1, NOW)
        assert isinstance(result, Blocked)
        assert "grant" in result.reason


class TestDerivedTurn:
    @pytest.mark.parametrize(
        "overall,teams,expected",
        [
            (1, 10, (1, 1)),
            (10, 10, (1, 10)),
            (11, 10, (2, 10)),
            (18, 10, (2, 3)),
            (21, 10, (3, 1)),
            (160, 10, (16, 1)),
        ],
    )
    def test_snake_inverse(self, overall, teams, expected):
        assert derive_turn(overall, teams) == expected

    @pytest.mark.parametrize("bad", [0, -3, True, "7"])
    def test_bad_overall_rejected(self, bad):
        with pytest.raises(ValueError):
            derive_turn(bad, 10)

    def autopick_op(self):
        return Operator(
            CONFIG, Allowlist([identity()]), Mode.AUTOPICK, grant=grant(), now_ms=NOW
        )

    def test_caller_mismatch_blocks(self):
        op = self.autopick_op()
        # on-clock overall 1 => round 1, slot 1; caller claims slot 4.
        result = op.submit_intent(fresh_state(), BOARD, 1, 4, NOW)
        assert isinstance(result, Blocked)
        assert "disagrees with observed on-clock" in result.reason

    def test_caller_round_mismatch_blocks(self):
        op = self.autopick_op()
        result = op.submit_intent(fresh_state(), BOARD, 2, 1, NOW)
        assert isinstance(result, Blocked)
        assert "round" in result.reason

    def test_none_means_derive(self):
        op = self.autopick_op()
        intent = op.submit_intent(fresh_state(), BOARD, None, None, NOW)
        assert isinstance(intent, SubmitIntent)
        assert intent.expected_overall == 1
        assert "turn-derived-from-observed-state" in intent.checks

    def test_derived_turn_used_even_when_caller_matches(self):
        # Our team on the clock at overall 19 => round 2, slot 2.
        op = self.autopick_op()
        state = DraftState(team="synaps1", league_id=LEAGUE, season=SEASON)
        entries = [slot_entry(i, 5, 900_000 + i) for i in range(1, 19)]
        entries.append(slot_entry(19, TEAM))
        state, _ = apply_snapshot(state, {"draftDetail": {"picks": entries}}, NOW, LOOKUP)
        intent = op.submit_intent(state, BOARD, 2, 2, NOW)
        assert isinstance(intent, SubmitIntent)
        assert intent.expected_overall == 19
        blocked = op.submit_intent(state, BOARD, 2, 9, NOW)
        assert isinstance(blocked, Blocked)


class TestCappedErrorLeakage:
    class BoomBoard:
        def __iter__(self):
            raise RuntimeError("SECRET-DETAIL-42 /Users/someone/private/path")

    def test_reason_is_generic(self):
        op = Operator(
            CONFIG, Allowlist([identity()]), Mode.AUTOPICK, grant=grant(), now_ms=NOW
        )
        result = op.submit_intent(fresh_state(), self.BoomBoard(), 1, 1, NOW)
        assert isinstance(result, Blocked)
        assert "internal error" in result.reason
        assert "audit log" in result.reason
        assert "SECRET-DETAIL-42" not in result.reason
        assert "/Users/" not in result.reason

    def test_full_detail_goes_to_audit_log_only(self, tmp_path):
        audit = AuditLog(tmp_path, "synaps1")
        op = Operator(
            CONFIG,
            Allowlist([identity()]),
            Mode.AUTOPICK,
            grant=grant(),
            now_ms=NOW,
            audit=audit,
        )
        result = op.submit_intent(fresh_state(), self.BoomBoard(), 1, 1, NOW)
        assert isinstance(result, Blocked)
        assert "SECRET-DETAIL-42" not in result.reason
        text = (tmp_path / "synaps1" / "audit.jsonl").read_text()
        assert "SECRET-DETAIL-42" in text
        events = [json.loads(line)["event"] for line in text.splitlines()]
        assert "submit.internal_error" in events
        assert "submit.blocked" in events
