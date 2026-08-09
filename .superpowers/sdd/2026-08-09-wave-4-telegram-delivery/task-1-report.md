# Отчёт RED-исполнителя Wave 4

## Файлы

- `tests/unit/domain/delivery/test_models.py`
- `tests/unit/application/delivery/test_publish_content.py`
- `tests/unit/adapters/telegram/test_bot_api.py`
- `tests/integration/infrastructure/test_sqlalchemy_delivery.py`
- `tests/integration/test_migrations.py`
- `docs/development-loop/evidence/2026-08-09-wave-4-red.md`

Production-файлы не менялись.

## Трассировка и мутации

Полная таблица `requirement → test → RED → mutation` находится в `docs/development-loop/evidence/2026-08-09-wave-4-red.md`.

Карта мутаций, привязанных к конкретным тестам: wrong status filter; reverse FIFO; remove `SKIP LOCKED`; remove unique; reserve two; confirm without message ID; package published before Telegram confirmation; auto-retry uncertain; retry failed terminal; skip stale conversion; delete before commit; call Telegram during cleanup; omit attempt; leak token/URL/caption/file bytes; wrong multipart field/MIME/basename; accept malformed JSON; omit cleanup marker; omit named migration constraints; break downgrade/re-upgrade. Покрыто 21 реалистичное изменение.

## Запуски

- Baseline `uv run pytest tests/unit tests/e2e -q`: `327 passed`.
- Domain RED: `4 failed`; причины — отсутствует `postify.domain.delivery`, нет `PackageStatus.PUBLISHED`.
- Application RED: `11 failed`; причина — отсутствует `postify.application.delivery`.
- Telegram adapter RED: `10 failed`; причина — отсутствует `postify.adapters.telegram`.
- `compileall` для новых/изменённых тестов: успех.
- `TEST_DATABASE_URL`: missing. Integration RED не запускался и остаётся pending; DSN не выводился, `DATABASE_URL` для будущего запуска должен быть unset.

## Self-review

- Все новые production-import находятся в test body/helper, collection errors нет.
- Expectations заданы литералами; fake хранят наблюдаемый event log.
- HTTP-тест использует `httpx.MockTransport` и реальный временный PNG.
- PostgreSQL-тесты задают реальные candidate/decision/attempt/package rows, конкуренцию, constraint и trigger rollback.
- `git diff --check` проходит.

## Concerns

- По срочному приоритету оркестратора первый атомарный commit ограничен domain/application/adapter/repository/migration. Config/CLI/systemd/wheel ещё не вошли и должны быть добавлены следующим RED-проходом.
- Integration semantics спроектированы и компилируются, но их фактический RED не подтверждён без безопасной test DB.
