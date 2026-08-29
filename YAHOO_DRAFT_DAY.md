# YAHOO DRAFT DAY — RUNBOOK SKELETON (NOT YET ACTIVE)

> Mirrors `DRAFT_DAY.md` (the ESPN briefing). **This is a SCAFFOLD**: every
> `⟨PLACEHOLDER⟩` must be filled with user-confirmed values, and the scope
> ladder below gates what is allowed. Until then, the Yahoo allowlist is
> EMPTY and every actuation path refuses by design.
> Written 2026-08-29 alongside the Yahoo adapter scaffold.

## Who / what / when

- **User:** Justin. Authorized Yahoo teams: **NONE YET** — allowlist is empty.
- **FORBIDDEN:** the team **RoughRydas** (and any Yahoo analog) — never touch
  it. Code enforces this (`PermissionError` in `yahoo_safety.YahooAllowlist`,
  hard refusals in every `scripts/yahoo_*.mjs`). See `TEAM_SAFETY.md`.
- **Yahoo draft: Sun Sep 6, 2026, 10:00 AM EDT** — per the league Scoring &
  Settings page (read-only recon 2026-08-29). NOTE: user initially relayed
  "Aug 30, 6 PM"; the settings page overrides. Dad's verbal confirm pending.
  - League: `384341` **"Old Backs Fresh Minds"** | Team: `6` **"All I Do Is
    Win"** — CANDIDATE (matches name user supplied; only team on account).
    Allowlist stays EMPTY until dad confirms verbatim; populating it remains
    a reviewed, user-approved edit.
  - Game key (2026 NFL, fetch via `/game/nfl`): `⟨GAME_KEY⟩`  → league key
    `⟨GAME_KEY⟩.l.⟨YAHOO_LEAGUE_ID⟩`, team key `…​.t.⟨YAHOO_TEAM_ID⟩`
  - Settings (recon-verified): 10-team **HALF-PPR (0.5/rec)** H2H snake
    ("Live Standard Draft"), **60s/pick** — faster than ESPN's 90s; retune
    act-by/halt thresholds. Roster QB/2WR/2RB/TE/W-R-T/K/DEF, 6 BN, 2 IR;
    pass TD 4, INT −1, fumble −2. Raw HTML: main `data/yahoo/raw/`.
  - Draft slot: `⟨SLOT⟩` (randomized at `⟨TIME⟩`?)
  - Draft session id for grants: `⟨GAME_KEY⟩.l.⟨LEAGUE⟩-2026-⟨DRAFT_EPOCH_MS⟩`
    (convention mirroring ESPN's `league-season-epoch`; confirm derivation)
  - Data root: `data/yahoo/384341/`

## Current state (scaffold reality check)

- Yahoo adapter is a SKELETON: `scripts/yahoo_fetch.mjs`, `yahoo_poll.mjs`,
  `yahoo_actuate.mjs`, `yahoo_set_prerank.mjs`, `yahoo_safety.py`. All
  actuation paths refuse (empty allowlist + missing grant + TODO(verify)
  endpoints). Research + open questions: `docs/yahoo-adapter.research.md`.
- **Live pick submission is browser-only on Yahoo** (no public API draft
  write — VERIFIED absence in official docs). Same CDP click discipline as
  ESPN applies.
- **Pre-rank upload is browser-only** (ASSUMED) — mechanism unverified;
  `yahoo_set_prerank.mjs` exits NOT-IMPLEMENTED even when allowlisted.
- ESPN path is untouched and remains the live-draft system of record.

## SCOPE LADDER — each rung requires the one below it to be proven

1. **Pre-rank floor (first and mandatory).** Upload our VORP-ordered list to
   Yahoo Pre-Draft Ranks and VERIFY by re-read. If nothing else happens,
   Yahoo autodrafts from our list. Blockers: real ids + verified pre-rank
   write mechanism. *No live anything until this floor exists.*
2. **Advisory live.** Read-only: `yahoo_poll.mjs` snapshots + dashboard +
   engine recommendations spoken to the user, who clicks in the browser
   himself. Blockers: snapshot latency proven acceptable in a MOCK draft.
3. **Full agent-in-the-loop** (agent decides and submits via
   `yahoo_actuate.mjs --live`) **ONLY IF the T-30 dry-run gate passes** in
   the real draft room (locate row + enabled button, click nothing), AND
   allowlist entry + session-bound grant exist, AND rungs 1–2 are green.

## Authorizations & mode policy (mirrors ESPN)

- Grant: ephemeral file in /tmp (never commit), must name the exact draft
  session id above, short expiry (draft window only), created at T-15.
- Dry-run is the DEFAULT for every actuator; `--live` requires the grant AND
  the (currently empty) allowlist entry.
- Browser stays read-only EXCEPT: verified pick submission during the draft
  and the pre-rank upload — both only after explicit user authorization.
- OAuth (if ever needed for API reads): user registers the app and completes
  the flow himself; the agent never initiates login. Scope `fspt-r` only
  unless proven otherwise.

## If the user shows up (~9 AM Sun Sep 6) — target sequence

```bash
cd "⟨REPO_ROOT⟩"
caffeinate -dis &                        # keep machine awake through the draft

# 0. Browser: bash scripts/browser_start.sh → user logs into Yahoo if needed.
#    Confirm CDP: curl -s localhost:9222/json/version

# 1. Fresh data + board (T-60)
YAHOO_LEAGUE_KEY=⟨GAME_KEY⟩.l.⟨LEAGUE⟩ OUT_DIR=data/yahoo/⟨LEAGUE⟩/raw node scripts/yahoo_fetch.mjs
.venv/bin/fantasy-draft build-board --team ⟨YAHOO_ALIAS⟩          # ⟨config TBD⟩

# 2. Refresh the Yahoo pre-rank safety net (RUNG 1 — currently NOT-IMPLEMENTED)
.venv/bin/python scripts/make_draftlist.py data/⟨YAHOO_ALIAS⟩/board.csv /tmp/yahoo_dl.json  # ⟨needs yahoo_player_id column⟩
node scripts/yahoo_set_prerank.mjs /tmp/yahoo_dl.json --league ⟨LEAGUE⟩ --team ⟨TEAM⟩   # verifies after writing

# 3. Go/no-go gate  ⟨preflight --team ⟨YAHOO_ALIAS⟩ once a config exists⟩

# 4. T-30: dry-run gate against the REAL draft room (user opens the room tab)
node scripts/yahoo_actuate.mjs '{"playerId":⟨ID⟩,"playerName":"⟨NAME⟩","leagueId":⟨LEAGUE⟩,"teamId":⟨TEAM⟩}' --grant-file /tmp/yahoo_grant.json
#    (dry-run is the default — it locates the row, clicks nothing)

# 5. T-15: issue grant (rung 3 only if step 4 passed; else stay on rung 2)
#    Grant JSON: {"alias":"⟨YAHOO_ALIAS⟩","league_id":⟨LEAGUE⟩,"season":2026,
#      "draft_session_id":"⟨SESSION_ID⟩",
#      "issued_at_ms":<now>,"expires_at_ms":<now+3h>}  → /tmp/yahoo_grant.json

# 6. Run at the highest rung earned:
TEAM=⟨YAHOO_ALIAS⟩ YAHOO_LEAGUE_KEY=⟨GAME_KEY⟩.l.⟨LEAGUE⟩ node scripts/yahoo_poll.mjs &   # read-only
#    Rung 2: agent reads snapshots + engine rec, advises; USER clicks.
#    Rung 3: agent decides → yahoo_actuate.mjs '<payload>' --grant-file /tmp/yahoo_grant.json --live
#            → verify pick in next snapshot → audit. One click max per turn.
```

## Timeline (target: Sun 2026-09-06, 10:00 AM EDT draft — a MORNING draft)

| When | What |
| --- | --- |
| ASAP | User supplies league/team ids → allowlist entry + TEAM_SAFETY update |
| T-1 day | Yahoo MOCK draft: capture draft-room URL/DOM read-only; measure `draftresults` latency |
| T-1 day | Verify pre-rank write mechanism; implement + verify rung 1 |
| T-60 min | Fresh data, board, pre-rank refresh, preflight |
| T-30 min | Dry-run gate in the real draft room (rung 3 go/no-go) |
| T-15 min | Grant issued (session-bound, ≤3h expiry) |
| 10:00 AM | Draft at the highest rung earned |
| After | Save roster + audit; retro vs ESPN drafts |

Heads-up: **Synaps2 (ESPN) drafts the next evening** — Mon Sep 7, 6:00 PM EDT.
Half-PPR strategy note: 0.5/rec shifts value toward RBs vs Synaps1's full
PPR — dad's "RBs touch the ball more" tilt is MORE correct here. Board must
be built from this league's scoring; the Synaps1 board does not transfer.

## Rules that must not be relaxed (identical to ESPN)

- HALT means halt: no blind retry, one click max per turn; on HALT drop to
  advisory permanently — that is correct behavior, not a bug.
- Stale state (>3s) blocks submission. Negative/skewed clock = stale.
- If anything is ambiguous about team identity, do nothing.
- The pre-rank floor must exist BEFORE any live rung — a failed live run must
  cost nothing.
- Empty allowlist = total refusal. Populating it is a reviewed, user-approved
  edit, never an inline hack.

## Key docs

- `docs/yahoo-adapter.research.md` — verified/assumed API findings + open questions
- `DRAFT_DAY.md`, `docs/draft-day-runbook.md` — the ESPN originals this mirrors
- `TEAM_SAFETY.md` — forbidden-team policy (extend with Yahoo ids when known)
- `src/fantasy_draft_assistant/yahoo_safety.py`, `tests/test_yahoo_safety.py`
