# ESPN Team Safety Rules

Last confirmed: 2026-08-28

## Authorized teams

- **Synaps1** — authorized for read-only analysis and user-approved draft-assistant work.
  - Current ESPN page identified by the user as Synaps1: league ID `305025860`, team ID `2`, season `2026`.
- **Synaps2** — authorized for read-only analysis and user-approved draft-assistant work. ESPN IDs not mapped yet.

## Protected team

- **RoughRydas** — **DO NOT TOUCH**.
  - Do not open it for automated work, modify it, draft for it, change its lineup, add/drop/trade players, alter settings, or submit any action for it.
  - If team identity is ambiguous, stop rather than risk acting on RoughRydas.

## Operational guardrail

All scripts that can perform ESPN actions must use an explicit allowlist for Synaps1 and Synaps2 and reject every other team by default. Browser work remains read-only unless the user explicitly authorizes a specific action.
