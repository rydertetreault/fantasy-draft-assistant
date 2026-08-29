# Postmortem: Synaps1 2026 draft — agent went blind, user drafted manually

**Date:** 2026-08-29 · **Outcome:** Round 1 autodrafted from our verified
pre-rank (Nacua @ 3). Justin took over manually from his phone for rounds
2–16. Final roster is good; the agent contributed only the round-1 floor.

## What the agent believed vs what happened

| Agent's view | Reality |
|---|---|
| Snapshots fresh (≤2s file age), 0 picks made through ~18:19 | Draft live; picks landing every ~5–20s; Justin drafting from phone |
| All 150 picks arrived in one ≤280s window ⇒ "instant autodraft" | REST endpoint flushed cached results at/near draft end |
| 90s/pick clock (from settings) | Real clock ~20s max |
| Desktop draft room usable for actuation | Room frozen at "RND 1 OF 16 --:--", empty pick history — session had moved to the phone |

## Three independent holes

1. **Blind data.** `lm-api-reads … mDraftDetail` serves cached/lagged data
   during live drafts. The real-time path is the draft room's websocket (what
   the phone app renders). Our freshness guard measured *snapshot file age*,
   never *data recency at the source* — files were "fresh" all draft while the
   payload was stale.
2. **Dead actuator.** ESPN gives the live room session to the most recent
   active device. When the phone app opened the draft room, the desktop Chrome
   room froze at round 1. No live DOM feed, no DRAFT buttons. (Agent advice
   that phone viewing "from the Board tab" was safe: **wrong** — viewing from
   the app's draft room takes the session.)
3. **Wrong clock.** Settings said 90s/pick; the live draft ran ~20s. The whole
   "decide by 45s remaining" cadence was calibrated to a clock that didn't
   exist. Detection latency was fine (~3s: poller 2s + watcher 1s); the 280s
   watch chunks were NOT the cause — sampling was per-second inside them.

## Fixes required before the next drafts (Yahoo Sun Sep 6, Synaps2 Mon Sep 7)

- [ ] **Primary feed = the draft room itself** via CDP: parse pick history,
      on-the-clock banner, and the countdown timer from the room DOM; tap
      websocket frames (`page.on('websocket')`) for pick events.
- [ ] **REST demoted to cross-check.** Divergence (DOM picks ≠ REST picks) ⇒
      trust DOM, log the lag, never block on REST.
- [ ] **Data-recency watchdog, not file-age.** Stale = clock not counting
      down / picks not advancing while a draft is live. A frozen room is a
      loud alarm within ~10s, not a silent "0 picks made".
- [ ] **Room-session watchdog + recovery protocol.** Detect the frozen-room
      signature (clock `--:--`, round stuck). Recovery = reload the room tab:
      requires navigation, so pre-authorize it in the runbook/grant as an
      explicit recovery action.
- [ ] **Single-device rule (hard).** While the agent drives, NO other device
      opens the draft room — league/team pages in the app are fine, the draft
      room is not. This goes in the user checklist in bold.
- [ ] **Short-clock cadence.** Read the real clock from the room DOM. Maintain
      a pre-computed top-3 shortlist BEFORE every one of our turns; on-turn
      action = one warm click, target ≤5s from turn start.
- [ ] **Warm actuator.** Persistent CDP connection + pre-located player rows;
      no cold playwright start per pick.
- [ ] **Validate in an ESPN mock draft** (user present ~20 min to authorize
      joining): measure DOM feed latency, confirm DRAFT button DOM in-turn,
      rehearse the ≤5s pick loop on a fast clock.

## What worked

- The pre-rank floor: uploaded, verified, and it delivered Nacua when the
  agent was blind. The floor remains the highest-value rung — build it first
  for both remaining drafts.
- Safety rails: zero unauthorized clicks, RoughRydas untouched, grant scoped
  and shredded. The system failed *silent*, not *unsafe* — but silent-blind
  is still a failure. The watchdogs above exist to make blindness loud.
