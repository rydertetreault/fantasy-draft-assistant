"""Behavioral scenarios: TeamIdentity + Allowlist guard (Checkpoint 1, Task 1).

Contract under test (per docs/live-draft-operator.spec.md and TEAM_SAFETY.md):

    from fantasy_draft_assistant.safety import TeamIdentity, Allowlist, can_submit

    def can_submit(identity: TeamIdentity, allowlist: Allowlist, state_age_ms: int) -> bool

- Exact allowlist match required before any write action.
- Default deny: any unknown team/league combination is rejected.
- Any alias in FORBIDDEN_ALIASES must NEVER pass, regardless of ids (tested
  via a sentinel alias injected with monkeypatch; the set is empty by default
  since RoughRydas was removed 2026-09-06 on owner authorization).
- Ambiguous/partial identity (missing ids) is rejected.
- Write actions are blocked when state_age_ms > 3000 (stale state fails closed).
"""

import pytest

from fantasy_draft_assistant import safety
from fantasy_draft_assistant.safety import Allowlist, TeamIdentity, can_submit

# Immutable identifiers from TEAM_SAFETY.md / config.synaps1.yaml
SYNAPS1_LEAGUE_ID = 305025860
SYNAPS1_TEAM_ID = 2
SYNAPS1_SEASON = 2026


def synaps1_identity() -> TeamIdentity:
    return TeamIdentity(
        alias="synaps1",
        league_id=SYNAPS1_LEAGUE_ID,
        team_id=SYNAPS1_TEAM_ID,
        season=SYNAPS1_SEASON,
    )


@pytest.fixture
def allowlist() -> Allowlist:
    return Allowlist([synaps1_identity()])


FRESH = 0  # ms; comfortably within the 3000 ms freshness budget


# ---------------------------------------------------------------------------
# Exact-match allow
# ---------------------------------------------------------------------------

class TestExactMatchAllow:
    def test_synaps1_exact_identity_is_allowed(self, allowlist):
        assert can_submit(synaps1_identity(), allowlist, state_age_ms=FRESH) is True

    def test_membership_operator_matches_exact_identity(self, allowlist):
        # Spec code style: `identity in allowlist`
        assert synaps1_identity() in allowlist

    def test_fresh_state_at_exact_threshold_is_allowed(self, allowlist):
        # spec: state_age_ms <= 3_000 is acceptable
        assert can_submit(synaps1_identity(), allowlist, state_age_ms=3000) is True


# ---------------------------------------------------------------------------
# Default deny for unknown identities
# ---------------------------------------------------------------------------

class TestDefaultDeny:
    def test_unknown_team_alias_is_denied(self, allowlist):
        stranger = TeamIdentity(
            alias="some_random_team",
            league_id=999999999,
            team_id=7,
            season=2026,
        )
        assert can_submit(stranger, allowlist, state_age_ms=FRESH) is False

    def test_wrong_league_id_is_denied(self, allowlist):
        imposter = TeamIdentity(
            alias="synaps1",
            league_id=111111111,  # not Synaps1's league
            team_id=SYNAPS1_TEAM_ID,
            season=SYNAPS1_SEASON,
        )
        assert can_submit(imposter, allowlist, state_age_ms=FRESH) is False

    def test_wrong_team_id_is_denied(self, allowlist):
        imposter = TeamIdentity(
            alias="synaps1",
            league_id=SYNAPS1_LEAGUE_ID,
            team_id=3,  # not team 2
            season=SYNAPS1_SEASON,
        )
        assert can_submit(imposter, allowlist, state_age_ms=FRESH) is False

    def test_wrong_season_is_denied(self, allowlist):
        imposter = TeamIdentity(
            alias="synaps1",
            league_id=SYNAPS1_LEAGUE_ID,
            team_id=SYNAPS1_TEAM_ID,
            season=2025,
        )
        assert can_submit(imposter, allowlist, state_age_ms=FRESH) is False

    def test_empty_allowlist_denies_everything(self):
        empty = Allowlist([])
        assert can_submit(synaps1_identity(), empty, state_age_ms=FRESH) is False


# ---------------------------------------------------------------------------
# Forbidden aliases must NEVER pass (mechanism tested with a sentinel alias)
# ---------------------------------------------------------------------------

SENTINEL = "forbidden-sentinel"


@pytest.fixture
def forbidden_sentinel(monkeypatch):
    """Inject a sentinel into FORBIDDEN_ALIASES so the mechanism stays tested."""
    monkeypatch.setattr(safety, "FORBIDDEN_ALIASES", frozenset({SENTINEL}))
    return SENTINEL


class TestForbiddenAliasProtection:
    @pytest.mark.parametrize(
        "league_id,team_id,season",
        [
            (123456, 1, 2026),
            (305025860, 2, 2026),  # even wearing Synaps1's exact ids
            (305025860, 5, 2026),
            (0, 0, 0),
        ],
    )
    def test_forbidden_alias_never_passes(
        self, allowlist, forbidden_sentinel, league_id, team_id, season
    ):
        forbidden = TeamIdentity(
            alias=forbidden_sentinel,
            league_id=league_id,
            team_id=team_id,
            season=season,
        )
        assert forbidden.is_forbidden
        assert can_submit(forbidden, allowlist, state_age_ms=FRESH) is False

    def test_forbidden_alias_case_variants_never_pass(self, allowlist, forbidden_sentinel):
        for alias in (
            "forbidden-sentinel",
            "FORBIDDEN-SENTINEL",
            "Forbidden-Sentinel",
            " forbidden-Sentinel ",
        ):
            forbidden = TeamIdentity(
                alias=alias,
                league_id=SYNAPS1_LEAGUE_ID,
                team_id=SYNAPS1_TEAM_ID,
                season=SYNAPS1_SEASON,
            )
            assert forbidden.is_forbidden, alias
            assert can_submit(forbidden, allowlist, state_age_ms=FRESH) is False, alias

    def test_forbidden_alias_cannot_be_added_to_an_allowlist(self, forbidden_sentinel):
        forbidden = TeamIdentity(
            alias=forbidden_sentinel, league_id=1, team_id=1, season=2026
        )
        # Either construction refuses it, or the resulting guard still denies it.
        try:
            poisoned = Allowlist([forbidden])
        except (ValueError, PermissionError):
            return  # refusing construction is acceptable fail-closed behavior
        assert can_submit(forbidden, poisoned, state_age_ms=FRESH) is False

    def test_forbidden_set_is_empty_by_default(self):
        # RoughRydas removed 2026-09-06 (owner authorization); nothing replaced it.
        assert safety.FORBIDDEN_ALIASES == frozenset()


class TestRoughRydasAuthorized:
    """2026-09-06: the owner authorized drafting for RoughRydas.

    It is no longer in FORBIDDEN_ALIASES, so a complete identity with that
    alias behaves like any other team: allowlistable and submittable when fresh.
    """

    def test_roughrydas_can_be_allowlisted_and_submits_when_fresh(self):
        rough = TeamIdentity(
            alias="RoughRydas", league_id=305025860, team_id=7, season=2026
        )
        assert rough.is_forbidden is False
        allowlist = Allowlist([rough])
        assert rough in allowlist
        assert can_submit(rough, allowlist, state_age_ms=FRESH) is True


# ---------------------------------------------------------------------------
# Ambiguous / partial identity is rejected
# ---------------------------------------------------------------------------

class TestAmbiguousIdentity:
    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(alias="synaps1", league_id=None, team_id=SYNAPS1_TEAM_ID, season=SYNAPS1_SEASON),
            dict(alias="synaps1", league_id=SYNAPS1_LEAGUE_ID, team_id=None, season=SYNAPS1_SEASON),
            dict(alias="synaps1", league_id=SYNAPS1_LEAGUE_ID, team_id=SYNAPS1_TEAM_ID, season=None),
            dict(alias="synaps1", league_id=None, team_id=None, season=None),
            dict(alias=None, league_id=SYNAPS1_LEAGUE_ID, team_id=SYNAPS1_TEAM_ID, season=SYNAPS1_SEASON),
        ],
    )
    def test_partial_identity_is_rejected(self, allowlist, kwargs):
        # Missing ids may be rejected at construction time or at guard time;
        # both are acceptable, but the guard must never say True.
        try:
            partial = TeamIdentity(**kwargs)
        except (TypeError, ValueError):
            return  # refusing to build an ambiguous identity is fail-closed
        assert can_submit(partial, allowlist, state_age_ms=FRESH) is False

    def test_synaps2_is_not_enabled_until_ids_are_mapped(self, allowlist):
        # TEAM_SAFETY.md: Synaps2 ESPN IDs are not mapped yet -> cannot write.
        try:
            synaps2 = TeamIdentity(
                alias="synaps2", league_id=None, team_id=None, season=None
            )
        except (TypeError, ValueError):
            return
        assert can_submit(synaps2, allowlist, state_age_ms=FRESH) is False


# ---------------------------------------------------------------------------
# Stale state blocks write actions
# ---------------------------------------------------------------------------

class TestStaleState:
    @pytest.mark.parametrize("age_ms", [3001, 5000, 60_000, 10**9])
    def test_stale_state_blocks_even_allowlisted_identity(self, allowlist, age_ms):
        assert can_submit(synaps1_identity(), allowlist, state_age_ms=age_ms) is False

    def test_stale_state_and_unknown_identity_still_denied(self, allowlist):
        stranger = TeamIdentity(alias="nobody", league_id=1, team_id=1, season=2026)
        assert can_submit(stranger, allowlist, state_age_ms=99_999) is False
