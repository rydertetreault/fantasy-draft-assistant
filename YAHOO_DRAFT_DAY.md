# YAHOO_DRAFT_DAY.md — READ THIS FIRST (dad's league)

> Point the agent at this file to resume Yahoo draft prep. Written late
> 2026-08-29 (~10:45 PM EDT) after the first Yahoo mock (bug-harvest run).
> Companion to `DRAFT_DAY.md` (ESPN) and `docs/postmortem-synaps1-2026.md`.

## Who / what / when

- **Team:** "All I Do Is Win" — Justin's DAD's team, owner-confirmed 2026-08-29.
  League **384341** "Old Backs Fresh Minds", team **6**, key `470.l.384341.t.6`.
- **Format:** 10-team, HALF-PPR (0.5/rec), H2H **snake** ("Live Standard"),
  60s/pick. Roster: QB/2RB/2WR/TE/W-R-T flex/K/DEF + 6 BN (+2 IR, not drafted).
- **DRAFT DATE: UNCERTAIN — CHECK FIRST.** Settings page said Sun **Sep 6,
  10:00 AM EDT**; Justin believes the league may move it (possibly to Sun Aug
  31 evening). **First task of any session: read
  `football.fantasysports.yahoo.com/f1/384341/settings` (read-only, via the
  user's logged-in session) and confirm.** Draft session id for future grants:
  `470.l.384341-2026-<start_ms>`.
- ESPN Synaps2 draft is Mon Sep 7 6 PM — the day after. Don't let prep collide.

## Current state (post mock #1, all pushed @ `489878e`)

- **Decision engine is cross-platform and validated**: `ctx_choose.py` +
  `src/fantasy_draft_assistant/context.py` (wait-loss, slot-adjusted VORP,
  hard caps QB2/TE2/K1/DEF1). **OWNER DIRECTIVE (mock #4, r2 Josh Allen
  graded B + RB,RB,RB start): follow the ESPN profile formula — the Yahoo
  profile now has HARD round floors (QB r5, DST r14, K r15) enforced at the
  ctx layer, starters-before-flex, and a K/DST ADP-ghost exemption. All
  profile-gated; ESPN path A/B-proven byte-identical.** Same brain that went
  16/16 on the ESPN validation mock.
- **Half-PPR board**: `data/yahoo/board.csv` (450 players) via
  `scripts/make_yahoo_board.py` (ESPN projections − 0.5×receptions; rebuild
  after fresh `fetch_espn_data.mjs` on draft day). Config: `config.yahoo.yaml`.
- **Yahoo mock driver**: `scripts/yahoo_mock_driver.mjs` — self-discovering
  DOM, MOCK-ONLY (hard-refuses the real room). 8 verified clicks @ ~527ms in
  mock #1 once row discovery worked.
- **Mock #1 verdict (user audit):** missed round 1, drafted 3 QBs. All root
  causes found and fixed (see table below). **NOT yet validated clean.**

## Bug harvest from mock #1 — fixed, offline-proven, needs live validation

| Failure | Fix (in `489878e`) |
|---|---|
| Missed pick 9 (round 1) | Row discovery + turn signal now known (see DOM notes) — armed pre-draft it fires from pick 1 |
| "Javonte Williams" click landed Jameson Williams (WR) | **Position-locked** row matching |
| "Jeremiyah Love" re-offer clicked Jordan Love → QB3 | Pos lock + roster **no-reoffer** (panel-synced roster added to drafted set) |
| "Bijan Robinson" at 135 clicked Brian Robinson Jr. (same team+pos+abbrev!) | **ADP-sanity ghost filter**: ADP + 30 < current overall ⇒ not a candidate, ever |
| DEF slot never filled | **DST bridge**: board "Lions D/ST" ↔ Yahoo "Detroit DEF" (city/nickname/team-token match) |
| Dart QB2 by forfeit | Funnel widened (base 100 / ctx 30) + **filter-click**: when the engine's best unseen candidate beats best visible by >5, click Yahoo's position filter tab, wait for rows to re-render, re-choose |
| Restart amnesia (wrong overall, lost roster) | Roster-panel `(N/15)` count is the turn index; picks persisted per-room; announcements freshness-gated (15s) |

**Still open:**
0. **K/DEF strategy per owner (post mock #5), all offline-verified:**
   bench depth r10-13 stays untouched; r14/15 fill K+DEF ordered by VALUE
   (elite kicker can precede a flat DST tier — K floor moved to 14);
   `reactive_floor_unlock` answers early position runs (3+ hist-evidenced
   takes) — "defense is based on when other teams start taking theirs but
   can be deferred". K/DST are also excluded from the ADP count-fill (their
   ESPN ADPs are fiction vs real rooms; Aubrey was being fill-"drafted" at
   r14). **None of this has live reps yet — next mock must show K+DEF
   actually landing.**
1. **Mock #5 (2026-08-30, real-users room, FAST ~28s/round): mechanics
   15/15 VERIFIED** (~530ms; slot from waiting-room label; in-place nav +
   fast turns handled). Strategy through r7 = the directives working:
   WR/RB/WR/RB/TE, QB r7. **FAILED the bar: ZERO K + ZERO DEF** — DST gain
   4.87 missed the 5.0 filter-click gate at r14 AND the fallback path never
   emitted `wanted`. Fixed (offline-replayed on the captured o134/o147
   states): endgame required-slot forcing (rounds left <= empty required
   slots ⇒ candidates restricted to them), fallback emits wanted+tokens,
   driver trusts the chooser's wanted. Picks-scrape captured the real panel
   format ("e. mcpherson\n(k · cin)") → parser handles it; Players-first
   state reset fixes delta-only diffs. **Scrape has zero full-draft live
   reps; filter-click STILL zero live reps.**
2. **OWNER GRADING NEEDED: QB2 (Bo Nix r8, ctx 0.71) + TE2 (Kelce r9, ctx
   0.06)** — in 10-team half-PPR the bench RB/WR pool is below replacement
   by r8, so capped-position backups outscore them. Caps held, but if
   backup QB/TE are dead roster spots, the fix is bench scoring
   (upside-weighted RB/WR bench) or QB2/TE2 floors — awaiting directive.
3. **Mock #4 (2026-08-30, instant-start room): mechanics 4/4 VERIFIED** —
   room hop + URL slot + mid-draft restart w/ persisted state + Players-tab
   remount guard all worked. **Strategy graded B by owner: Josh Allen r2
   (QBs never that high) and RB,RB,RB before any WR.** Fixes (all
   profile-gated, offline-replayed against the exact mock-4 turns): hard
   floors QB5/DST14/K15 at the ctx layer (ESPN's -30 base-funnel penalty
   never bound there), starters-before-flex bench-weighting, K/DST exempt
   from the ADP ghost filter (Aubrey adp 86.6 would be "ghost" at r14/15).
   Replays now go WR/WR at the o15/o26 turns; K/DST land r14/15 only.
   **Needs a full clean validation mock.**
2. Filter-click still has zero *correct* live reps. Watch it on TE/K/DEF turns.
3. **Opponent modeling now feeds on REAL picks (owner directive)**: driver
   scrapes the room's "Picks" panel off-turn (body-text diff → `hist.txt`,
   restores "Players"); chooser attributes true pick order to snake slots
   (abbrev+injury-tag matching, same-team twin dedup by ADP with
   visible-row rescue, newest-first autodetect) → per-team need, run
   detection, survival math on actuals. Profile-gated
   (`history_order_attribution`); ESPN legacy path 4/4 byte-identical.
   **Picks-tab scrape has ZERO live reps — validate the panel format,
   tab restore, and `picks-scrape: N lines` log next mock.**
3. Fallback once labeled an empty-TE-slot pick "bench 0.0" — believed to be a
   phantom-roster artifact of the collision bugs; confirm gone.
4. **Pre-rank floor: NOT IMPLEMENTED** (`yahoo_set_prerank.mjs` is a refusing
   skeleton). This is rung #1 — Synaps1 proved floors win drafts alone. Needs
   DOM recon of Yahoo's pre-rank editor before the real draft.
5. The mock driver is MOCK-ONLY by design. Real-draft actuation must go
   through `yahoo_actuate.mjs` gates (allowlist, grant with exact session id,
   dry-run gate at T-30) — wire it AFTER a clean validation mock.
6. Yahoo ADP proxy is ESPN ADP — fine for gap modeling, imperfect for their
   room's sort order.

## Yahoo draft-room DOM cheat sheet (hard-won, mock #1)

- Room URL: `football.fantasysports.yahoo.com/draftclient/f1/<mock_id>/<slot>`
  — **the trailing segment is OUR SLOT** (mock #2 `.../10171133/7`, mock #3
  `.../10171677/3`): primary slot source, critical for instant-start rooms
  with no waiting room. Mocks are namespaced under `/f1/384341/...`
  (`mock_waiting`, etc.). **REAL room = `/f1/384341/draft` OR
  `draftclient/f1/384341/<slot>`** (league id inside draftclient = real) —
  both forms refused by the mock driver.
- **Entering the room does NOT open a new browser tab (owner-confirmed):
  the current page target UNHOOKS (dies) and a new page target appears in
  place.** Held Page handles go silently stale. The driver re-scans all CDP
  targets every cycle and hops to any live draftclient — arm it BEFORE
  joining; rooms can fill and start instantly (mock #3 cost ~100s latched
  to a dead lobby handle; pick 3 saved with 11s left). Expect the real
  draft to load straight into the room.
- **Turn signal = `document.title`**: `"YOUR TURN, DRAFT NOW | ..."` on the
  clock; `"N picks until your turn | ..."` waiting; `"You are next | ..."`.
  **OWNER-CORRECTED (mock #2): mid-draft banner ordinals are the draft's
  CURRENT round/pick — NOT our pick number.** The countdown ("you're up in
  X picks") sits next to current-position text; parsing it as our overall
  caused the stuck-"overall 14" bookkeeping. Only the PRE-DRAFT waiting-room
  label ("YOUR TURN - 7TH PICK") names our first pick → slot inference is
  gated to pre-first-pick + off-turn; our overall comes ONLY from the roster
  panel count `(N/15)` + slot math. Slot persists in `our_picks.json`.
- **Atomic/hashed CSS** (`_ys_*`, `D(f)`, `Mstart(a)`) — no semantic classes.
  Derive player rows FROM the per-row `Draft` buttons (exact text match;
  "Drafted" is a different, dangerous near-match) → smallest ancestor with a
  position token.
- Rows render ONLY on our turn (buttons 0/0 off-turn, ~100 on turn), top-40
  by Yahoo rank — TE/K/DEF live behind position filter tabs ("Tight Ends",
  "Kickers", "Defen…"). Names abbreviated: `"J. Love Q RB Ari Bye 14 A-"`
  (note injury tag between name and pos).
- **Roster panel** `"YOUR TEAM (N/15) QB J. Allen QB Buf …"` = ground truth
  incl. autopicks; count `(N/15)` verifies clicks (count-increment, never
  name matching) and indexes our next turn.
- 30s clock in mocks (real league: 60s). **Mocks run with REAL USERS
  (owner-confirmed): pick timing varies wildly — no bot-burst assumptions,
  no freshness-window shortcuts.** Rooms/tabs can also die mid-draft
  (mock #2 tab closed at r2): driver now re-latches to a live
  `draftclient`/`mock_waiting` tab instead of error-spinning.

## Next session — run the validation mock

```bash
cd "/Users/justintetreault/Fantasy Football Drafting/fantasy-draft-assistant"
# 0. Browser: CDP on :9222; if /json/list shows 0 tabs, open ANY window first
#    (zero-window Chrome breaks connectOverCDP). User logs into Yahoo.
# 1. CHECK THE REAL DRAFT DATE (settings page, read-only). This gates everything.
# 2. Rebuild the board if data is stale (>12h):
node scripts/fetch_espn_data.mjs && .venv/bin/python scripts/make_yahoo_board.py
# 3. Arm (SLOT = whatever the lobby assigns; it self-corrects from ordinals):
SLOT=<slot> TEAMS=10 nohup node scripts/yahoo_mock_driver.mjs > data/yahoo/mock_driver_stdout.log 2>&1 &
# 4. USER joins a 10-team "Live Standard" mock (NEVER Salary Cap; user loads
#    all drafts themself). Driver latches automatically.
# 5. Watch: tail -f data/yahoo/mock_driver.log
```

**Validation bar (all must hold):** round 1 fires · every VERIFIED pick is the
intended player (spot-check panel vs log) · TE/K/DEF filled via filter-clicks
· ≤2 QB, ≤2 TE, exactly 1 K + 1 DEF · zero ghost candidates · no autopicks
while the driver is up. Then: implement the pre-rank floor + wire
`yahoo_actuate.mjs` for the real room, mirroring the ESPN gate sequence.

## Rules that must not be relaxed

- **TWO-PROFILE RULE (owner directive): every engine/strategy change must be
  per-profile (`config.synaps2.yaml` vs `config.yahoo.yaml` + profile-gated
  code flags). ESPN's validated profile stays frozen — prove byte-identical
  output via A/B after any shared-code edit.**

- The real room (`/f1/384341/draft`) is untouchable by mock tooling. Real
  actuation only via `yahoo_actuate.mjs` gates + owner-authorized grant.
- User loads all drafts; agent never navigates to/joins draft rooms.
- One submission max per turn; verify by roster count before anything else.
- Single-device rule during any real draft: the room lives ONLY in the
  dedicated Chrome. (ESPN postmortem lesson — phones steal room sessions.)
- RoughRydas remains forbidden everywhere, always.

## Key files

`scripts/yahoo_mock_driver.mjs` · `scripts/ctx_choose.py` ·
`scripts/make_yahoo_board.py` · `config.yahoo.yaml` · `data/yahoo/board.csv` ·
`scripts/yahoo_room_probe.mjs` (recon) · `scripts/yahoo_{actuate,set_prerank,
poll,fetch}.mjs` (real-room scaffolds, refuse-by-default) ·
`src/fantasy_draft_assistant/{context,yahoo_safety}.py` ·
project memory: search "yahoo" for the full trail.
