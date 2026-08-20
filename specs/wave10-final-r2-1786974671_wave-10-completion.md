# Wave 10 completion plan

## Objective and governing behavior

Finish the existing dirty `feature/ui-v1-html-mockup` worktree in place. Preserve and correct the current Codex profile/schema, Telegram checking, manual-operation, migration, and UI work; do not reset it, create another branch, or change SSSF/ADW files.

`wave-10.md` remains the baseline, with one explicit override from the latest request: rejecting a package is a one-click operation. The UI must not ask for a reason, the API must not accept/use a rejection reason, the database must not store one on the rejection history event, and the open package detail dialog must close after a successful rejection. Candidate-selection rejection reasons are unrelated and remain intact. Do not pass package-rejection feedback to Codex.

## Current-state findings to correct

- The worktree has a partial `ExecutionContext` and manual counters, but behavior is still selected by ad-hoc conditionals and defaults. Some manual claims can consume unrelated scheduled retries, and scheduler callers rely on implicit automatic defaults.
- `WebApplication._submit_operation()` reaches into `RunOnce._content`, performs delivery lookup with raw SQL, and assembles media replacement itself. This duplicates orchestration instead of sharing application actions.
- Load-more returns `202` and refreshes after a fixed 1.2 seconds; it does not poll the accepted operation to a terminal result or distinguish completed, empty, failed, and unresolved-review results.
- Durable same-project/same-operation exclusion already exists through the partial unique index and `ON CONFLICT`, but it needs coverage for load-more/manual actions and must remain the authority across web processes.
- Manual/automatic usage counters and `mode`/`actor` exist, but operation runs do not yet store the Codex profile or material/package counts required by the journal.
- Retry/regeneration can create further attempts, while the domain model still globally restricts `attempt_no` to 1 or 2. The automatic retry policy, not the attempt-history type, should own the two-attempt automatic limit.
- Package regeneration preserves old rows indirectly but has no explicit package-version lineage. Media versions exist, but project ownership and history guarantees need tightening.
- Rejection still requires `RejectRequest.reason`, stores it in `content_package_status_history.reason`, and shows a reason form.
- Load-more and other content operations currently turn some technical failures into successful `empty` journal outcomes. Terminal status must reflect the real result.
- The current diff has trailing whitespace in `tests/ui_mockup/test_browser_flows.py`; clean that while updating the tests.

## Target contracts

### Server-owned execution policy

Represent execution mode with validated enums/value objects rather than free-form strings. The context must include `mode` (`automatic` or `manual`), `actor` (`scheduler` or `ui`), operation purpose, optional target, and batch size. Make operation-specific invariants explicit:

- scheduler `run_once`/`publish_once`: automatic, actor scheduler, quotas/fresh-reserve credits/retry windows/schedules enabled;
- UI search: manual, actor UI, imports/selects through the normal run-once services and processes content without reading or incrementing automatic counters;
- load-more: manual batch size exactly 3, only never-processed selected candidates, no scheduled-retry sweep;
- retry-analysis: exactly the requested failed/retryable attempt, immediately, never an unrelated retry;
- return-to-analysis/regenerate: exactly the project-owned package and a new persisted attempt/package version;
- replace-media: the existing package, shared extraction/media services, no analysis/package quota;
- publish-now/retry-delivery: targeted delivery through `PublishContent`, without schedule/day-plan gating but with route/channel/secret/Telegram/idempotency/message-id checks.

No request schema may expose `mode`, `actor`, `bypass_quotas`, or similar controls. Route handlers choose the manual context; scheduler composition passes the automatic context explicitly.

### Operation API and journal

Keep the resource-oriented mutation endpoints already introduced:

- `POST /api/v1/projects/{project_id}/operations/search`
- `POST /api/v1/projects/{project_id}/packages/load-more`
- `POST /api/v1/projects/{project_id}/attempts/{attempt_id}/retry-analysis`
- `POST /api/v1/projects/{project_id}/packages/{package_id}/return-to-analysis`
- `POST /api/v1/projects/{project_id}/packages/{package_id}/regenerate`
- `POST /api/v1/projects/{project_id}/packages/{package_id}/media/replace`
- `POST /api/v1/projects/{project_id}/packages/{package_id}/publish-now`
- `POST /api/v1/projects/{project_id}/deliveries/{delivery_id}/retry`

All return `202` with `status: accepted` and `operationRunId`; load-more also returns `requested: 3`. Add `GET /api/v1/projects/{project_id}/operations/{operation_run_id}` for project-scoped polling. Its response must expose kind, mode, actor, status, outcome/failure code, configured Codex model/effort when Codex actually ran, materials taken, packages created, and timestamps. A foreign-project run is `404`.

Use `succeeded/completed` only when the action completed correctly, `succeeded/empty` for a real no-work/no-selected-package result with zero created packages, and `failed` with an allowlisted safe code for technical failure. Always persist actual counts, including partial work. Manual runs must never emit automatic quota-limit codes or alter automatic deficit calculations.

### One-click rejection

`POST /api/v1/projects/{project_id}/packages/{package_id}/reject` has no reason body. It performs the existing atomic status/history transition, writes the rejected history row with `reason = NULL`, then performs the existing recoverable media cleanup. The detail dialog closes only after the server confirms rejection; failures keep it open and show the generic safe error. A second/invalid transition remains `409 invalid_transition`.

## Implementation steps

### 1. Normalize execution policy and shared action boundaries

Update `src/postify/domain/content/models.py` and `src/postify/domain/observability/models.py`:

- replace stringly mode/actor/purpose checks with enums and operation-specific validation;
- require positive attempt numbers in `ContentAttempt`, leaving the automatic maximum-two rule in automatic processing policy;
- add structured operation result/summary fields for counts and optional Codex profile;
- keep the existing safe Codex output and delivery outcome taxonomies closed and validated.

Update ports in `src/postify/application/ports/content_repository.py`, `operation_run_repository.py`, `dashboard_repository.py`, and `delivery_repository.py` so actions receive explicit policy/targets and return structured results. Do not use `getattr`, private action attributes, or raw database access from the web facade.

Refactor actions in `src/postify/application/content/process_content.py`, `review_content.py`, `replace_media.py`, `src/postify/application/jobs/run_once.py`, `src/postify/application/delivery/publish_content.py`, and `src/postify/application/observability/record_operation.py`. Add a small action module such as `src/postify/application/content/manual_operations.py` if needed to express the eight owner commands. Actions own eligibility, ownership, status transitions, result classification, and operation metadata. Existing extractor, Codex analyzer, media provider, importer/selector, delivery repository, publisher, and cleanup mechanics remain reusable capability services; do not build a parallel manual pipeline or a god service.

Specific corrections:

- split import/select/content steps so manual search can reuse the normal run-once chain while load-more/retry/regenerate can invoke only the required shared action without reaching into `RunOnce` internals;
- make claim selection operation-aware: load-more excludes all previously attempted candidates and scheduled retries; targeted commands either claim the exact target or return a safe ineligible/not-found result;
- make automatic article retry retain its six-hour window and two-attempt cap; manual retry is immediate and creates append-only attempts;
- return whether Codex ran and the material/package counts; classify Codex/schema/extraction/media failure as failed rather than a fictitious empty success;
- on regenerate, link the new package version to the requested package while retaining every old attempt/package/status row;
- on media replacement, retain the previous media version before swapping the current media atomically;
- on targeted publication, do not let unrelated cleanup consume the owner command. Reuse the same `PublishContent` send/confirm/failure code and keep stale-send, duplicate-delivery, route/channel and message-id safeguards.

### 2. Complete migrations and repository invariants

Review and correct the uncommitted revisions `20260817_10` through `20260817_15`, especially downgrade constraints, clean-install behavior, and all operation-kind/failure-code checks. Keep them in the existing linear chain. Add a follow-up head migration, for example `src/postify/infrastructure/database/migrations/versions/20260817_16_finalize_wave10_operations.py`, so an already-upgraded local database also receives final invariants.

The final schema must:

- keep `content_daily_usage.analyses_started/packages_created` automatic-only and nonnegative, with separate nonnegative manual columns;
- keep `operation_runs.mode/actor`, and add nullable `codex_model`, nullable `codex_reasoning_effort`, nonnegative `materials_taken`, and nonnegative `packages_created` (plus checks that automatic/scheduler and manual/ui pair correctly);
- retain the partial unique index on `(project_id, operation)` for `status='running'`;
- make `content_package_status_history.reason` nullable so a reject event stores SQL `NULL`, not an empty string or sentinel reason;
- add project-safe package version lineage (a composite project/package foreign key or an equivalent version table) and project-safe media-version foreign keys/indexes;
- preserve existing unique attempt/package, delivery, and project isolation constraints;
- have a reversible downgrade to the prior head and a clean upgrade from the original base through the new head.

Update `src/postify/infrastructure/repositories/sqlalchemy_content.py`, `sqlalchemy_observability.py`, `sqlalchemy_dashboard.py`, and `sqlalchemy_delivery.py`:

- use transactions and `FOR UPDATE`/`SKIP LOCKED` where claims or version numbers race;
- increment only the mode-specific counters and never fresh/reserve credits for manual work;
- persist operation metadata on terminal success and failure;
- expose one project-scoped operation by ID for polling;
- keep the existing database-level running-operation exclusion and translate conflicts to `operation_busy`;
- scope every target lookup and mutation by `project_id`, including delivery route lookup and package/media lineage;
- retain positive integer `message_id` validation and atomic attempt/delivery/package confirmation.

Update dashboard/observability models and queries in `src/postify/application/dashboard/models.py`, `show_dashboard.py`, `src/postify/application/observability/show_status.py`, and their repositories. Automatic coverage/deficit/quota signals must continue to use only automatic counters. Dashboard and journal responses must display the separate manual totals and all new run metadata without inventing `unknown_persisted_state` for valid manual rows.

### 3. Make scheduler and composition explicit

Update `src/postify/bootstrap.py`, `src/postify/application/scheduling/project_scheduler.py`, and `src/postify/web/services.py`:

- make CLI/scheduler factories pass automatic policy explicitly and preserve scheduled-job acceptance/lease/acknowledgement behavior;
- make every UI mutation create manual/UI policy server-side;
- replace the private `_content` access, inline media composition, and raw delivery SQL with public application actions/factories;
- start one durable operation run before background submission, update that same run to exactly one terminal state, and leave scheduled operation IDs/acknowledgements consistent on success or failure;
- read model and reasoning effort from the fresh project runtime graph for each Codex invocation and journal the profile actually used;
- require the target route/channel to be enabled, secret-configured, and in an acceptable checked state; manual publish bypasses only timing/plan rules, not Telegram preflight or send safeguards.

Keep `BoundedOperations` only as executor/capacity management. Database ownership remains the cross-process idempotency authority. Ensure submission failure terminalizes the accepted run safely.

### 4. Tighten HTTP contracts

Update `src/postify/web/routes/api.py`, `src/postify/web/schemas.py`, and `src/postify/web/errors.py` as needed:

- remove `RejectRequest` and call `reject(project_id, package_id)` without a reason;
- retain CSRF enforcement on every mutation and existing safe error serialization;
- make all eight manual commands `202` and return their run IDs;
- add the operation-detail polling endpoint and typed response allowlist;
- return `409 review_unresolved` for load-more with project-scoped unresolved package IDs, `409 operation_busy` for duplicate running work, and safe `404/409` responses for ineligible foreign/stale targets;
- never serialize secrets, raw Codex prompts/output, Telegram errors, SQL errors, or client-controlled bypass data.

### 5. Finish the browser behavior

Update `src/postify/web/static/api.js`, `app.js`, `screens.js`, and `styles.css`:

- make the reject button call the mutation directly; remove the reject-reason form and request body; after success call `closeDetail()`, show the toast, and refresh the review data;
- implement an abortable operation poller using the returned `operationRunId`; load-more stays disabled and reads `Анализируем материалы…` until the run is terminal, not for a fixed timeout;
- on completed load-more, fetch packages and rerender the review list in the SPA without a document reload so new media-backed cards/detail views are available;
- render the exact empty message `Новых материалов нет. Запустите новый поиск.`, a safe failed state with a retry button, and an unresolved state that identifies packages still awaiting review;
- prevent repeat clicks locally while running and handle server `operation_busy` consistently;
- preserve default `Подобрать ещё 3 поста` after a resolved/retryable state;
- extend overview/journal/detail rendering with automatic limits, manual totals, mode, actor, Codex profile, material/package counts, terminal outcome, and safe failure code;
- keep accessible focus restoration, dialog behavior, responsive layout, and current design rather than redesigning the UI.

### 6. Add regression coverage before declaring completion

Update existing tests and add focused files where separation is clearer.

Unit coverage:

- `tests/unit/domain/content/test_models.py` and `tests/unit/domain/observability/test_models.py`: policy invariants, unlimited append-only manual attempt numbering, operation metadata, valid terminal states/codes;
- `tests/unit/application/content/test_process_content.py`, `test_review_content.py`, and a manual-operations test module: automatic quota stop, manual bypass without automatic increments, exact target selection, load-more batch cap, empty versus failed classification, version preservation, immediate rejection with no reason;
- `tests/unit/application/jobs/test_run_once.py`, `tests/unit/application/scheduling/test_project_scheduler.py`, and bootstrap tests: explicit automatic policy and shared actions;
- `tests/unit/application/delivery/test_publish_content.py` and adapter tests: targeted publish/retry still enforce route/channel, idempotency, safe Telegram failures, and positive `message_id`;
- `tests/unit/application/observability/test_record_operation.py`/`test_show_status.py`: complete journal fields and manual work excluded from automatic deficit/quota signals;
- `tests/unit/web/test_api.py`: no-body rejection, project-scoped polling and manual endpoints, `202` payloads, CSRF, conflict/error mapping, and rejection of any bypass field;
- retain/extend `tests/unit/adapters/ai/test_codex_content_analyzer.py` to assert project-selected `gpt-5.6-luna`/`high`, `--output-schema`, strict Pydantic v2 validation, sanitized failures, and cleanup.

PostgreSQL integration coverage:

- `tests/integration/test_migrations.py`: upgrade/downgrade/new head, nullable rejection reason, separate counters, journal metadata/checks, version lineage/project-safe FKs, operation-kind constraints, and wheel migration inclusion;
- `tests/integration/infrastructure/test_sqlalchemy_content.py`: exhausted automatic limit versus manual success, no automatic counter/credit changes, repeated batches of at most three, two concurrent load-more attempts with no duplicate attempts/packages, exact immediate retry, append-only regeneration, media versions, reasonless rejection, and cross-project targets;
- `test_sqlalchemy_observability.py`/`test_sqlalchemy_dashboard.py`: cross-process operation exclusion, one terminal update, separate metrics, complete manual journal fields, and no false quota/deficit/unknown-state signals;
- `test_sqlalchemy_delivery.py`: project-scoped targeted publish/retry, route affinity, concurrent retry idempotency, Telegram failure persistence, atomic positive message identifiers, and no duplicate send;
- `tests/integration/test_web_operation_ownership.py`, `test_web_run_once_scope.py`, `test_web_component.py`, and `test_project_runtime_configuration.py`: server-selected manual/automatic contexts, shared public actions, fresh project model/effort, polling ownership, and scheduler behavior unchanged.

Browser coverage in `tests/ui_mockup/test_browser_flows.py`:

- load-more default, running/disabled, completed refresh, empty, safe failure/retry, unresolved-with-package-identifiers, duplicate click, and newly created package detail/media;
- direct one-click rejection sends no reason/body, never renders a reason control, closes the dialog after success, refreshes the list, and leaves the dialog open on failure;
- all other manual buttons hit their project-scoped endpoint and preserve appropriate dialog/toast behavior;
- dashboard and journal render separate automatic/manual metrics and complete run metadata.

Keep the established Codex, Telegram checker, project-isolation, scheduler recovery, installed-wheel, static asset, and CLI regression suites green.

## Verification sequence

Run from the worktree, judging every command by exit status:

1. Focused unit and browser tests while iterating, then `uv run pytest -m 'not integration' -q` with the repository's expected test environment (or explicit non-integration test paths if marker leakage still collects DB fixtures).
2. Start/use the repository's PostgreSQL test instance and run `TEST_DATABASE_URL='<postgresql+psycopg test URL>' uv run pytest -m integration -q`, followed by full `TEST_DATABASE_URL=... uv run pytest -q`.
3. `uv run ruff check .`.
4. `python -m compileall -q src tests`.
5. `node --check src/postify/web/static/api.js`, `app.js`, `screens.js`, and `settings.js`.
6. `uv lock --check` and `uv build --offline`; inspect/install the wheel through the existing package/wheel tests so the new migration, Python modules, and static assets work outside the checkout.
7. `git diff --check` and `git diff --check 9a499cb --`.
8. With the local app and a disposable project/database, exhaust the automatic package quota, invoke UI load-more, wait for its terminal run, verify up to three new media-backed packages open in detail, and confirm automatic counters remain unchanged. Exercise publish-now only with a safe test Telegram target/credentials; otherwise rely on the mocked/integration delivery tests and do not send externally.

Do not commit, push, merge, reset, or alter unrelated files. The builder should finish with only the requested source/test/spec work in the existing dirty worktree.
