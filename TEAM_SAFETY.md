# Team Safety Rules (ESPN + Yahoo)

Last confirmed: 2026-08-29

## Authorized teams

- **Synaps1** — authorized for read-only analysis and user-approved draft-assistant work.
  - Current ESPN page identified by the user as Synaps1: league ID `305025860`, team ID `2`, season `2026`.
- **Synaps2** — authorized for read-only analysis and user-approved draft-assistant work.
  - Mapped 2026-08-28: league ID `2144943745` ("2026 GTA VI B4 CASH W League"), team ID `4`, season `2026`, 12-team PPR snake, drafts Mon Sep 7 2026 6:00 PM EDT.

## Authorized Yahoo team (dad's league)

- **All I Do Is Win** (alias `allidoiswin`) — authorized for read-only analysis and user-approved draft-assistant work on Yahoo.
  - Mapped 2026-08-29 via read-only recon of the owner's logged-in session; confirmed verbatim by the account owner (Justin's dad, relayed by Justin) on 2026-08-29.
  - League ID `384341` ("Old Backs Fresh Minds"), team ID `6`, game key `470` (2026 NFL) → team key `470.l.384341.t.6`, season `2026`.
  - 10-team half-PPR (0.5/rec) H2H snake, 60s/pick, drafts Sun Sep 6 2026 10:00 AM EDT.
  - Verified the ONLY team on that Yahoo account — no other teams exist there to protect.

## Protected team

- **RoughRydas** — **DO NOT TOUCH**.
  - Do not open it for automated work, modify it, draft for it, change its lineup, add/drop/trade players, alter settings, or submit any action for it.
  - If team identity is ambiguous, stop rather than risk acting on RoughRydas.

## Operational guardrail

All scripts that can perform ESPN or Yahoo actions must use an explicit allowlist (Synaps1 + Synaps2 on ESPN; All I Do Is Win on Yahoo) and reject every other team by default. Browser work remains read-only unless the user explicitly authorizes a specific action.
