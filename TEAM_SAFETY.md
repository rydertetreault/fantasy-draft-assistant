# Team Safety Rules (ESPN + Yahoo)

Last confirmed: 2026-09-06

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

## Authorized ESPN team (owner's own — added 2026-09-06)

- **RoughRydas** (alias `roughrydas`; ESPN display name "Rough Rydahs") — authorized for read-only analysis AND user-approved draft-assistant work, same footing as Synaps1/Synaps2.
  - **Authorization:** the account/team owner (Ryder) stated directly in-session on 2026-09-06 that RoughRydas is their own team and authorized the agent to draft for it. Recorded verbatim intent: "i am the owner. authorized."
  - League ID `1851947` ("The Tetreau Invitational"), team ID `1`, season `2026`. 10-team full-PPR snake, 90s/pick, draft slot 8, drafts Sun Sep 6 2026 8:00 PM EDT. Profile: `config.roughrydas.yaml`.
  - History: this team was the hard-forbidden "DO NOT TOUCH" entry from 2026-08-28 through 2026-09-06 (`FORBIDDEN_ALIASES` in `safety.py`, refusal checks in `espn_poll.mjs`/`espn_room_poll.mjs`/`espn_actuate.mjs`). Those were removed 2026-09-06. The forbidden-alias *mechanism* remains in code (currently an empty set) and stays covered by tests.
  - Yahoo scripts still hard-refuse the alias `roughrydas`; this is moot (no such Yahoo team) and was left in place.

## Protected teams

- None currently named. Every team not on the allowlist above is denied by default — the allowlist is the protection.

## Operational guardrail

All scripts that can perform ESPN or Yahoo actions must use an explicit allowlist (Synaps1 + Synaps2 + RoughRydas on ESPN; All I Do Is Win on Yahoo) and reject every other team by default. Browser work remains read-only unless the user explicitly authorizes a specific action.
