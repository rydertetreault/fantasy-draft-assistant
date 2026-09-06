#!/usr/bin/env bash
# RoughRydas mock-day arming script (2026-09-06).
# 1) waits for ESPN login (fetch returns 200), 2) pulls fresh data for league
# 1851947, 3) builds data/roughrydas/board.csv, 4) runs preflight, 5) arms the
# ESPN mock driver (TEAMS=10) with the RoughRydas board + profile, polling
# until the user latches into a mock room.
set -uo pipefail
cd "$(dirname "$0")/.."
LOG=data/mock/arm.log; mkdir -p data/mock data/raw
log(){ echo "$(date +%T) $*" | tee -a "$LOG"; }

log "waiting for ESPN login (fetch 200)..."
until LEAGUE_ID=1851947 OUT_DIR=data/raw timeout 60 node scripts/fetch_espn_data.mjs 2>&1 | tee -a "$LOG" | grep -q "^players: "; do
  sleep 8
done
log "fetch OK"
.venv/bin/fantasy-draft build-board --team roughrydas --raw data/raw/players.json --out data 2>&1 | tail -3 | tee -a "$LOG"
.venv/bin/fantasy-draft preflight --team roughrydas 2>&1 | tee -a "$LOG"
log "arming mock driver (TEAMS=10, RoughRydas board+profile) — join a 10-team ESPN mock now"
BOARD_CSV="$PWD/data/roughrydas/board.csv" CONFIG_YAML="$PWD/config.roughrydas.yaml" TEAMS=10 \
  exec node scripts/espn_mock_driver.mjs
