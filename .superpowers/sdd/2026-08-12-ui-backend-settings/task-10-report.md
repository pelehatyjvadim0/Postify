# Задача 10 — планировщик проекта

## RED

- Application scheduler отсутствовал:

```text
uv run pytest -q tests/unit/application/scheduling/test_project_scheduler.py
# collection error: No module named postify.application.scheduling
```

- PostgreSQL repository и durable claims отсутствовали:

```text
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q tests/integration/infrastructure/test_sqlalchemy_schedule.py
# collection error: No module named postify.infrastructure.repositories.sqlalchemy_schedule
```

- Lifespan не запускал polling task:

```text
uv run pytest -q tests/unit/application/scheduling tests/unit/web/test_scheduler_lifespan.py
# 2 failed, 6 passed: ticks=0, startup task не создан
```

- Дополнительные mutation gates до исправления:

```text
uv run pytest -q \
  tests/unit/application/scheduling/test_project_scheduler.py::test_scheduled_publish_uses_same_web_application_boundary_as_http \
  tests/unit/web/test_scheduler_lifespan.py::test_polling_continues_after_infrastructure_failure
# 2 failed: scheduler обходил public WebApplication boundary; DB failure завершал task

uv run pytest -q \
  tests/unit/application/scheduling/test_project_scheduler.py::test_source_cron_supports_bootstrap_weekday_range
# 1 failed: persisted default `0 9 * * 1-5` не распознавался
```

## GREEN

- `ProjectScheduler.tick(now)` читает persisted project schedules,
  переводит `now` в timezone каждого проекта и создаёт
  `run_once`/`publish_once` только в exact minute.
- Cron matcher поддерживает wildcard, list, range и step; поэтому
  bootstrap-значение `0 9 * * 1-5` работает.
- Repository читает только enabled sources/routes. `autopublish=false`
  не создаёт publish command.
- Claim использует `pg_advisory_xact_lock(project_id)`; lock, insert
  `schedule_slot_claims` и commit находятся в одной транзакции.
  Primary key `(project_id, kind, scheduled_for)` даёт project isolation,
  repeat idempotency и restart durability.
- Миграция `20260812_07` создаёт claims-таблицу; integration-тест
  выполняет upgrade, downgrade до `20260812_06` и повторный upgrade.
- HTTP и scheduler вызывают одни public `WebApplication` boundary и один
  `BoundedOperations`; duplicate `operation_busy` не подменяется отдельным flow.
  Publish composition теперь передаёт `project_id` в delivery и operation journal.
- FastAPI lifespan создаёт один task, ждёт 100 мс между ticks,
  логирует обычные infrastructure exceptions и продолжает polling.
  Shutdown отменяет и дожидается task; `CancelledError` не попадает
  в infrastructure handler.

Static UI и systemd timers не изменялись.

## Проверка

```text
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q tests/unit/application/scheduling \
  tests/integration/infrastructure/test_sqlalchemy_schedule.py \
  tests/unit/web/test_scheduler_lifespan.py
# 16 passed in 2.22s

TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q tests/integration/test_migrations.py \
  tests/integration/test_web_component.py tests/integration/test_web_run_once_scope.py \
  tests/unit/web tests/unit/bootstrap/test_open_publish_once.py
# 32 passed in 3.48s

uv run ruff check <все затронутые Python-файлы Task 10>
# All checks passed!

uv run python -m compileall -q <затронутые production packages>
# exit 0

git diff --check
# без вывода
```

PostgreSQL 16 запущен в отдельном test-контейнере на
`127.0.0.1:55432`; каждый integration-тест создавал и удалял
собственную PostgreSQL schema.
