# YAHOO_DRAFT_DAY.md — READ THIS FIRST (dad's league)

> Point the agent at this file to resume Yahoo draft prep. Written late
> 2026-08-29 (~10:45 PM EDT) after the first Yahoo mock (bug-harvest run).
> Companion to `DRAFT_DAY.md` (ESPN) and `docs/postmortem-synaps1-2026.md`.

## Who / what / when

- **Team:** "All I Do Is Win" — Justin's DAD's team, owner-confirmed 2026-08-29.
  League **384341** "Old Backs Fresh Minds", team **6**, key `470.l.384341.t.6`.
- **Format:** 10-team, HALF-PPR (0.5/rec), H2H **snake** ("Live Standard"),
  **45s/pick** (settings-confirmed 2026-08-30; NOT 60s as first assumed).
  Roster: QB/2RB/2WR/TE/W-R-T flex/K/DEF + 6 BN (+2 IR, not drafted).
- **DRAFT DATE CONFIRMED: Sun Aug 30, 2026, 7:00 PM EDT** — read from the
  settings page via the user's logged-in session at 3:46 PM the same day.
  The league moved it up a week from Sep 6. Draft session id for grants:
  `470.l.384341-2026-<start_ms>`.
- **QB2/TE2 OWNER VERDICT (2026-08-30): fine as-is.** Bo Nix r8 / Kelce r9
  approved; no bench-scoring or floor changes needed. Item CLOSED.
- ESPN Synaps2 draft is Mon Sep 7 6 PM — the day after. Don't let prep collide.

## Current state (post mock #8 — VALIDATED CLEAN, live driver armed @ `eca7f0b`)

- **MOCK #8 (2026-08-30 5:32 PM) PASSED THE FULL BAR**: 15/15 driver picks
  VERIFIED (~530ms), round 1 fired, K (Dicker) + DEF (Broncos) landed via
  the ENDGAME GATE + select-dropdown list switch, 2QB/2TE/1K/1DEF, zero
  ghosts, zero autopicks. This is the clean validation mock.
- **`scripts/yahoo_live_driver.mjs` (NEW, tested)**: the byte-identical
  mock-8 loop, REAL room only (refuses every mock/foreign tab), dry-run by
  default; `--live` requires `--grant-file` (alias allowlist `allidoiswin`,
  RoughRydas forbidden, league 384341, session id
  `470.l.384341-2026-<start_ms>`, validity window, expiry re-checked before
  EVERY click). All 6 refusal paths + both arming modes tested offline.
  Currently RUNNING in dry-run, waiting to latch the real room tonight.
- **Decision engine cross-platform and validated**: `ctx_choose.py` +
  `context.py` (wait-loss, slot-adjusted VORP, hard caps QB2/TE2/K1/DEF1,
  hard floors QB r5 / DST r14 / K r14-15, starters-before-flex, K/DST
  ADP-ghost exemption, endgame required-slot forcing + `required_now`
  emission). All profile-gated; ESPN path A/B byte-identical (6/6 + 4/4
  scenarios re-proven today). 332 tests pass.
- **Half-PPR board**: `data/yahoo/board.csv` (452 players) rebuilt fresh
  3:46 PM draft day via `fetch_espn_data.mjs` + `make_yahoo_board.py`.
- **Mock driver** `yahoo_mock_driver.mjs` stays MOCK-ONLY (owner rule).

## The endgame-gate saga (mocks #5-#8) — how K/DEF got guaranteed

| Mock | Result | Lesson |
|---|---|---|
| #5 | 15/15 mechanics, ZERO K/DEF | DST gain 4.87 lost to the 5.0 filter-click gate; fallback never emitted `wanted` |
| #6 | 15/15 mechanics, ZERO K/DEF | Filter-tab click silently missed; "rows changed" check lied (any opponent pick satisfied it); fallback clicked RB/WR over wanted DST |
| #7 | 13 picks, r14 lost to autopick | ENDGAME GATE correctly REFUSED the RB, but all switch strategies failed: **Yahoo's position filter is a `<select>` dropdown, not tabs** — and the search-box fallback ("broncos") poisoned the list to 0 draft buttons. Bought the DOM truth via live recon |
| #8 | **15/15 + K + DEF ✅** | Select-dropdown switch (native setter + change event) verified live: 31 DST rows / 40 K rows, gate recovered both turns in ~1.5s |

**Hard guarantee now in the driver:** while rounds left <= empty required
slots (`required_now` from the chooser, round-number based), clicking any
other position is REFUSED; list-switch strategies retry until the clock
forces an emergency valve at <=8s (beats autopick). Post-#8 fix, offline
replay-proven: forcing keys off `round_no`, not the phantom-inflated panel
roster, so K/DEF land r14/15 per owner directive (bench r10-13 untouched,
K/DST ordered by value).

## Bug harvest from mock #1 — all live-validated by mock #8

| Failure | Fix |
|---|---|
| Missed pick 9 (round 1) | Row discovery + turn signal — fires from pick 1 (live-proven #5-#8) |
| "Javonte Williams" click landed Jameson Williams (WR) | **Position-locked** row matching |
| "Jeremiyah Love" re-offer clicked Jordan Love → QB3 | Pos lock + roster **no-reoffer** |
| "Bijan Robinson" at 135 clicked Brian Robinson Jr. | **ADP-sanity ghost filter** (K/DST exempt) |
| DEF slot never filled | **DST bridge** + endgame gate + select-dropdown switch (live-proven #8) |
| Dart QB2 by forfeit | Funnel widened + `wanted`-driven list switch |
| Restart amnesia | Roster-panel `(N/15)` = turn index; picks persisted per-room |

**Still open (accepted for tonight):**
1. **Phantom panel-roster entries** (parser counts 12 at 10 real picks —
   trailing RB/WR ghosts). Endgame forcing is now immune (round_no based);
   residual effect is mild scoring bias in bench weighting. Fix parser
   post-draft.
2. **Pre-rank floor NOT IMPLEMENTED** (`yahoo_set_prerank.mjs` refusing
   skeleton). CUT for tonight — no time for DOM recon; the validated driver
   is the plan A, manual takeover is plan B.
3. Yahoo ADP proxy is ESPN ADP — fine for gap modeling, imperfect for their
   room's sort order.
4. QB2/TE2 verdict (owner, 2026-08-30): fine as-is. CLOSED.
5. Picks-scrape, room hop, URL slot, mid-draft restart: all have live reps
   across #5-#8. CLOSED.

## Yahoo draft-room DOM cheat sheet (hard-won, mocks #1-#8)

- **POSITION FILTER IS A `<select name="position-filter">` DROPDOWN — NOT
  TABS** (mock #7 live recon). Option values: `pos_type=All`, `pos=QB/WR/
  RB/TE/K/DEF` (+`pos_type=O`, `pos=W/R/T`); DEF's text label is "Team
  Defenses". React select: use the NATIVE value setter + bubbling `change`
  event; `.click()` on option text silently no-ops (cost mocks #4-#7 their
  K/DEF turns).
- **Search box** (`input placeholder="Search for a player"`) filters by
  NAME and POISONS the list for everything else (0 draft buttons on our
  clock = lost turn, mock #7). Clear via native setter + `input` event
  before any list switch and after any pick. Last-resort only.
- **DEF rows are nickname form: "Broncos DEF", "Cowboys DEF"** (not
  "Denver DEF") — the DST bridge (city/nick/team-token) matches either.
- **A CLOSED page still reports its last draftclient URL** — `page.url()`
  doesn't throw, so a hop check keyed on URL alone spins on the dead
  handle forever. `page.isClosed()` must force the target re-scan
  (found pre-mock #8; the driver missed a fresh waiting room for 10 min).
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

## TONIGHT (Sun Aug 30) — real-draft runbook, draft 7:00 PM EDT

Validated in mock #8 (15/15 driver picks, K+DEF landed via endgame gate +
select-dropdown switch): `scripts/yahoo_live_driver.mjs` = the same loop,
real-room-only, gated (dry-run default; --live needs a valid grant).

```bash
cd "/Users/justintetreault/Fantasy Football Drafting/fantasy-draft-assistant"
# T-30 (6:30): USER opens the real room (football.fantasysports.yahoo.com
#   /f1/384341/draft) in the dedicated Chrome. DRY-RUN gate:
node scripts/yahoo_live_driver.mjs            # logs would-be clicks only
#   PASS = latches room, reads state, names sane choices. Then Ctrl-C.
# T-15 (6:45): issue grant (owner authorizes) -> /tmp/yahoo_grant.json:
#   {"alias":"allidoiswin","league_id":384341,
#    "draft_session_id":"470.l.384341-2026-1788130800000",
#    "issued_at_ms":<now>,"expires_at_ms":<now+4h>}
# T-10: arm live:
nohup node scripts/yahoo_live_driver.mjs --live --grant-file /tmp/yahoo_grant.json \
  > data/yahoo/live_driver_stdout.log 2>&1 &
tail -f data/yahoo/live_driver.log
# Rules: single-device (room ONLY in dedicated Chrome), one submission max
# per turn (built in), UNVERIFIED after click => driver holds, human takes over.
```

## Next session — run the validation mock (SUPERSEDED by mock #8 — kept for reference)

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
while the driver is up. **MET BY MOCK #8 (2026-08-30).** Pre-rank floor was
cut for tonight; `yahoo_live_driver.mjs` (gated, above) replaced the
per-click `yahoo_actuate.mjs` wiring as the real-room path.

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

`scripts/yahoo_live_driver.mjs` (REAL room, gated — tonight's driver) ·
`scripts/yahoo_mock_driver.mjs` · `scripts/ctx_choose.py` ·
`scripts/make_yahoo_board.py` · `config.yahoo.yaml` · `data/yahoo/board.csv` ·
`data/yahoo/live_driver.log` (tonight's log) ·
`scripts/yahoo_room_probe.mjs` (recon) · `scripts/yahoo_{actuate,set_prerank,
poll,fetch}.mjs` (real-room scaffolds, refuse-by-default) ·
`src/fantasy_draft_assistant/{context,yahoo_safety}.py` ·
project memory: search "yahoo" for the full trail.
