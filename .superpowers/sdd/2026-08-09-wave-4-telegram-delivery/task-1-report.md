# Отчёт RED-исполнителя Wave 4

## Файлы

- `tests/unit/domain/delivery/test_models.py`
- `tests/unit/application/delivery/test_publish_content.py`
- `tests/unit/adapters/telegram/test_bot_api.py`
- `tests/integration/infrastructure/test_sqlalchemy_delivery.py`
- `tests/integration/test_migrations.py`
- `tests/unit/config/test_settings.py`
- `tests/e2e/test_cli_publish_once.py`
- `tests/e2e/test_systemd_installer.py`
- `tests/unit/infrastructure/test_delivery_wheel.py`
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
- PostgreSQL/migrations: controller подтвердил на безопасной smoke DB `15 failed, 5 passed`; причины — только missing delivery module/schema. DSN не записан.
- Config RED: `12 failed, 62 passed`; существующие 62 сценария GREEN.
- CLI RED: `9 failed`; причина — нет `publish-once`.
- Systemd RED: `5 failed, 13 passed`; существующие installer-сценарии GREEN, нет publish pair/четырёх copy.
- Wheel RED: `1 failed`; чистый wheel собран, delivery modules/head отсутствуют.

## Self-review

- Все новые production-import находятся в test body/helper, collection errors нет.
- Expectations заданы литералами; fake хранят наблюдаемый event log.
- HTTP-тест использует `httpx.MockTransport` и реальный временный PNG.
- PostgreSQL-тесты задают реальные candidate/decision/attempt/package rows, конкуренцию, constraint и trigger rollback.
- `git diff --check` проходит.

## Concerns

- Live Telegram preflight не входит в RED-задачу.
