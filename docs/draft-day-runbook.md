# Draft-Day Runbook — Live ESPN Draft Operator

Applies to **Synaps1** (league `305025860`, team `2`, season `2026`, 10-team
full-PPR snake, 90-second clock). Synaps2 stays **disabled** until its
identifiers are captured. **RoughRydas is never touched** (TEAM_SAFETY.md —
absolute; unknown identities are denied by default).

## Countdown checklist

### T-60 minutes — slot & plan
- [ ] Obtain the randomized draft slot from ESPN the moment it is announced.
- [ ] Confirm the pick order (`settings.draftSettings.pickOrder`) is captured
      in `data/raw/league_settings.json`.
- [ ] Sanity-check the slot-specific turn map:
      `fantasy-draft dashboard --team synaps1` must show the correct
      `next turn` overall for the announced slot.

### T-45 minutes — data refresh
- [ ] Refresh raw inputs (players + league settings) **read-only**.
- [ ] Rebuild the board: `fantasy-draft build-board --team synaps1`.
- [ ] Check `data/synaps1/rejects.csv` — unexpected rejects mean a schema
      drift; investigate before relying on the board.

### T-30 minutes — identity & insurance
- [ ] Run `fantasy-draft preflight --team synaps1` — every check must PASS
      (staleness warnings acceptable only if you just rebuilt).
- [ ] Note the printed **observed draft session id**
      (e.g. `305025860-2026-1788040800000`) — any autopick grant must carry
      exactly this `draft_session_id`.
- [ ] Log into ESPN in the dedicated browser profile; verify the page shows
      **Synaps1** and league `305025860` before anything else.
- [ ] Populate an ESPN in-site queue as outage insurance, and print/keep a
      paper fallback board (top ~40 by tier).

### T-15 minutes — rehearsal
- [ ] Full replay smoke:
      `fantasy-draft replay /tmp/full.jsonl --generate full --board data/synaps1/board.csv`
      → verdict must be **PASS** with max latency under 3000 ms.
- [ ] Read-only observation sync; dashboard must show `[FRESH]` state.
- [ ] If autopick is desired, issue the grant **now** (see below), not earlier.

## Mode selection

Restart always returns to **observe**. Autopick never survives a restart.

- **observe** (default): read-only; recommendations available on demand.
- **advisory**: recommendations surfaced continuously; a human clicks.
  `fantasy-draft run --team synaps1 --mode advisory`
- **autopick**: the operator submits verified picks. Requires an ephemeral,
  session-bound grant file (kept OUT of git, delete after the draft):

```bash
SESSION="305025860-2026-1788040800000"   # from preflight output
NOW=$(python3 -c 'import time; print(int(time.time()*1000))')
cat > /tmp/synaps1-grant.json <<EOF
{"alias": "synaps1", "league_id": 305025860, "season": 2026,
 "draft_session_id": "$SESSION",
 "issued_at_ms": $NOW, "expires_at_ms": $(($NOW + 4*3600*1000))}
EOF
fantasy-draft preflight --team synaps1 --grant-file /tmp/synaps1-grant.json
fantasy-draft run --team synaps1 --mode autopick --authorization-file /tmp/synaps1-grant.json
```

A grant that is expired, mis-aliased, or names any other session caps the
operator at advisory. There is no way to allowlist RoughRydas; do not try.

## Per-pick timing budget

- **Each opposing pick:** state reconciles within 3 s; watch the dashboard.
- **Before our turn:** at least three currently-available candidates queued.
- **90–45 s on our clock:** verify board, settle primary + fallbacks.
- **By 45 s:** submit (autopick) or click (advisory). Never wait for the
  final seconds on purpose.
- **By 30 s without confirmation: HALT.** Stop automation and take over
  manually in the ESPN tab. **Never blind-retry a click** — an unconfirmed
  submit may still have landed; re-clicking risks burning the pick.
- **After the pick:** confirm player/team/overall on the dashboard; the
  audit log (`data/synaps1/audit.jsonl`) records the verified action.

## Manual-takeover triggers (any one of these → human drives)

1. Dashboard shows `STALE` while we are on or near the clock.
2. A submit returns HALT (rejected click or missing/mismatched confirmation).
3. Identity ambiguity of any kind — wrong team name, wrong league id in the
   URL, unexpected login prompt. When in doubt, stop (RoughRydas risk).
4. Browser disconnect/crash, ESPN DOM overhaul, or repeated Blocked results.
5. Grant expiry mid-draft (deliberate: re-issue only if you still want autopick).

On takeover: draft from the ESPN queue / paper board. Automation stays in
observe mode; it may keep recommending, but it must not click again.

## Non-negotiable rules

- No blind retries, ever. One click per verified intent.
- Halt at 30 s without confirmation; the human finishes the pick.
- Exact allowlist match (alias, league, team, season) before any write.
- Grants are ephemeral, session-bound, and never committed to git.
- All tests and the full replay must be green **before** enabling autopick.
