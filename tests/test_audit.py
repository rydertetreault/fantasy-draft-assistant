"""Audit log tests (Checkpoint 3, Task 8): append-only JSONL, UTC
timestamps, per-team isolation, and NO secrets ever on disk."""

import json

import pytest

from fantasy_draft_assistant.audit import (
    FORBIDDEN_KEY_PATTERNS,
    REDACTED,
    AuditLog,
    grant_audit_view,
    scrub,
)

from test_operator import grant


class TestAppendOnlyJsonl:
    def test_appends_timestamped_utc_records(self, tmp_path):
        log = AuditLog(tmp_path, "synaps1")
        log.log("operator.init", mode="observe")
        log.log("submit.blocked", reason="mode is observe, not autopick")
        lines = (tmp_path / "synaps1" / "audit.jsonl").read_text().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["event"] == "operator.init"
        assert first["team"] == "synaps1"
        # ISO-8601 UTC timestamp.
        assert first["ts"].endswith("+00:00")
        # Append-only: a second logger call added, never rewrote.
        log2 = AuditLog(tmp_path, "synaps1")
        log2.log("third")
        assert len(log.read_all()) == 3
        assert [e["event"] for e in log.read_all()][:2] == [
            "operator.init",
            "submit.blocked",
        ]

    def test_per_team_files_are_isolated(self, tmp_path):
        AuditLog(tmp_path, "synaps1").log("a")
        AuditLog(tmp_path, "synaps2").log("b")
        assert [e["event"] for e in AuditLog(tmp_path, "synaps1").read_all()] == ["a"]
        assert [e["event"] for e in AuditLog(tmp_path, "synaps2").read_all()] == ["b"]

    def test_bad_alias_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            AuditLog(tmp_path, "../evil")


class TestSecretFree:
    def test_scrub_redacts_forbidden_keys_recursively(self):
        dirty = {
            "reason": "ok",
            "espn_s2": "AEB...secret",
            "nested": {"Cookie": "sid=123", "list": [{"auth_token": "x"}]},
        }
        clean = scrub(dirty)
        assert clean["reason"] == "ok"
        assert clean["espn_s2"] == REDACTED
        assert clean["nested"]["Cookie"] == REDACTED
        assert clean["nested"]["list"][0]["auth_token"] == REDACTED

    def test_grant_audit_view_exposes_only_session_and_expiry(self):
        g = grant()
        view = grant_audit_view(g)
        assert set(view) == {"draft_session_id", "expires_at_ms"}

    def test_secret_scan_of_written_audit_fixture(self, tmp_path):
        """Write realistic events (including attacker-shaped fields) and
        grep the file for every forbidden key pattern's value."""
        log = AuditLog(tmp_path, "synaps1")
        log.log("operator.init", mode="autopick", **grant_audit_view(grant()))
        log.log(
            "login.debug",
            cookie="SWID={ABC-123}; espn_s2=SECRETVALUE",
            session_token="tok_LIVE_123",
            password="hunter2",
            note="legit note",
        )
        text = (tmp_path / "synaps1" / "audit.jsonl").read_text()
        for leaked in ("SECRETVALUE", "tok_LIVE_123", "hunter2", "{ABC-123}"):
            assert leaked not in text
        assert "legit note" in text
        # Grant contents beyond expiry + session id never appear.
        assert str(grant().issued_at_ms) not in text
        # And the scrubber's coverage list itself is intact.
        for pattern in ("cookie", "token", "password", "swid", "espn_s2"):
            assert pattern in FORBIDDEN_KEY_PATTERNS
