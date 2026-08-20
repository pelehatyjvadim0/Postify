# Final re-review 2 — 2026-08-17

Scope: product commit `497746a` against the three blockers in
`final-rereview.md`, plus the environment, backup and durable evidence
requirements of the remediation request.

## Finding closure

1. **Wrong route/channel — closed.** Route ID is present in schedule reads,
   command/claim/job persistence and the web/open-project boundary. Delivery
   retries require persisted route and channel equality. Two-route regressions
   cover a higher-ID due route and a retry owned by the other route.
2. **Crash-orphaned accepted work — closed.** Slot claim, running operation and
   queued job commit atomically. Lease claim/ack plus queued/expired recovery
   are durable. A new `WebApplication` executes a previously accepted callback
   exactly once and persists `succeeded`, attempt count `1`.
3. **Journal/attempt contract — closed.** Empty state retains toolbar and
   operational snapshot; populated state includes deficit reasons. Attempt DTO
   query and UI show code and reason. Browser regression covers both shapes.
4. **Operator docs — closed.** Executable shell tests prove spaced `.env`
   values survive source and SQLAlchemy driver stripping produces a real libpq
   pg_dump target; schema-only pg_dump succeeded against PostgreSQL 16.14.
5. **Evidence truthfulness — closed.** Run-006, RED, review and progress ledger
   identify the tested commit and current gate counts. The tracked manifest
   references 16 existing PNG files with hashes and overflow measurements.

## Verdict

**APPROVED for Wave 6.** The prior NOT APPROVED record remains historical and
is superseded for product commit `497746a`. Merge, push, worktree deletion and
cache cleanup are not authorized by this verdict.
