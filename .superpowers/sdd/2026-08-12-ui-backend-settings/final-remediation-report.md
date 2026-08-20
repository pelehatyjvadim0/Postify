# Final remediation report — 2026-08-17

Tested product commit: `497746a` (`d08cb7d` contains the durable backend fix).

## Changes

- `ScheduledCommand` and persisted slot identity carry `route_id`; web publish
  opens that exact route.
- Delivery retry selection uses persisted project/route/channel equality.
- `scheduled_jobs` is written in the same transaction as slot acceptance and
  operation ownership. Workers claim a lease and acknowledge success/failure;
  queued or expired leased work is recovered after restart.
- Empty and populated Journal states always render operational controls,
  runtime, signals and deficit reasons. Attempt query/DTO/UI includes `code`
  and `reason`.
- `.env.example` quotes spaced shell values. README converts the recommended
  SQLAlchemy PostgreSQL URL to a libpq URL before `pg_dump`.
- Capture script produces a durable, checksummed visual matrix and manifest.

## Verification

```console
TEST_DATABASE_URL='postgresql+psycopg://<redacted>@127.0.0.1:55434/postgres' uv run pytest -q
741 passed in 51.85s

TMPDIR=/dev/shm/postify-gate-tmp PYTHONDONTWRITEBYTECODE=1 TEST_DATABASE_URL='postgresql+psycopg://<redacted>@127.0.0.1:55434/postgres' uv run pytest -p no:cacheprovider -q tests/integration/test_project_runtime_configuration.py tests/integration/test_web_component.py tests/integration/test_web_operation_ownership.py tests/integration/infrastructure/test_sqlalchemy_schedule.py tests/integration/infrastructure/test_sqlalchemy_delivery.py
37 passed in 5.20s

TMPDIR=/dev/shm/postify-browser-final PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/home/user/.cache/uv uv run pytest -p no:cacheprovider -q tests/ui_mockup/test_browser_flows.py
77 passed in 30.36s

TMPDIR=/dev/shm/postify-wheel-tmp PYTHONDONTWRITEBYTECODE=1 TEST_DATABASE_URL='postgresql+psycopg://<redacted>@127.0.0.1:55434/postgres' uv run pytest -p no:cacheprovider -q tests/e2e/test_cli_ui.py
1 passed in 3.44s
```

Ruff, compileall, `uv lock --check`, four JavaScript syntax checks,
`git diff --check` and range diff-check all exited `0`. The test server reports
PostgreSQL 16.14. A schema-only real `pg_dump` using the README-converted libpq
target exited `0`.

Capture command exited `0`; manifest product commit is `497746a`, contains 16
PNG records with valid SHA-256 hashes and zero horizontal overflow records.
No push, merge, secrets, worktree deletion or cache cleanup occurred.
