"""Carried-forward fixes from the Checkpoint 1 convergence verdict.

1. Negative state_age_ms fails closed (clock skew = unknown freshness).
2. Boolean id fields are rejected by TeamIdentity completeness.
3. Path-traversal aliases are rejected; RoughRydas allowlisting raises
   PermissionError specifically (not just any denial).
4. DraftState carries saved_at and league/season binding validated on load.
"""

import pytest

from fantasy_draft_assistant.models import DraftState
from fantasy_draft_assistant.safety import Allowlist, TeamIdentity, can_submit

SYNAPS1 = TeamIdentity(alias="synaps1", league_id=305025860, team_id=2, season=2026)


@pytest.fixture
def allowlist() -> Allowlist:
    return Allowlist([SYNAPS1])


class TestNegativeStateAge:
    @pytest.mark.parametrize("age_ms", [-1, -3000, -(10**12)])
    def test_negative_age_fails_closed_even_for_allowlisted(self, allowlist, age_ms):
        assert can_submit(SYNAPS1, allowlist, state_age_ms=age_ms) is False

    def test_non_int_age_fails_closed(self, allowlist):
        assert can_submit(SYNAPS1, allowlist, state_age_ms=None) is False  # type: ignore[arg-type]
        assert can_submit(SYNAPS1, allowlist, state_age_ms=True) is False  # type: ignore[arg-type]

    def test_zero_and_threshold_still_allowed(self, allowlist):
        assert can_submit(SYNAPS1, allowlist, state_age_ms=0) is True
        assert can_submit(SYNAPS1, allowlist, state_age_ms=3000) is True


class TestBooleanIdRejection:
    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(alias="synaps1", league_id=True, team_id=2, season=2026),
            dict(alias="synaps1", league_id=305025860, team_id=True, season=2026),
            dict(alias="synaps1", league_id=305025860, team_id=2, season=False),
        ],
    )
    def test_bool_id_fields_are_incomplete(self, allowlist, kwargs):
        identity = TeamIdentity(**kwargs)
        assert identity.is_complete is False
        assert can_submit(identity, allowlist, state_age_ms=0) is False

    def test_bool_id_identity_cannot_be_allowlisted(self):
        bogus = TeamIdentity(alias="synaps1", league_id=305025860, team_id=True, season=2026)
        with pytest.raises(ValueError):
            Allowlist([bogus])


class TestPathTraversalAlias:
    @pytest.mark.parametrize(
        "alias",
        ["../synaps1", "..", "a/../b", "synaps1/../../etc", "/etc/passwd", "a\\b"],
    )
    def test_traversal_alias_rejected_at_state_construction(self, alias):
        with pytest.raises(ValueError):
            DraftState(team=alias)

    @pytest.mark.parametrize("alias", ["../synaps1", "..", "x/y"])
    def test_traversal_alias_rejected_at_load(self, tmp_path, alias):
        with pytest.raises(ValueError):
            DraftState.load(tmp_path, alias)


class TestRoughRydasPermissionError:
    def test_allowlisting_roughrydas_raises_permission_error_specifically(self):
        rough = TeamIdentity(alias="RoughRydas", league_id=1, team_id=1, season=2026)
        with pytest.raises(PermissionError):
            Allowlist([rough])

    @pytest.mark.parametrize("alias", ["roughrydas", " RoughRydas ", "ROUGHRYDAS"])
    def test_variants_also_raise_permission_error(self, alias):
        rough = TeamIdentity(alias=alias, league_id=305025860, team_id=2, season=2026)
        with pytest.raises(PermissionError):
            Allowlist([rough])


class TestDraftStateBinding:
    def test_save_writes_saved_at_timestamp(self, tmp_path):
        state = DraftState(team="synaps1", league_id=305025860, season=2026)
        state.save(tmp_path)
        loaded = DraftState.load(tmp_path, "synaps1")
        assert loaded.saved_at is not None
        assert "T" in loaded.saved_at  # ISO-8601

    def test_load_refuses_wrong_league_binding(self, tmp_path):
        DraftState(team="synaps1", league_id=111, season=2026).save(tmp_path)
        with pytest.raises(ValueError, match="league"):
            DraftState.load(tmp_path, "synaps1", league_id=305025860, season=2026)

    def test_load_refuses_wrong_season_binding(self, tmp_path):
        DraftState(team="synaps1", league_id=305025860, season=2025).save(tmp_path)
        with pytest.raises(ValueError, match="season"):
            DraftState.load(tmp_path, "synaps1", league_id=305025860, season=2026)

    def test_matching_binding_loads_fine(self, tmp_path):
        DraftState(team="synaps1", league_id=305025860, season=2026).save(tmp_path)
        loaded = DraftState.load(tmp_path, "synaps1", league_id=305025860, season=2026)
        assert loaded.league_id == 305025860
        assert loaded.season == 2026
