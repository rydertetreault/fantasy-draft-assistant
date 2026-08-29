# Yahoo Fantasy Sports API — Adapter Research

Researched 2026-08-28/29 (eve of ESPN Synaps1 draft) for a future Yahoo league
draft targeting **Sun 2026-08-30 6:00 PM EDT**. Research was **read-only**:
public docs fetched with `curl` (no login, no OAuth initiated, no credentials,
zero writes to any Yahoo service). Every claim below is tagged **VERIFIED**
(observed directly during this session) or **ASSUMED** (prior knowledge or
community consensus not confirmable from official docs today).

## Verification method

- `curl` of `https://developer.yahoo.com/fantasysports/guide/` — **VERIFIED**:
  it now redirects to `https://sports.yahoo.com/developer/`, a generic landing
  page. The detailed Fantasy Sports API guide is no longer served at its
  historic URL.
- `curl` of a 2024 Wayback Machine capture of the official guide
  (`web.archive.org/web/2024id_/https://developer.yahoo.com/fantasysports/guide/`,
  ~322 KB HTML) — **VERIFIED** as the source for resource/URI/write claims
  below (marked "VERIFIED (archived guide)"). Caveat: a 2024 snapshot of docs
  that Yahoo has since taken down may lag current behavior.
- `curl` of `https://developer.yahoo.com/oauth2/guide/` — **VERIFIED**: live,
  HTTP 200, documents the Authorization Code Grant flow.
- Unauthenticated `curl` of
  `https://fantasysports.yahooapis.com/fantasy/v2/game/nfl` — **VERIFIED**:
  returns **HTTP 401**, i.e. the API host is live and OAuth is mandatory for
  every request.

## 1. OAuth2 requirements

- **VERIFIED**: All Fantasy Sports API requests require OAuth (401 without a
  token; the archived guide's "OAuth" section says the API requires it).
- **VERIFIED**: Yahoo uses OAuth 2.0 **Authorization Code Grant** — register
  an app to get a client id/secret, send the user to an authorize URL, receive
  a code at the redirect URI, exchange it for access + refresh tokens, and use
  the refresh token to mint new access tokens (live OAuth2 guide).
- **ASSUMED**: Access tokens last ~1 hour; refresh tokens are long-lived. A
  3-hour draft window therefore needs at least two token refreshes.
- **ASSUMED**: Fantasy-specific scopes are `fspt-r` (read) and `fspt-w`
  (write), selected at app registration ("Fantasy Sports Read" vs
  "Read/Write"). Not present in the pages fetched today.
- **ASSUMED**: For a local tool, redirect URI `oob`/localhost flows work;
  Yahoo has historically been picky (https redirect required for non-oob).
- **Safety note**: this project will NOT initiate OAuth until the user
  explicitly authorizes it with a real Yahoo league. All skeletons refuse by
  default (empty allowlist, no grant).

## 2. Key formats and core resources

Base URL — **VERIFIED (archived guide)**: `https://fantasysports.yahooapis.com/fantasy/v2/`.
Responses default to XML; **ASSUMED**: `?format=json` returns JSON.

- **VERIFIED (archived guide)** key formats:
  - game key: `{game_code}` or `{game_id}` (e.g. `nfl` or `223`; game_codes
    are translated to game_ids).
  - league key: `{game_key}.l.{league_id}` (e.g. `223.l.431`; lower-case L).
  - team key: `{game_key}.l.{league_id}.t.{team_id}` (e.g. `223.l.431.t.1`).
  - player key: `{game_key}.p.{player_id}`.
- **ASSUMED**: the NFL game_key for the 2026 season is a specific integer that
  must be fetched at adapter-config time via `/game/nfl` (it changes yearly).

### League settings

- **VERIFIED (archived guide)**: `GET /league/{league_key}` returns metadata
  including `draft_status` (`predraft`/`postdraft`), `num_teams`, `edit_key`;
  `settings` include `draft_type` (e.g. `live`) and `scoring_type`.
- **ASSUMED**: `GET /league/{league_key}/settings` returns full roster slots,
  scoring modifiers (incl. PPR value), and draft time — the equivalent of
  ESPN `mSettings`.

### Players / projections

- **VERIFIED (archived guide)**: Player resource and Players collection exist
  with filters; **ASSUMED** specifics:
  `GET /league/{league_key}/players;start=0;count=25;sort=AR` (Yahoo actual
  rank), `;sort=OR` (overall rank), `;status=A` (available), pagination capped
  at 25/page. Sub-resources `stats`, `percent_owned`, `draft_analysis` (ADP,
  avg round, % drafted).
- **ASSUMED**: Yahoo exposes NO point projections via the public API — only
  ranks, ADP (`draft_analysis`), and historical stats. Projections must come
  from our own board (same VORP pipeline as ESPN).

### Draft results

- **ASSUMED**: `GET /league/{league_key}/draftresults` returns completed picks
  (pick, round, team_key, player_key). Widely used by community libraries
  (e.g. `yahoo_fantasy_api`), but NOT present in the archived guide capture
  fetched today, so it stays ASSUMED until probed with a real token.
- **ASSUMED — CRITICAL for polling**: `draftresults` updates during a live
  draft with some lag, and there is no documented low-latency draft feed
  (Yahoo's own draft client uses a private websocket/ExFM channel). The
  poller skeleton therefore mirrors ESPN's browser-context approach and its
  freshness gates; whether API polling is fast enough for a 90s clock is an
  OPEN QUESTION to resolve in a mock draft.

## 3. Pre-draft rankings upload ("pre-rank" — our autodraft floor)

- **VERIFIED (archived guide, by absence)**: the official guide documents NO
  write endpoint for pre-draft rankings. The complete documented write
  surface is listed in §4.
- **ASSUMED**: Yahoo pre-draft ranks are edited in the browser at the league's
  "Pre-Draft Ranks" page (drag-drop reorder + "import by player list"
  paste box). Yahoo autodrafts from this personal ranked list when a manager
  is absent — same floor semantics as ESPN's Edit Draft Strategy.
- **ASSUMED**: the browser page performs form/JSON POSTs to
  `football.fantasysports.yahoo.com` (site-internal, undocumented). The
  `yahoo_set_prerank.mjs` skeleton mirrors `espn_set_draftlist.mjs`
  (write-then-re-read verification) but every endpoint is a TODO(verify)
  requiring one-time DevTools capture in the user's own logged-in session,
  with explicit user authorization.

## 4. Live draft pick submission — API or browser-only?

- **VERIFIED (archived guide)**: the ONLY documented write operations in the
  official Fantasy Sports API are:
  - `PUT team/{team_key}/roster` — set lineup;
  - `POST league/{league_key}/transactions` — add/drop, propose trades;
  - `PUT transaction/{transaction_key}` — edit waiver, accept/reject/allow/
    disallow/vote-against trade;
  - `DELETE transaction/{transaction_key}` — cancel waiver/pending trade.
  **There is NO draft-pick write anywhere in the documented API.**
- **CONCLUSION (VERIFIED absence in docs + ASSUMED overall)**: **live draft
  pick submission is browser-only.** Yahoo's draft room is an app-like client
  speaking a private realtime protocol; no public REST endpoint drafts a
  player. Any Yahoo live actuation must click the "Draft" button in the
  user's own logged-in browser, exactly like `espn_actuate.mjs` — CDP attach,
  never navigate, locate row, one click max, verify via next snapshot.
- **ASSUMED**: Yahoo draft-room URLs look like
  `https://football.fantasysports.yahoo.com/draftclient/...` or contain
  `/f1/{league_id}/draft` — the exact URL shape must be captured read-only
  from a real (mock) draft room before `--live` is ever considered.

## 5. Consequences for the adapter

| ESPN piece | Yahoo mirror | Status |
| --- | --- | --- |
| `fetch_espn_data.mjs` (read-only data) | `scripts/yahoo_fetch.mjs` | skeleton; endpoints TODO(verify) |
| `espn_poll.mjs` (read-only snapshots) | `scripts/yahoo_poll.mjs` | skeleton; latency OPEN QUESTION |
| `espn_set_draftlist.mjs` (pre-rank floor) | `scripts/yahoo_set_prerank.mjs` | skeleton; browser-only, endpoints TODO(verify) |
| `espn_actuate.mjs` (verified click) | `scripts/yahoo_actuate.mjs` | skeleton; browser-only confirmed by docs absence |
| `safety.py` allowlist | `yahoo_safety.py` | implemented; allowlist EMPTY → everything refuses |
| `DRAFT_DAY.md` | `YAHOO_DRAFT_DAY.md` | runbook skeleton with placeholders |

## 6. Top open questions blocking live actuation

1. Real Yahoo league ID + team ID + season game_key — allowlist is EMPTY until
   the user supplies and confirms them (and confirms no RoughRydas analog).
2. Does `draftresults` update fast enough during a live draft for an
   agent-in-the-loop 90s clock? Measure in a Yahoo **mock draft** first.
3. Exact pre-rank write mechanism (site-internal endpoint or DOM automation)
   and its verification read-back.
4. Yahoo draft-room DOM: player-row selectors, draft-button label/state, and
   on-the-clock indicator — capture from a mock draft, read-only.
5. OAuth app registration + scope (`fspt-r` first; `fspt-w` only if any API
   write turns out to be needed at all) — requires explicit user action;
   agent will not initiate.

## Addendum — candidate identity observed on disk (UNCONFIRMED)

During this scaffolding session, a **concurrent** read-only recon (not run by
this session; `scripts/tmp_yahoo_recon*.mjs` + `data/yahoo/raw/*.html` in the
MAIN checkout, timestamped minutes before this note) captured the logged-in
account's Yahoo pages. Extracted **candidate** values — treated entirely as
**ASSUMED / UNCONFIRMED** and deliberately NOT added to any allowlist:

- League `384341` ("Old Backs Fresh Minds"), team id `6` ("All I Do Is Win").
- Settings page: Live Standard Draft, **Draft Time: Sun Sep 6 10:00am EDT**,
  1 minute/pick, max 10 teams. NOTE: this **conflicts** with the working
  target of Sun 2026-08-30 6:00 PM EDT — the user must reconcile.
- No "RoughRydas" string appears in the captured pages, but forbidden-team
  vigilance still applies until the user confirms team identity explicitly.

The allowlist stays EMPTY until the user confirms these ids in a reviewed
edit (yahoo_safety.py + TEAM_SAFETY-style record + YAHOO_DRAFT_DAY.md).
