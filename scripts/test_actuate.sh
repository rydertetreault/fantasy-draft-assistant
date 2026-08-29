#!/usr/bin/env bash
# Node test runner for scripts/espn_actuate.mjs against the LOCAL browser
# fixture (Checkpoint 3, Task 7). No live ESPN access: it spawns a headless
# Chrome on a file:// fixture and checks that the dry-run actuator locates
# the right row and refuses wrong-league / missing-grant / expired-grant /
# player-not-found cases. Never passes --live.
set -u

CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
PORT="${CDP_PORT:-9333}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="$ROOT/tests/harness/fixtures/draft_room.html"
LEAGUE=305025860

if [ ! -x "$CHROME_BIN" ]; then
  echo "SKIP: Chrome binary not found at $CHROME_BIN"
  exit 3
fi
if ! command -v node >/dev/null 2>&1; then
  echo "SKIP: node not found"
  exit 3
fi

PROFILE="$(mktemp -d)"
WORK="$(mktemp -d)"
CHROME_PID=""
cleanup() {
  [ -n "$CHROME_PID" ] && kill "$CHROME_PID" 2>/dev/null
  rm -rf "$PROFILE" "$WORK"
}
trap cleanup EXIT

# League id baked into the URL query so the league-id-in-URL check is real.
URL="file://$FIXTURE?leagueId=$LEAGUE"
"$CHROME_BIN" --headless=new --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" --no-first-run --disable-gpu "$URL" \
  >/dev/null 2>&1 &
CHROME_PID=$!

for _ in $(seq 1 75); do
  if curl -fsS "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
if ! curl -fsS "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then
  echo "FAIL: headless Chrome CDP endpoint never came up on port $PORT"
  exit 1
fi

export BROWSER_CDP_URL="http://127.0.0.1:$PORT"

NOW="$(node -e 'console.log(Date.now())')"
GRANT="$WORK/grant.json"
GRANT_EXPIRED="$WORK/grant_expired.json"
GRANT_WRONG_LEAGUE="$WORK/grant_wrong_league.json"
cat > "$GRANT" <<EOF
{"alias":"synaps1","league_id":$LEAGUE,"season":2026,"draft_session_id":"$LEAGUE-2026-fixture","issued_at_ms":$((NOW-60000)),"expires_at_ms":$((NOW+3600000))}
EOF
cat > "$GRANT_EXPIRED" <<EOF
{"alias":"synaps1","league_id":$LEAGUE,"season":2026,"draft_session_id":"$LEAGUE-2026-fixture","issued_at_ms":$((NOW-7200000)),"expires_at_ms":$((NOW-3600000))}
EOF
cat > "$GRANT_WRONG_LEAGUE" <<EOF
{"alias":"synaps1","league_id":999999,"season":2026,"draft_session_id":"999999-2026-fixture","issued_at_ms":$((NOW-60000)),"expires_at_ms":$((NOW+3600000))}
EOF
GRANT_SYNAPS2_NOPAGE="$WORK/grant_synaps2_nopage.json"
cat > "$GRANT_SYNAPS2_NOPAGE" <<EOF
{"alias":"synaps2","league_id":2144943745,"season":2026,"draft_session_id":"2144943745-2026-fixture","issued_at_ms":$((NOW-60000)),"expires_at_ms":$((NOW+3600000))}
EOF

FAILURES=0
LAST_OUT=""

check() {
  local desc="$1" want="$2"
  shift 2
  LAST_OUT="$(node "$ROOT/scripts/espn_actuate.mjs" "$@" 2>&1)"
  local code=$?
  if [ "$code" -eq "$want" ]; then
    echo "PASS (exit $code): $desc"
  else
    echo "FAIL: $desc — wanted exit $want, got $code"
    echo "$LAST_OUT" | sed 's/^/    /'
    FAILURES=$((FAILURES + 1))
  fi
}

TARGET='{"playerId":3918298,"playerName":"Josh Allen","leagueId":305025860,"teamId":2}'

# 1. Dry-run locates the right row + draft button on the fixture.
check "dry-run locates Josh Allen row" 0 "$TARGET" --grant-file "$GRANT" --allow-file-fixture
if ! echo "$LAST_OUT" | grep -q "target: Josh Allen (3918298)"; then
  echo "FAIL: dry-run output did not identify the Josh Allen row"; FAILURES=$((FAILURES + 1))
fi
if ! echo "$LAST_OUT" | grep -q "DRY-RUN: no click performed"; then
  echo "FAIL: dry-run output missing the no-click confirmation"; FAILURES=$((FAILURES + 1))
fi

# 2. Without --allow-file-fixture the file:// page must be refused
#    (proves the https/host check is real and the flag relaxes ONLY it).
check "file:// page refused without --allow-file-fixture" 5 "$TARGET" --grant-file "$GRANT"

# 3. Unknown league id: refused immediately (not a known real league; mock
#    rooms must use --mock). Tightened 2026-08-29 post-Synaps1.
check "unknown league id refused" 2 \
  '{"playerId":3918298,"playerName":"Josh Allen","leagueId":999999,"teamId":2}' \
  --grant-file "$GRANT_WRONG_LEAGUE" --allow-file-fixture

# 3b. Known real league with no open page: refused at page-location stage.
check "known league without open page refused" 5 \
  '{"playerId":3918298,"playerName":"Josh Allen","leagueId":2144943745,"teamId":4}' \
  --grant-file "$GRANT_SYNAPS2_NOPAGE" --allow-file-fixture

# 3c. Mock mode can never target a real league.
check "mock mode refuses real league" 2 \
  '{"playerId":3918298,"playerName":"Josh Allen","leagueId":305025860,"teamId":2}' \
  --grant-file "$GRANT" --mock

# 4. Missing grant file argument.
check "missing grant refused" 2 "$TARGET" --allow-file-fixture

# 5. Expired grant.
check "expired grant refused" 3 "$TARGET" --grant-file "$GRANT_EXPIRED" --allow-file-fixture

# 6. Player not on the board.
check "player not found refused" 6 \
  '{"playerId":424242,"playerName":"Nobody Nowhere","leagueId":305025860,"teamId":2}' \
  --grant-file "$GRANT" --allow-file-fixture

if [ "$FAILURES" -eq 0 ]; then
  echo "ALL PASS"
  exit 0
fi
echo "$FAILURES check(s) failed"
exit 1
