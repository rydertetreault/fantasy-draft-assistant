"""Preflight tests (Checkpoint 3, Task 9 + carried CP2 feedback 4)."""

import json
import os
import time
from pathlib import Path

import pytest
import yaml

from fantasy_draft_assistant.preflight import run_preflight

from test_operator import CONFIG, LEAGUE, SEASON

REPO = Path(__file__).resolve().parents[1]

DRAFT_DATE_MS = 1788040800000
SESSION = f"{LEAGUE}-{SEASON}-{DRAFT_DATE_MS}"

BOARD_CSV = (
    "player,espn_player_id,pos,nfl_team_id,projection,last_season_points,"
    "adp,percent_owned,injury_status,tier\n"
    + "\n".join(
        f"Player {i},{1000 + i},{pos},1,{300 - i * 4}.0,,{i}.0,99.0,ACTIVE,1"
        for i, pos in enumerate(
            ["QB", "RB", "WR", "RB", "WR", "TE", "RB", "WR", "QB", "RB",
             "WR", "TE", "RB", "WR", "QB", "RB", "WR", "TE", "RB", "WR"]
        )
    )
    + "\n"
)


def check_map(report):
    return {c["name"]: c for c in report["checks"]}


@pytest.fixture
def workspace(tmp_path):
    """A fully healthy preflight workspace."""
    config_path = tmp_path / "config.synaps1.yaml"
    config_path.write_text(yaml.safe_dump(CONFIG))
    team_dir = tmp_path / "data" / "synaps1"
    team_dir.mkdir(parents=True)
    (team_dir / "board.csv").write_text(BOARD_CSV)
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir()
    (raw_dir / "players.json").write_text("{}")
    (raw_dir / "league_settings.json").write_text(
        json.dumps(
            {
                "id": LEAGUE,
                "seasonId": SEASON,
                "settings": {"draftSettings": {"date": DRAFT_DATE_MS}},
                "draftDetail": {"drafted": False, "inProgress": False},
            }
        )
    )
    return tmp_path


def preflight(workspace, **kwargs):
    return run_preflight(
        "synaps1",
        config_path=workspace / "config.synaps1.yaml",
        data_dir=workspace / "data",
        **kwargs,
    )


class TestHappyPath:
    def test_all_checks_pass_and_report_is_written(self, workspace):
        report = preflight(workspace)
        checks = check_map(report)
        assert report["ok"] is True
        for name in (
            "config",
            "identity-allowlist",
            "roughrydas-selftest",
            "board",
            "board-freshness",
            "raw-source-freshness",
            "draft-session",
            "replay-smoke",
            "timing-budget",
        ):
            assert checks[name]["status"] == "pass", checks[name]
        # Session id printed for grant issuance (CP2 feedback 1).
        assert SESSION in checks["draft-session"]["detail"]
        assert "draft_session_id" in checks["draft-session"]["detail"]
        # Timestamped JSON report on disk.
        on_disk = json.loads(
            (workspace / "data" / "synaps1" / "preflight_report.json").read_text()
        )
        assert on_disk["ok"] is True
        assert on_disk["observed_session_id"] == SESSION
        assert on_disk["generated_at"].endswith("+00:00")

    def test_replay_smoke_actually_drafts_three_rounds(self, workspace):
        report = preflight(workspace)
        detail = check_map(report)["replay-smoke"]["detail"]
        assert "3/3 picks confirmed" in detail


class TestStalenessWarnings:
    def test_old_board_and_raw_source_warn_but_do_not_fail(self, workspace):
        old = time.time() - 24 * 3600
        os.utime(workspace / "data" / "synaps1" / "board.csv", (old, old))
        os.utime(workspace / "data" / "raw" / "players.json", (old, old))
        report = preflight(workspace)
        checks = check_map(report)
        assert checks["board-freshness"]["status"] == "warn"
        assert "refresh before draft" in checks["board-freshness"]["detail"]
        assert checks["raw-source-freshness"]["status"] == "warn"
        assert report["ok"] is True  # warnings are soft

    def test_max_age_is_configurable(self, workspace):
        old = time.time() - 2 * 3600
        os.utime(workspace / "data" / "synaps1" / "board.csv", (old, old))
        assert (
            check_map(preflight(workspace, max_age_hours=1.0))["board-freshness"]["status"]
            == "warn"
        )
        assert (
            check_map(preflight(workspace, max_age_hours=12.0))["board-freshness"]["status"]
            == "pass"
        )


class TestHardFailures:
    def test_missing_config_fails(self, tmp_path):
        report = run_preflight(
            "synaps1", config_path=tmp_path / "nope.yaml", data_dir=tmp_path / "data"
        )
        assert report["ok"] is False
        assert check_map(report)["config"]["status"] == "fail"

    def test_missing_board_fails(self, workspace):
        (workspace / "data" / "synaps1" / "board.csv").unlink()
        report = preflight(workspace)
        assert report["ok"] is False
        assert check_map(report)["board"]["status"] == "fail"

    def test_forbidden_configured_team_fails_allowlist_check(self, workspace):
        bad = dict(CONFIG)
        bad["espn"] = {**CONFIG["espn"], "authorized_team": "RoughRydas"}
        (workspace / "config.synaps1.yaml").write_text(yaml.safe_dump(bad))
        report = preflight(workspace)
        assert report["ok"] is False
        assert check_map(report)["identity-allowlist"]["status"] == "fail"

    def test_session_league_mismatch_fails(self, workspace):
        settings = workspace / "data" / "raw" / "league_settings.json"
        payload = json.loads(settings.read_text())
        payload["id"] = 999999
        settings.write_text(json.dumps(payload))
        report = preflight(workspace)
        assert report["ok"] is False
        assert check_map(report)["draft-session"]["status"] == "fail"


class TestReplaySmokeTeamCount:
    """Regression: replay-smoke must honor the config team count.

    Bug: preflight generated its smoke script with the 10-team
    DEFAULT_PICK_ORDER while ReplayRunner sized the draft from
    config['league']['teams'] — for a 12-team league the smoke degraded to a
    silent no-op (confirmed=0 blocked=0 halts=0).
    """

    TWELVE_LEAGUE = 2144943745

    def run_for(self, tmp_path, *, teams, team_id, alias="synaps2"):
        config = {
            "espn": {
                "league_id": self.TWELVE_LEAGUE,
                "team_id": team_id,
                "season_id": SEASON,
                "authorized_team": alias.capitalize(),
            },
            "league": {
                "teams": teams,
                "roster_slots": {
                    "QB": 1, "RB": 2, "WR": 2, "TE": 1,
                    "FLEX": 1, "DST": 1, "K": 1,
                },
            },
            "strategy": {"wait_until_round": {"DST": 14, "K": 15}},
        }
        config_path = tmp_path / f"config.{alias}.yaml"
        config_path.write_text(yaml.safe_dump(config))
        team_dir = tmp_path / "data" / alias
        team_dir.mkdir(parents=True)
        (team_dir / "board.csv").write_text(BOARD_CSV)
        raw_dir = tmp_path / "data" / "raw"
        raw_dir.mkdir()
        (raw_dir / "players.json").write_text("{}")
        (raw_dir / "league_settings.json").write_text(
            json.dumps(
                {
                    "id": self.TWELVE_LEAGUE,
                    "seasonId": SEASON,
                    "settings": {"draftSettings": {"date": DRAFT_DATE_MS}},
                    "draftDetail": {"drafted": False, "inProgress": False},
                }
            )
        )
        return run_preflight(
            alias, config_path=config_path, data_dir=tmp_path / "data"
        )

    def test_twelve_team_league_passes_replay_smoke(self, tmp_path):
        report = self.run_for(tmp_path, teams=12, team_id=4)
        checks = check_map(report)
        assert checks["replay-smoke"]["status"] == "pass", checks["replay-smoke"]
        assert "3/3 picks confirmed" in checks["replay-smoke"]["detail"]
        assert report["ok"] is True

    def test_team_id_outside_league_size_fails_loudly(self, tmp_path):
        report = self.run_for(tmp_path, teams=12, team_id=13)
        checks = check_map(report)
        assert checks["replay-smoke"]["status"] == "fail"
        # Explicit reason, not the silent-no-op "confirmed=0" symptom.
        assert "team_id 13" in checks["replay-smoke"]["detail"]
        assert "confirmed=0" not in checks["replay-smoke"]["detail"]
        assert report["ok"] is False


class TestReplayRunnerTeamCountMismatch:
    """A script whose pick_order disagrees with config team count must raise."""

    def test_mismatched_script_raises_instead_of_silent_noop(self, tmp_path):
        import io

        from fantasy_draft_assistant.pipeline import load_board
        from fantasy_draft_assistant.replay import ReplayRunner, generate_script

        board_path = tmp_path / "board.csv"
        board_path.write_text(BOARD_CSV)
        board_rows = load_board(board_path)
        config = {
            **CONFIG,
            "league": {**CONFIG["league"], "teams": 12},
        }
        # Default pick_order is 10 teams — disagrees with the 12-team config.
        script = generate_script(
            board_rows,
            tmp_path / "smoke.jsonl",
            rounds=3,
            our_team_id=2,
            league_id=LEAGUE,
            season=SEASON,
            alias="synaps1",
            include_faults=False,
        )
        with pytest.raises(ValueError, match="team"):
            ReplayRunner(config, board_rows).run(script)


class TestGrantValidation:
    def write_grant(self, workspace, **overrides):
        now_ms = int(time.time() * 1000)
        payload = {
            "alias": "synaps1",
            "league_id": LEAGUE,
            "season": SEASON,
            "draft_session_id": SESSION,
            "issued_at_ms": now_ms - 60_000,
            "expires_at_ms": now_ms + 3_600_000,
            **overrides,
        }
        path = workspace / "grant.json"
        path.write_text(json.dumps(payload))
        return path

    def test_valid_session_bound_grant_passes(self, workspace):
        path = self.write_grant(workspace)
        report = preflight(workspace, grant_path=path)
        assert check_map(report)["grant"]["status"] == "pass"
        assert report["ok"] is True

    def test_grant_for_other_session_fails(self, workspace):
        path = self.write_grant(workspace, draft_session_id="another-draft")
        report = preflight(workspace, grant_path=path)
        assert check_map(report)["grant"]["status"] == "fail"
        assert report["ok"] is False

    def test_expired_grant_fails(self, workspace):
        now_ms = int(time.time() * 1000)
        path = self.write_grant(workspace, expires_at_ms=now_ms - 1)
        report = preflight(workspace, grant_path=path)
        assert check_map(report)["grant"]["status"] == "fail"

    def test_missing_session_file_downgrades_to_warn_but_grant_still_checked(
        self, workspace
    ):
        (workspace / "data" / "raw" / "league_settings.json").unlink()
        path = self.write_grant(workspace)
        report = preflight(workspace, grant_path=path)
        checks = check_map(report)
        assert checks["draft-session"]["status"] == "warn"
        # Without an observed session the grant is validated on everything else.
        assert checks["grant"]["status"] == "pass"
