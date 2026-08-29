"""Append-only, secret-free audit log (Checkpoint 3, Task 8).

Every operator/actuator transition and attempted action is appended as one
JSON line to ``<data_dir>/<team>/audit.jsonl`` with a UTC timestamp. The log
is per-team (Synaps1 and Synaps2 never share a file) and is scrubbed:

- Keys matching :data:`FORBIDDEN_KEY_PATTERNS` (cookies, tokens, passwords,
  ESPN session identifiers, ...) are redacted recursively, whatever the value.
- Authorization grants are never logged wholesale; use :func:`grant_audit_view`
  which exposes only the session id and expiry (CP feedback: no grant
  contents beyond expiry + session id).

Full internal-error detail belongs HERE, not in user-facing Blocked reasons
(CP2 verdict, LOW: cap raw exception text leakage).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import _validate_alias

AUDIT_FILENAME = "audit.jsonl"

#: Any key whose lowercase name contains one of these substrings is redacted.
FORBIDDEN_KEY_PATTERNS: tuple[str, ...] = (
    "cookie",
    "token",
    "password",
    "passwd",
    "secret",
    "swid",
    "espn_s2",
    "mfa",
    "credential",
    "bearer",
    "api_key",
    "apikey",
)

REDACTED = "[REDACTED]"


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in FORBIDDEN_KEY_PATTERNS)


def scrub(value: Any) -> Any:
    """Recursively redact values held under secret-looking keys."""
    if isinstance(value, Mapping):
        return {
            str(k): (REDACTED if _is_forbidden_key(str(k)) else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def grant_audit_view(grant: Any) -> dict[str, Any]:
    """The ONLY grant fields that may ever be logged: session id + expiry."""
    return {
        "draft_session_id": getattr(grant, "draft_session_id", None),
        "expires_at_ms": getattr(grant, "expires_at_ms", None),
    }


class AuditLog:
    """Append-only JSONL audit log for exactly one team alias."""

    def __init__(self, data_dir: str | Path, team: str) -> None:
        self.team = _validate_alias(team)
        self.path = Path(data_dir) / self.team / AUDIT_FILENAME

    def log(self, event: str, **fields: Any) -> dict[str, Any]:
        """Append one scrubbed, UTC-timestamped event; returns the record."""
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "team": self.team,
            "event": str(event),
        }
        clean = scrub(fields)
        for key, value in clean.items():
            if key not in record:
                record[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return record

    def read_all(self) -> list[dict[str, Any]]:
        """All events, oldest first. Unparseable lines are skipped visibly."""
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"event": "audit.unparseable_line"})
        return events
