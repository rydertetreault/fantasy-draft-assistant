"""Browser-fixture tests for scripts/espn_actuate.mjs (Checkpoint 3, Task 7).

Runs scripts/test_actuate.sh, which spawns a LOCAL headless Chrome on a
``file://`` fixture (tests/harness/fixtures/draft_room.html) and drives the
CDP actuator in dry-run only. No live ESPN access, ever. Skipped gracefully
when Chrome or node is missing.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

pytestmark = pytest.mark.browser


@pytest.mark.skipif(not CHROME.exists(), reason="local Chrome binary not found")
@pytest.mark.skipif(shutil.which("node") is None, reason="node not found")
def test_actuator_against_local_draft_room_fixture():
    proc = subprocess.run(
        ["bash", str(REPO / "scripts" / "test_actuate.sh")],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == 3:  # the script's own SKIP signal
        pytest.skip(output.strip())
    assert proc.returncode == 0, output
    assert "ALL PASS" in output
    # Dry-run must have located the exact fixture row...
    assert "PASS (exit 0): dry-run locates Josh Allen row" in output
    # ...and every refusal case must have fired with its distinct exit code.
    for refusal in (
        "file:// page refused without --allow-file-fixture",
        "unknown league id refused",
        "known league without open page refused",
        "mock mode refuses real league",
        "missing grant refused",
        "expired grant refused",
        "player not found refused",
    ):
        assert f": {refusal}" in output
