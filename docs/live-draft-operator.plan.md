# Plan: Live Draft Operator

Convergence: **informed**

Fixed policy before implementation:

- Threshold: `0.80`
- Axis weights: spec compliance `0.35`, code quality `0.20`, test coverage `0.20`, edge cases `0.15`, security `0.10`
- Maximum fix iterations: `2`
- Maximum total role calls: `10`
- Rationale: medium/large feature with a browser actuator and a strict protected-team boundary.

> Note: engineering subagent dispatch was attempted during planning but is blocked by an expired Synaps authentication token. No subagent result was used. Implementation must not claim convergence until fresh role calls can run.

## Dependency graph

`team identity + event models` → `safety guard + state reducer` → `ranking engine` → `ESPN observer` → `operator modes/actuator` → `replay harness + preflight` → `draft-day runbook`

## Task 1: Freeze identities and isolate team state

**Description:** Define typed team identities and separate paths/configuration for each authorized team.

**Acceptance criteria:**
- Synaps1 exact identity is allowlisted and Synaps2 remains disabled until mapped.
- Unknown identities and RoughRydas are rejected by default.
- Team states cannot share draft picks or rosters.

**Verification:** `pytest -q tests/test_safety.py tests/test_state_isolation.py`

**Dependencies:** None  
**Files likely touched:** models, safety, config, tests  
**Scope:** M

## Task 2: Replace sample data with a reproducible data pipeline

**Description:** Merge current projections, ESPN rankings/ADP, injuries, and role metadata while retaining source timestamps.

**Acceptance criteria:**
- Every row has stable player identity, position, source timestamp, and uncertainty fields.
- Stale or malformed sources are visibly rejected or down-weighted.
- Refresh can run without browser write access.

**Verification:** fixture-driven data tests plus schema validation  
**Dependencies:** Task 1  
**Files likely touched:** scripts, data models, fixtures, tests  
**Scope:** M

## Task 3: Build replacement-value and turn-aware ranking

**Description:** Rank available players using projected distributions, replacement/FLEX value, tier cliffs, roster construction, and next-turn survival.

**Acceptance criteria:**
- Output contains primary plus two legal fallbacks with explanations.
- Snake order and next-turn calculations work for every slot and round.
- DST/K waiting policy and roster limits are enforced without overriding exceptional legal cases silently.

**Verification:** deterministic scenario tests and Monte Carlo seed replay  
**Dependencies:** Tasks 1-2  
**Files likely touched:** ranking, simulation, models, tests  
**Scope:** M

## Checkpoint 1: Decision engine

- Data schema validates.
- Static draft scenarios produce legal, explainable recommendations.
- Safety and isolation tests are green.
- Durable artifact: checkpoint commit and verification log.

## Task 4: Implement idempotent ESPN draft observation

**Description:** Convert ESPN events/DOM state into normalized picks without duplicates and reconcile against full board snapshots.

**Acceptance criteria:**
- New picks appear in local state within 3 seconds in fixture/browser tests.
- Duplicate and out-of-order events converge to the same state.
- Selector/API failure marks state stale instead of inventing state.

**Verification:** replay and browser-fixture tests  
**Dependencies:** Task 1  
**Files likely touched:** espn adapter, reducer, fixtures, tests  
**Scope:** M

## Task 5: Add explicit operational modes

**Description:** Support `observe`, `advisory`, and ephemeral `autopick` modes with default read-only behavior.

**Acceptance criteria:**
- Restart always returns to non-writing mode.
- Autopick requires session-specific authorization for an exact allowlisted identity.
- Stale state, identity mismatch, unavailable candidate, or expired authorization blocks submission.

**Verification:** mode transition and fault-injection tests  
**Dependencies:** Tasks 1 and 4  
**Files likely touched:** operator, authorization, CLI, tests  
**Scope:** M

## Task 6: Implement verified pick submission

**Description:** Select a candidate, submit once, and verify the resulting ESPN state before continuing.

**Acceptance criteria:**
- Candidate identity and availability are rechecked immediately before click.
- One click is followed by state verification; no blind retry occurs.
- Primary failure can use a still-available fallback only while state and clock remain safe.

**Verification:** local browser harness with changed DOM, delayed confirmation, and rejected picks  
**Dependencies:** Tasks 3-5  
**Files likely touched:** actuator, operator, browser fixture, tests  
**Scope:** M

## Checkpoint 2: Safe browser loop

- Full observation-to-recommendation path is under the timing budget.
- Every attempted forbidden/stale write is rejected.
- Actuator passes idempotency and manual-takeover scenarios.
- Durable artifact: checkpoint commit and oracle-style verdict.

## Task 7: Build unattended end-to-end replay harness

**Description:** Simulate a full 10-team snake draft, human authorization, clock pressure, disconnects, DOM drift, and forbidden-team navigation.

**Acceptance criteria:**
- Harness completes without a human and emits structured pass/fail evidence.
- It proves red→green for RoughRydas rejection, stale-state refusal, and duplicate-pick handling.
- Timing report identifies any decision exceeding its budget.

**Verification:** `pytest -q` plus one-command replay harness  
**Dependencies:** Tasks 1-6  
**Files likely touched:** harness, fixtures, integration tests, docs  
**Scope:** M

## Task 8: Draft-day dashboard and audit log

**Description:** Show timer, identity, freshness, roster, top candidates, reasons, mode, and last verified action.

**Acceptance criteria:**
- Operator can identify manual takeover conditions at a glance.
- Every state transition and attempted action is timestamped without secrets.
- Separate dashboards/logs exist for Synaps1 and Synaps2.

**Verification:** snapshot/output tests and secret scan  
**Dependencies:** Tasks 3-6  
**Files likely touched:** UI, logging, tests  
**Scope:** M

## Task 9: Execute preflight and mock-draft rehearsal

**Description:** Run the complete system against a replay and an ESPN practice draft before the real event.

**Acceptance criteria:**
- Login, exact identity, clock, draft slot, and queue are verified.
- A full rehearsal records no stale, duplicate, or cross-team actions.
- Manual fallback board and ESPN queue are ready if automation fails.

**Verification:** signed/timestamped preflight report  
**Dependencies:** Tasks 1-8  
**Files likely touched:** runbook, generated report  
**Scope:** S

## Checkpoint 3: Draft-ready gate

- Full test suite and unattended replay pass.
- Live read-only smoke test passes for the exact team.
- User explicitly chooses advisory or autopick mode for that draft session.
- Durable artifact: final verification report, clean worktree, and resume token.

## Draft-day timing budget

- **T-60 minutes:** obtain draft slot; calculate slot-specific turn map and candidate tiers.
- **T-45:** refresh news/injuries, projections, ADP, and ESPN pre-draft ranks.
- **T-30:** login and exact identity preflight; populate an ESPN queue as outage insurance.
- **T-15:** run read-only state synchronization and full replay smoke test.
- **At each opposing pick:** reconcile state within 3 seconds and update survival estimates.
- **Before our turn:** maintain at least three currently available candidates.
- **Our turn, 90-45 seconds:** verify board and choose primary/fallbacks.
- **By 45 seconds:** submit in authorized autopick mode; do not intentionally wait for the final seconds.
- **By 30 seconds:** if confirmation is missing, halt automation and use manual takeover—never blind-click.
- **After pick:** verify player/team/overall pick and persist an audit event.

## Risks and mitigations

- **Bad/stale projections:** source timestamps, ensemble inputs, uncertainty, late news refresh.
- **ESPN changes:** semantic selectors/API observation, full-state reconciliation, local fixture tests, manual fallback.
- **Network/browser loss:** preloaded queue, paper board, second device, no last-second submission policy.
- **Autodraft race:** act early and verify; ESPN queue contains acceptable fallback ordering.
- **Wrong team:** exact immutable IDs and default deny; Synaps2 stays disabled until mapped.
- **Strategic overfitting:** tiers and probabilistic survival replace rigid round scripts.
- **Two simultaneous drafts:** do not automate both in one tab/session; use isolated profiles/processes and independent operators.

## Required next inputs

1. Open Synaps2 manually so its immutable identifiers and settings can be captured safely.
2. Confirm the actual draft date/time for Synaps2.
3. Re-authenticate Synaps engineering tooling before convergence implementation (`synaps login`).
