# DRAFT DAY — READ THIS FIRST

> Point the agent at this file tomorrow. It contains everything needed to get
> up to speed. Written 2026-08-28 night, the eve of the Synaps1 draft.

## Who / what / when

- **User:** Justin. Two authorized ESPN teams: **Synaps1** and **Synaps2**.
- **FORBIDDEN:** the team **RoughRydas** — never touch it, never act on it.
  Code enforces this (`PermissionError` at allowlist construction). See `TEAM_SAFETY.md`.
- **Synaps1 draft: TODAY (Sat Aug 29, 2026) 6:00 PM EDT.** League `305025860`,
  team id `2`, 10-team full-PPR snake, 90s/pick, slot randomized ~5:00 PM.
  Draft session id for grants: `305025860-2026-1788040800000`.
- **Synaps2 draft: Mon Sep 7, 6:00 PM EDT.** League `2144943745`, team id `4`,
  12-team PPR snake. Data root: `data/leagues/2144943745/`.

## Current state (verified on the eve)

- **ESPN server-side pre-rank is LIVE for Synaps1** — 250-player VORP-ordered
  list uploaded to Edit Draft Strategy and verified via API re-read (first 5:
  Gibbs, Bijan Robinson, Nacua, McCaffrey, Chase; DST/K at the tail). If
  nothing else happens, **ESPN autodrafts from our list. This is the floor.**
- Repo: `github.com/rydertetreault/fantasy-draft-assistant` (private), main @
  `748b9ba`+. **266/266 tests green.** Preflight PASS for both teams.
- Convergence verdicts (0.882 / 0.888 / 0.93 APPROVE) in `docs/verdicts/`.
- Standing authorization from user (recorded in project memory): autopick for
  the Synaps1 session above + the draft-strategy write (already done).

## Authorizations & mode policy

- **PRIMARY MODE (user confirmed on draft eve): AGENT-IN-THE-LOOP LIVE.** The
  user will be logged in, at the machine, browser open, session active. The
  agent watches the draft live via the read-only poller snapshots and DECIDES
  EVERY PICK itself — using the engine's recommendations as decision support
  plus live judgment the engine lacks: opponents' roster needs (who needs an
  RB before our next turn?), positional runs in progress, tier-cliff survival
  odds, and late news. Each pick: decide → submit via
  `scripts/espn_actuate.mjs --live` (grant required) → verify in next snapshot
  → log reasoning. Work the clock in-turn: sleep/poll between picks, act by
  ~45s remaining, halt to the user by ~30s if unconfirmed.
- Backup if the agent session is interrupted: `fantasy-draft run --mode
  autopick` (engine drafts alone). Floor: ESPN pre-rank autodraft.
- Dry-run gate at T-30 still mandatory before any --live submission.
- Grant: create at T-15, ephemeral file in /tmp (never commit), must name the
  exact session id above, short expiry (draft window only).
- Browser stays read-only EXCEPT: verified pick submission during the draft
  (autopick mode) and draft-list refresh via `scripts/espn_set_draftlist.mjs`.

## If the user shows up today (~5 PM) — run this sequence

```bash
cd "/Users/justintetreault/Fantasy Football Drafting/fantasy-draft-assistant"
caffeinate -dis &                        # keep machine awake through the draft

# 0. Browser: bash scripts/browser_start.sh  → user logs into ESPN if needed.
#    Confirm CDP: curl -s localhost:9222/json/version

# 1. Fresh data + board (T-60)
node scripts/fetch_espn_data.mjs
.venv/bin/fantasy-draft build-board --team synaps1

# 2. Refresh the ESPN pre-rank safety net with the fresh board
.venv/bin/python scripts/make_draftlist.py data/synaps1/board.csv /tmp/dl.json
node scripts/espn_set_draftlist.mjs /tmp/dl.json     # verifies after writing

# 3. Go/no-go gate
.venv/bin/fantasy-draft preflight --team synaps1     # must print PASS

# 4. T-30: dry-run gate against the REAL draft room (user opens the room tab)
node scripts/espn_actuate.mjs '{"playerId":4429795,"playerName":"Jahmyr Gibbs","leagueId":305025860,"teamId":2}' --grant-file /tmp/grant.json
#    (dry-run is the default — it locates the row, clicks nothing)

# 5. T-15: issue grant (autopick only if step 4 passed; else use --mode advisory)
#    Grant JSON: {"alias":"synaps1","league_id":305025860,"season":2026,
#      "draft_session_id":"305025860-2026-1788040800000",
#      "issued_at_ms":<now>,"expires_at_ms":<now+3h>}  → /tmp/grant.json

# 6. Run — AGENT-IN-THE-LOOP (primary): poller feeds snapshots, the AGENT
#    watches and decides each pick live, submitting via espn_actuate.mjs.
TEAM=synaps1 node scripts/espn_poll.mjs &            # read-only snapshot poller
#    Agent loop per turn: read newest data/synaps1/snapshots/*.json →
#    dashboard + engine rec → agent decision (opponent rosters, runs, tiers) →
#    node scripts/espn_actuate.mjs '<payload>' --grant-file /tmp/grant.json --live
#    → verify pick in next snapshot → audit. Engine-only backup if needed:
#    .venv/bin/fantasy-draft run --team synaps1 --mode autopick --grant-file /tmp/grant.json
#    dashboard anytime: .venv/bin/fantasy-draft dashboard --team synaps1
```

## Rules that must not be relaxed

- HALT means halt: no blind retry, one click max per turn; on HALT the runner
  drops to advisory permanently — that is correct behavior, not a bug.
- Stale state (>3s) blocks submission. Negative/skewed clock = stale.
- If anything is ambiguous about team identity, do nothing.
- The ESPN pre-rank list is already in place — a failed live run costs nothing.

## Key docs

- `docs/draft-day-runbook.md` — full procedure + machine-off addendum
- `docs/draft-strategy.md` — how the board thinks (VORP, tiers, PPR, portfolio)
- `docs/live-draft-operator.spec.md` / `.plan.md` — spec and plan
- `docs/verdicts/` — convergence verdicts + known non-blocking follow-ups
- Project memory: search `fantasy-draft-assistant` for the full trail

## After the Synaps1 draft

- Save the final roster + audit log; note what worked for the Synaps2 run Sep 7.
- Synaps2 gets the same treatment: fresh data → board → pre-rank upload
  (`--league 2144943745 --team 4`) → live operator if user is present.

## User strategy preference (draft eve)

User prefers securing two good RBs early ("RBs touch the ball more"). Agreed
policy — **RB tilt, not RB rule**: in rounds 1-4, when candidates are within
~6 projected points, break the tie toward RB. Never pass a clearly superior
elite WR to force RB2 (full PPR: WR5->WR15 drop is 55 pts this year vs RB's
34; but RB15->RB27 craters 67 pts, so aim to secure 2 startable RBs before
the round-5 RB cliff). If the room runs on RBs early, pivot to the abandoned
elite WRs and attack RB again rounds 3-5.
