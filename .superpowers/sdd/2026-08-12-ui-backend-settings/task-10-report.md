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

## Исправления после review

### RED

```text
uv run pytest -q \
  tests/unit/web/test_scheduler_lifespan.py::test_blocking_sync_tick_keeps_loop_responsive_and_shutdown_bounded
# 1 failed: event loop был заблокирован 1,00 с синхронным tick

TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q \
  tests/integration/infrastructure/test_sqlalchemy_schedule.py::test_advisory_claim_wait_has_database_timeout \
  tests/integration/infrastructure/test_sqlalchemy_schedule.py::test_schedule_query_wait_has_statement_timeout
# 2 failed: repository не имел lock_timeout/statement_timeout contract

uv run pytest -q tests/unit/infrastructure/test_database_engine.py
# 1 failed: engine не ограничивал TCP connect и pool acquisition
```

### GREEN

- Lifespan владеет одним `ThreadPoolExecutor(max_workers=1)` и выполняет
  sync tick через `run_in_executor`. Ticks остаются последовательными:
  на каждый polling cycle не создаются новые threads или detached tasks.
- Shutdown отменяет и дожидается asyncio polling task, затем выполняет
  `executor.shutdown(wait=False, cancel_futures=True)`. Python не может принудительно
  остановить уже запущенный thread; поэтому asyncio shutdown имеет жёсткую
  границу, а DB worker дополнительно ограничен PostgreSQL timeout’ами.
- Repository устанавливает transaction-local `lock_timeout=1000ms` и
  `statement_timeout=5000ms` до schedule queries/claim. Advisory lock, durable insert
  и commit по-прежнему находятся в одной транзакции.
- Общий PostgreSQL engine ограничивает TCP connect и pool acquisition
  пятью секундами; timeout policy покрывает всю DB-границу до начала
  transaction-local PostgreSQL timeout’ов.
- Lifespan-тест с реально блокирующим sync method подтверждает
  отзывчивость event loop, bounded shutdown и завершение polling task.
  PostgreSQL 16 integration-тесты отдельно доказывают timeout
  occupied advisory lock и blocked configuration query.

```text
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q tests/unit/application/scheduling \
  tests/integration/infrastructure/test_sqlalchemy_schedule.py \
  tests/unit/web/test_scheduler_lifespan.py
# 19 passed in 2.98s

TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q tests/integration/test_migrations.py \
  tests/integration/test_web_component.py tests/integration/test_web_run_once_scope.py \
  tests/unit/web tests/unit/bootstrap/test_open_publish_once.py \
  tests/unit/infrastructure/test_database_engine.py
# 34 passed in 3.55s
```
