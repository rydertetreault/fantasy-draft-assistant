#!/usr/bin/env bash
# Launch Chrome with remote debugging for the draft assistant (self-contained,
# no external plugins needed). Log in to ESPN manually in the window it opens.
set -euo pipefail
PORT="${CDP_PORT:-9222}"
DATA_DIR="${BROWSER_DATA_DIR:-$HOME/.cache/fantasy-draft-browser}"
mkdir -p "$DATA_DIR"

if [[ "$(uname)" == "Darwin" ]]; then
  BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  BIN="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium || true)"
fi
[[ -x "$BIN" ]] || { echo "Chrome/Chromium not found — install Google Chrome"; exit 1; }

# Already running?
if curl -s "http://localhost:${PORT}/json/version" >/dev/null 2>&1; then
  echo "Browser already running on :${PORT}"
  exit 0
fi

"$BIN" --remote-debugging-port="$PORT" --user-data-dir="$DATA_DIR" \
  --no-first-run --no-default-browser-check "https://fantasy.espn.com/football/" \
  >/dev/null 2>&1 &
echo "Chrome starting on :${PORT} (profile: $DATA_DIR). Log in to ESPN in the window."
