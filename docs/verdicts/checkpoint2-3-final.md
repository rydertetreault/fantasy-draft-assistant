# Convergence verdicts — Checkpoints 2 & 3 (final)

- Checkpoint 2 (data pipeline, observer, modes, verified submission): PROCEED 0.888
- Checkpoint 3 (replay harness, dashboard/audit, preflight/runbook) + whole-feature: APPROVE 0.93
- Evidence: 240/240 pytest green; browser fixture suite 6/6 distinct refusal exit codes; full 342-event replay 16/16 picks confirmed, timing max 2.6ms vs 3000ms budget; preflight 9/9 incl. RoughRydas PermissionError self-test; audit secret-scan clean.

## Non-blocking follow-ups (before any --live use)
1. LOW security: add value-level credential regex (espn_s2=, SWID={, Bearer ) to audit scrub().
2. LOW edge: dashboard should render mode as "unknown" when newest audit event is older than a threshold.
3. LOW test: shell check that --live --allow-file-fixture exits 2.

## Unprovable without live ESPN (accepted risks; runbook covers procedure)
Live read-only smoke test; real draft-room selectors (dry-run first!); 3s budget under real latency; live click->confirmation loop; Synaps2 unmapped (stays disabled); session id changes if draft is rescheduled (re-run preflight, re-issue grant).
