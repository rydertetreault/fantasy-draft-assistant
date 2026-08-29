# Spec: Live ESPN Draft Operator

Status: approved for planning

## Assumptions

1. The assistant supports exactly two allowlisted ESPN teams: Synaps1 and Synaps2.
2. Every unknown team/league combination is denied. RoughRydas must never be touched.
3. Synaps1 is a 10-team, full-PPR snake league with a 90-second clock and a randomized draft slot announced one hour before the draft.
4. Synaps2 settings and identifiers are still unknown and must be captured before it can be enabled.
5. The browser can lose connectivity and ESPN's DOM can change without notice.
6. No strategy can guarantee a league win; the objective is to maximize expected championship probability and avoid preventable draft-day failures.
7. Automated pick submission is enabled only after an explicit draft-day mode change by the user. Read-only observation and recommendations are the default.

## Objective

Build a reliable live-draft operator that observes ESPN draft state, maintains an independent state for each authorized team, ranks available players using current market and projection data, and either recommends or submits a pick within the clock. It must fail closed whenever identity, availability, state freshness, or authorization is uncertain.

## Success criteria

- Exact allowlist match is required before any ESPN write action.
- Unknown teams, including RoughRydas, cannot pass the identity guard.
- A newly observed pick updates recommendations within 3 seconds under normal conditions.
- Recommendations include a primary pick, two fallbacks, and concise reasons.
- Submitted picks are verified against ESPN's resulting draft state; retries are never blind.
- If state is stale, identity is ambiguous, or the browser disconnects, automation halts and signals manual takeover.
- Synaps1 and Synaps2 state files, strategies, and browser sessions cannot contaminate one another.
- A replay harness can simulate a complete snake draft, clock pressure, DOM changes, duplicate events, disconnects, and forbidden-team navigation without a human.

## Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
fantasy-draft recommend --config config.synaps1.yaml --round 1 --pick 1
# Planned commands:
fantasy-draft preflight --team synaps1
fantasy-draft observe --team synaps1
fantasy-draft run --team synaps1 --mode advisory
fantasy-draft run --team synaps1 --mode autopick --authorization-file <ephemeral-file>
fantasy-draft replay tests/fixtures/draft.jsonl
```

## Project structure

- `src/fantasy_draft_assistant/` — models, ranking, ESPN observer, safety guard, operator
- `scripts/` — data refresh and operational entry points
- `data/<team>/` — isolated draft state and generated boards
- `tests/` — unit, replay, safety, and timing tests
- `docs/` — strategy, runbook, spec, and plan
- Local browser cookies and authorization tokens remain outside Git

## Code style

Typed Python with pure decision functions and side effects isolated behind adapters:

```python
def can_submit(identity: TeamIdentity, allowlist: Allowlist, state_age_ms: int) -> bool:
    return identity in allowlist and state_age_ms <= 3_000
```

## Testing strategy

- Unit tests for scoring, roster constraints, next-turn probability, and identity checks.
- Replay tests using recorded/synthetic ESPN draft events.
- Property tests for duplicate/out-of-order picks and snake-order calculations.
- Fault injection for disconnects, stale state, changed selectors, expired login, and clock pressure.
- A browser harness against local HTML fixtures; live ESPN is a final read-only smoke test.
- Red/green proof for forbidden-team rejection and stale-state refusal.

## Boundaries

### Always

- Validate league ID, team ID, season, and configured alias before a write.
- Keep a timestamped event log and preserve a manual takeover path.
- Maintain at least three queued legal candidates before each turn.
- Run the full preflight and replay suite before draft-day autopick mode.

### Require explicit authorization

- Entering autopick mode for a named allowlisted team and specific draft session.
- Clicking the final ESPN Draft button.
- Any dependency, schema, or CI change beyond this approved plan.

### Never

- Act on RoughRydas or an unknown team.
- Store ESPN passwords, MFA codes, cookies, or session tokens in Git.
- Submit from stale/ambiguous state or retry a pick blindly.
- Treat ADP, projections, stacks, bye weeks, or a fixed round plan as absolute truth.
