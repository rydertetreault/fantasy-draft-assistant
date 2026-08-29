"""Refuse-by-default scenarios for the Yahoo adapter scaffold.

Contract (mirrors tests/test_safety.py; see yahoo_safety.py and hard rules in
docs/yahoo-adapter.research.md):

    from fantasy_draft_assistant.yahoo_safety import (
        YahooTeamIdentity, YahooAllowlist, build_default_allowlist, can_submit_yahoo,
    )

- The DEFAULT allowlist contains EXACTLY ONE owner-confirmed team:
  "allidoiswin" = All I Do Is Win, team key 470.l.384341.t.6, season 2026
  (confirmed 2026-08-29). Every OTHER identity, however plausible, must be
  refused.
- Exact five-field match (alias, game_key, league_id, team_id, season) is
  required even against a populated allowlist.
- RoughRydas can NEVER pass or be allowlisted (PermissionError, reusing the
  ESPN forbidden-alias set).
- Ambiguous/partial identity fails closed; bools are not ids.
- Stale (>3000 ms) or negative state age blocks even allowlisted identities.
- The actuation scripts (yahoo_actuate.mjs, yahoo_set_prerank.mjs) refuse at
  their gates for any non-allowlisted team — verified via real subprocesses
  when node is available.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fantasy_draft_assistant.safety import FORBIDDEN_ALIASES, MAX_STATE_AGE_MS
from fantasy_draft_assistant.yahoo_safety import (
    YahooAllowlist,
    YahooTeamIdentity,
    build_default_allowlist,
    can_submit_yahoo,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FRESH = 0  # ms

# A plausible-looking Yahoo identity that is NOT the confirmed team. It must
# refuse against the default allowlist (exact-match only, no partial credit).
PLAUSIBLE = YahooTeamIdentity(
    alias="yahoo1", game_key="461", league_id=123456, team_id=7, season=2026
)

# The single owner-confirmed team (2026-08-29): the ONLY identity the default
# allowlist may ever pass.
CONFIRMED = YahooTeamIdentity(
    alias="allidoiswin", game_key="470", league_id=384341, team_id=6, season=2026
)


def _identity(**overrides) -> YahooTeamIdentity:
    base = dict(alias="yahoo1", game_key="461", league_id=123456, team_id=7, season=2026)
    base.update(overrides)
    return YahooTeamIdentity(**base)


# ---------------------------------------------------------------------------
# The default allowlist: exactly ONE confirmed team; everything else refuses
# ---------------------------------------------------------------------------

class TestDefaultAllowlist:
    def test_default_allowlist_has_exactly_the_confirmed_entry(self):
        allowlist = build_default_allowlist()
        assert len(allowlist) == 1
        assert list(allowlist) == [CONFIRMED]

    def test_confirmed_identity_is_allowed_when_fresh(self):
        assert can_submit_yahoo(CONFIRMED, build_default_allowlist(), FRESH) is True

    def test_confirmed_team_key(self):
        assert CONFIRMED.team_key == "470.l.384341.t.6"

    def test_confirmed_ids_with_wrong_season_refused(self):
        wrong_season = YahooTeamIdentity(
            alias="allidoiswin", game_key="470", league_id=384341, team_id=6, season=2025
        )
        assert can_submit_yahoo(wrong_season, build_default_allowlist(), FRESH) is False

    def test_confirmed_ids_with_imposter_alias_refused(self):
        imposter = YahooTeamIdentity(
            alias="RoughRydas", game_key="470", league_id=384341, team_id=6, season=2026
        )
        assert imposter not in build_default_allowlist()
        assert can_submit_yahoo(imposter, build_default_allowlist(), FRESH) is False

    def test_plausible_identity_refused_by_default(self):
        assert can_submit_yahoo(PLAUSIBLE, build_default_allowlist(), FRESH) is False

    def test_membership_operator_refuses_non_confirmed(self):
        assert PLAUSIBLE not in build_default_allowlist()

    @pytest.mark.parametrize(
        "identity",
        [
            _identity(),
            _identity(alias="synaps1"),  # even ESPN-authorized aliases don't carry over
            _identity(alias="synaps2", league_id=2144943745, team_id=4),
            _identity(game_key="nfl"),
            _identity(league_id=1, team_id=1),
            _identity(alias="allidoiswin"),  # right alias, wrong ids
        ],
        ids=[
            "yahoo1", "espn-alias-synaps1", "espn-alias-synaps2", "game-code",
            "tiny-ids", "right-alias-wrong-ids",
        ],
    )
    def test_every_non_confirmed_identity_refused(self, identity):
        assert can_submit_yahoo(identity, build_default_allowlist(), FRESH) is False


# ---------------------------------------------------------------------------
# Exact-match semantics (against a hypothetical populated allowlist)
# ---------------------------------------------------------------------------

class TestExactMatchSemantics:
    @pytest.fixture
    def allowlist(self) -> YahooAllowlist:
        return YahooAllowlist([_identity()])

    def test_exact_identity_is_allowed_when_explicitly_listed(self, allowlist):
        assert can_submit_yahoo(_identity(), allowlist, FRESH) is True

    @pytest.mark.parametrize(
        "overrides",
        [
            {"alias": "yahoo2"},
            {"game_key": "462"},
            {"game_key": "nfl"},  # code vs id must not cross-match
            {"league_id": 123457},
            {"team_id": 8},
            {"season": 2027},
        ],
        ids=["alias", "game_key", "game-code-alias", "league_id", "team_id", "season"],
    )
    def test_any_single_field_mismatch_is_denied(self, allowlist, overrides):
        assert can_submit_yahoo(_identity(**overrides), allowlist, FRESH) is False

    def test_non_identity_object_is_denied(self, allowlist):
        assert "yahoo1" not in allowlist
        assert None not in allowlist

    def test_alias_normalization_matches_espn_semantics(self, allowlist):
        assert can_submit_yahoo(_identity(alias="  YaHoo1 "), allowlist, FRESH) is True

    def test_team_key_built_only_for_complete_identity(self):
        assert _identity().team_key == "461.l.123456.t.7"
        assert _identity(team_id=None).team_key is None


# ---------------------------------------------------------------------------
# RoughRydas can never pass or be allowlisted
# ---------------------------------------------------------------------------

class TestForbiddenTeam:
    def test_forbidden_aliases_are_shared_with_espn_guard(self):
        assert "roughrydas" in FORBIDDEN_ALIASES

    @pytest.mark.parametrize("alias", ["RoughRydas", "roughrydas", "  ROUGHRYDAS  "])
    def test_allowlisting_roughrydas_raises_permission_error(self, alias):
        with pytest.raises(PermissionError):
            YahooAllowlist([_identity(alias=alias)])

    def test_roughrydas_denied_even_if_entries_share_its_ids(self):
        allowlist = YahooAllowlist([_identity()])
        imposter = _identity(alias="RoughRydas")
        assert imposter not in allowlist
        assert can_submit_yahoo(imposter, allowlist, FRESH) is False


# ---------------------------------------------------------------------------
# Ambiguous / partial identity fails closed
# ---------------------------------------------------------------------------

class TestIncompleteIdentity:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"alias": None},
            {"alias": "   "},
            {"game_key": None},
            {"game_key": ""},
            {"game_key": "461.l.9"},  # a full league key is NOT a game key
            {"league_id": None},
            {"team_id": None},
            {"season": None},
            {"team_id": True},  # bools are not ids
            {"league_id": False},
        ],
        ids=[
            "no-alias", "blank-alias", "no-game-key", "blank-game-key",
            "league-key-as-game-key", "no-league", "no-team", "no-season",
            "bool-team", "bool-league",
        ],
    )
    def test_incomplete_identity_cannot_be_allowlisted(self, overrides):
        with pytest.raises(ValueError):
            YahooAllowlist([_identity(**overrides)])

    def test_incomplete_identity_is_denied_by_populated_allowlist(self):
        allowlist = YahooAllowlist([_identity()])
        assert can_submit_yahoo(_identity(season=None), allowlist, FRESH) is False

    def test_non_identity_entry_raises_type_error(self):
        with pytest.raises(TypeError):
            YahooAllowlist(["yahoo1"])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Freshness gate (same 3000 ms budget as ESPN)
# ---------------------------------------------------------------------------

class TestFreshness:
    @pytest.fixture
    def allowlist(self) -> YahooAllowlist:
        return YahooAllowlist([_identity()])

    def test_exact_threshold_is_allowed(self, allowlist):
        assert can_submit_yahoo(_identity(), allowlist, MAX_STATE_AGE_MS) is True

    def test_stale_state_is_denied(self, allowlist):
        assert can_submit_yahoo(_identity(), allowlist, MAX_STATE_AGE_MS + 1) is False

    def test_negative_age_clock_skew_is_denied(self, allowlist):
        assert can_submit_yahoo(_identity(), allowlist, -1) is False

    def test_bool_age_is_denied(self, allowlist):
        assert can_submit_yahoo(_identity(), allowlist, True) is False


# ---------------------------------------------------------------------------
# Script-level refusal behavior (real subprocesses; skipped without node)
# ---------------------------------------------------------------------------

node_missing = shutil.which("node") is None


@pytest.mark.skipif(node_missing, reason="node not found")
class TestScriptRefusals:
    def _run(self, *argv):
        return subprocess.run(
            ["node", *argv], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
        )

    def test_yahoo_actuate_refuses_valid_grant_for_unlisted_alias(self, tmp_path):
        """Even a well-formed, in-window grant refuses: alias not allowlisted."""
        grant = {
            "alias": "yahoo1",
            "league_id": 123456,
            "season": 2026,
            "draft_session_id": "461.l.123456-2026-1788127200000",
            "issued_at_ms": 0,
            "expires_at_ms": 9_999_999_999_999,
        }
        grant_file = tmp_path / "grant.json"
        grant_file.write_text(json.dumps(grant))
        proc = self._run(
            "scripts/yahoo_actuate.mjs",
            json.dumps({"playerId": 1, "playerName": "Test Player", "leagueId": 123456, "teamId": 7}),
            "--grant-file", str(grant_file),
        )
        assert proc.returncode == 3, proc.stderr
        assert "REFUSED" in proc.stderr
        assert "not allowlisted" in proc.stderr
        assert "DRY-RUN" not in proc.stdout and "LIVE" not in proc.stdout

    def test_yahoo_actuate_refuses_roughrydas_grant_explicitly(self, tmp_path):
        grant_file = tmp_path / "grant.json"
        grant_file.write_text(json.dumps({"alias": "RoughRydas", "league_id": 123456,
                                          "issued_at_ms": 0, "expires_at_ms": 9e15}))
        proc = self._run(
            "scripts/yahoo_actuate.mjs",
            json.dumps({"playerId": 1, "playerName": "Test Player", "leagueId": 123456, "teamId": 7}),
            "--grant-file", str(grant_file),
        )
        assert proc.returncode == 3, proc.stderr
        assert "forbidden" in proc.stderr.lower()

    def test_yahoo_actuate_requires_grant_file(self):
        proc = self._run(
            "scripts/yahoo_actuate.mjs",
            json.dumps({"playerId": 1, "playerName": "Test Player", "leagueId": 123456, "teamId": 7}),
        )
        assert proc.returncode == 2, proc.stderr
        assert "--grant-file is required" in proc.stderr

    def test_yahoo_actuate_live_flag_still_refuses(self, tmp_path):
        grant_file = tmp_path / "grant.json"
        grant_file.write_text(json.dumps({"alias": "yahoo1", "league_id": 123456,
                                          "draft_session_id": "x",
                                          "issued_at_ms": 0, "expires_at_ms": 9e15}))
        proc = self._run(
            "scripts/yahoo_actuate.mjs",
            json.dumps({"playerId": 1, "playerName": "Test Player", "leagueId": 123456, "teamId": 7}),
            "--grant-file", str(grant_file), "--live",
        )
        assert proc.returncode == 3, proc.stderr
        assert "REFUSED" in proc.stderr
        assert "LIVE" not in proc.stdout

    def test_yahoo_set_prerank_refuses_unlisted_team(self, tmp_path):
        prerank = tmp_path / "prerank.json"
        prerank.write_text(json.dumps([101, 102, 103]))
        proc = self._run(
            "scripts/yahoo_set_prerank.mjs", str(prerank), "--league", "123456", "--team", "7",
        )
        assert proc.returncode == 3, proc.stderr
        assert "REFUSED" in proc.stderr
        assert "not an allowlisted" in proc.stderr

    def test_yahoo_poll_refuses_without_league_key(self):
        proc = self._run("scripts/yahoo_poll.mjs")  # no TEAM/YAHOO_LEAGUE_KEY env
        assert proc.returncode == 2, proc.stderr
        assert "REFUSED" in proc.stderr

    def test_yahoo_fetch_refuses_without_league_key(self):
        proc = self._run("scripts/yahoo_fetch.mjs")
        assert proc.returncode == 2, proc.stderr
        assert "REFUSED" in proc.stderr
        assert "no Yahoo league is configured" in proc.stderr
