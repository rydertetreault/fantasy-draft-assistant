# Fantasy Draft Assistant

Live ESPN fantasy-football draft operator: observes the draft board, ranks
available players from real ESPN projections/ADP, and recommends (or — with an
explicit session-bound grant — submits) picks under the 90-second clock.

**Safety first:** only the exact allowlisted teams **Synaps1** and **Synaps2**
can ever be acted on. The team *RoughRydas* is permanently forbidden — the code
refuses it at allowlist construction (see `TEAM_SAFETY.md`). Everything fails
closed: stale state, unknown identity, missing confirmation → halt.

## Setup on a new device

```bash
git clone <this-repo> && cd fantasy-draft-assistant

# Python side (decision engine, CLI, tests)
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q          # expect: 243 passed

# Node side (browser data fetch + actuator)
npm install                  # installs playwright (uses system Chrome, no download needed)

# Browser (log in to ESPN manually in the window that opens)
bash scripts/browser_start.sh
```

## Draft-day quickstart (per team)

```bash
# 1. Fetch fresh data (read-only; needs a logged-in fantasy.espn.com tab)
node scripts/fetch_espn_data.mjs                                    # Synaps1
LEAGUE_ID=2144943745 OUT_DIR=data/leagues/2144943745/raw \
  node scripts/fetch_espn_data.mjs                                  # Synaps2

# 2. Build the board
.venv/bin/fantasy-draft build-board --team synaps1
.venv/bin/fantasy-draft build-board --team synaps2 \
  --raw data/leagues/2144943745/raw/players.json --out data/leagues/2144943745

# 3. Go/no-go gate (must be PASS before drafting)
.venv/bin/fantasy-draft preflight --team synaps1
.venv/bin/fantasy-draft preflight --team synaps2 \
  --config config.synaps2.yaml --data data/leagues/2144943745

# 4. During the draft
.venv/bin/fantasy-draft dashboard --team synaps1     # mode/freshness/candidates
.venv/bin/fantasy-draft recommend --config config.synaps1.yaml --round 1 --pick 5
```

Full procedure, timings, mode selection (observe/advisory/autopick), grant
issuance, and manual-takeover rules: **`docs/draft-day-runbook.md`**.

## Key commands

| Command | Purpose |
|---|---|
| `fantasy-draft build-board` | Raw ESPN JSON → validated board (visible rejects) |
| `fantasy-draft preflight` | 9-check go/no-go gate incl. safety self-tests |
| `fantasy-draft replay X.jsonl --generate full` | Unattended full-draft simulation |
| `fantasy-draft dashboard` | Live status: mode, freshness, on-clock, top-3 + reasons |
| `fantasy-draft recommend / draft / undo / roster` | Manual advisory loop |
| `bash scripts/test_actuate.sh` | Browser actuator harness (6 refusal checks) |

## Teams

| Team | League | Team ID | Format | Draft |
|---|---|---|---|---|
| Synaps1 | 305025860 | 2 | 10-team PPR snake | Sat Aug 29 2026, 6 PM EDT |
| Synaps2 | 2144943745 | 4 | 12-team PPR snake | Mon Sep 7 2026, 6 PM EDT |

## Layout

- `src/fantasy_draft_assistant/` — safety guard, models, board, pipeline,
  observer, operator, actuator, replay, audit, dashboard, preflight
- `scripts/` — browser launcher, ESPN fetch (read-only), actuator (dry-run
  default), actuator harness
- `docs/` — spec, plan, strategy, runbook, convergence verdicts
- `data/` — local artifacts (gitignored): raw JSON, boards, state, audit logs
- `tests/` — 243 tests incl. unattended replay harness + browser fixture suite

## Never in git

ESPN passwords/cookies/tokens, grant files, `data/` artifacts, `.venv`,
`node_modules`. Secrets live only in your local browser session.
