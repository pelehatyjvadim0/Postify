# Файловая архитектура Postify

## Цель

Сохранить MVP одним запускаемым Python-приложением, но отделить предметные правила от базы данных, внешних API и systemd. Архитектура должна позволить позднее выделить видеосервис без зависимости его кода от Telegram.

## Выбранный подход

Выбран модульный монолит с портами и адаптерами.

- `domain` содержит предметные сущности и правила без SQL, HTTP, systemd и чтения окружения;
- `application` содержит сценарии работы и порты, которые нужны этим сценариям;
- `adapters` реализуют интеграции с Algolia, Telegram, OpenRouter и медиа-источниками;
- `infrastructure` содержит PostgreSQL, реализации репозиториев, журналирование и управление systemd;
- `deploy` содержит только файлы развёртывания Ubuntu/VPS;
- `migrations` содержит миграции Alembic;
- `tests` повторяет границы приложения: модульные, интеграционные и сквозные тесты.

Это проще микросервисов для первого запуска: один процесс задачи, одна БД и один набор команд. В то же время правила отбора и контентный бриф не зависят от Telegram. Будущий независимый видеосервис сможет использовать тот же нейтральный медиабриф через отдельный пакет или API, не меняя Telegram-конвейер.

## Правила зависимостей

```text
cli / jobs → application → domain
adapters → application + domain
infrastructure → application + domain
domain → только стандартная библиотека и собственные модули domain
```

`application` не импортирует конкретные клиенты HTTP, модели SQLAlchemy или команды systemd. Он получает их через порты. `adapters` и `infrastructure` не вызывают друг друга напрямую: сборка зависимостей происходит в `bootstrap.py`.

Порт появляется на внешней границе работающего сценария, а не «на вырост». Одноразовая обёртка сценария, параметр окружения для неизменяемого имени unit'а и отдельный сервис без второго потребителя не создаются.

## Ворота качества

Каждая волна выполняется одним последовательным TDD-циклом: тест на конкретное правило сначала должен падать по ожидаемой причине, затем минимальный код делает его зелёным. До следующей волны обязателен свежий reviewer Terra 5.6 с уровнем рассуждений high:

1. сначала он проверяет сами тесты и временно вносит критичные мутации правила; каждая мутация обязана сделать тест красным;
2. затем он проверяет лаконичность и корректность кода;
3. только после устранения замечаний и полной проверки начинается следующая волна.

Интеграционные тесты PostgreSQL запускаются на отдельной `TEST_DATABASE_URL` и не могут считаться пройденными при `skip` в обязательной проверке волны.

## Целевая карта каталогов

```text
Postify/
├── pyproject.toml
├── uv.lock
├── .env.example
├── alembic.ini
├── migrations/
├── deploy/systemd/
├── scripts/
├── src/postify/
│   ├── config.py
│   ├── bootstrap.py
│   ├── cli.py
│   ├── domain/
│   │   ├── candidates/
│   │   ├── content/
│   │   ├── publishing/
│   │   ├── farms/
│   │   └── shared/
│   ├── application/
│   │   ├── ports/
│   │   ├── ingestion/
│   │   ├── selection/
│   │   ├── content_creation/
│   │   ├── publication/
│   │   └── jobs/
│   ├── adapters/
│   │   ├── sources/
│   │   ├── publishers/
│   │   ├── generators/
│   │   └── media/
│   └── infrastructure/
│       ├── database/
│       ├── repositories/
│       ├── observability/
│       └── systemd.py
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

Это целевая карта, а не список файлов для немедленного создания. Каталоги и файлы появляются только вместе со сценарием, который их использует.

## Волны реализации

### Волна 1 — техническая основа и импорт HN Algolia

Цель: команда `postify run-once` получает кандидатов HN Algolia, сохраняет их в PostgreSQL и не создаёт дубликаты. CLI управляет timer, активной задачей и PostgreSQL-unit из конфигурации.

Создаются следующие файлы:

```text
pyproject.toml
.env.example
alembic.ini
migrations/env.py
migrations/versions/*_create_candidates.py
deploy/systemd/postify-run-once.service
deploy/systemd/postify-run-once.timer
scripts/install-systemd.sh
src/postify/__init__.py
src/postify/config.py
src/postify/bootstrap.py
src/postify/cli.py
src/postify/domain/candidates/models.py
src/postify/application/ports/candidate_source.py
src/postify/application/ports/candidate_repository.py
src/postify/application/ingestion/import_candidates.py
src/postify/adapters/sources/hn_algolia.py
src/postify/infrastructure/database/engine.py
src/postify/infrastructure/database/models.py
src/postify/infrastructure/repositories/sqlalchemy_candidates.py
src/postify/infrastructure/systemd.py
tests/unit/domain/candidates/test_models.py
tests/unit/config/test_settings.py
tests/unit/application/ingestion/test_import_candidates.py
tests/unit/adapters/sources/test_hn_algolia.py
tests/unit/infrastructure/test_systemd.py
tests/integration/conftest.py
tests/integration/test_migrations.py
tests/integration/infrastructure/test_sqlalchemy_candidates.py
tests/integration/test_import_component.py
tests/e2e/test_cli_run_once.py
tests/e2e/test_systemd_installer.py
```

Волна создаёт `run-once`, `start`, `stop` и базовый `status`: он показывает PostgreSQL-unit, доступность БД, timer, последнее/следующее срабатывание, число кандидатов и результат задачи. Unit'ы работают в system-режиме; установщик получает абсолютные пути к окружению и `EnvironmentFile`, пользователя службы, `POSTGRESQL_SYSTEMD_UNIT` и режим владения. Этот unit должен быть выделен для Postify либо оператор явно разрешает остановку общего экземпляра. Расширенные счётчики очереди и публикаций, а также долговечная последняя ошибка добавляются в волне 5 вместе с их таблицами, а не имитируются заранее.

Префикс имени каждой миграции создаёт Alembic; в списках далее фиксируется неизменяемый смысловой суффикс файла.

### Волна 2 — отбор и журнал решений

Цель: дешёвые правила оценивают кандидата, фиксируют причину решения и сохраняют резерв кандидатов.

Новые файлы:

```text
migrations/versions/*_add_candidate_decisions.py
src/postify/domain/candidates/selection.py
src/postify/domain/candidates/statuses.py
src/postify/application/ports/decision_repository.py
src/postify/application/selection/select_candidates.py
src/postify/infrastructure/repositories/sqlalchemy_decisions.py
tests/unit/domain/candidates/test_selection.py
tests/unit/application/selection/test_select_candidates.py
tests/integration/infrastructure/test_sqlalchemy_decisions.py
```

### Волна 3 — контентный и медиабриф

Цель: лидирующий кандидат превращается в нейтральный контентный пакет с текстом, ссылкой при необходимости и сведениями о визуале. Этот пакет не является Telegram-сообщением и пригоден для будущего видео.

Точный список файлов и контрактов фиксирует отдельный план только после выбора провайдера, выдачи ключа и согласования политики хранения исходных материалов и прав на визуал. До этого не создаются конкретный адаптер генератора, адаптер визуала, их конфигурация и тестовые заготовки. Сценарий должен оставаться проверяемым подставным генератором.

### Волна 4 — Telegram-очередь и автопостинг

Цель: контентные пакеты занимают слоты фермы, публикуются без дублей и сохраняют результат каждой попытки.

Точный список файлов и контрактов фиксирует отдельный план после получения токена, идентификатора чата и правила трёх слотов. До этого не создаются Telegram-адаптер, очередь публикаций и пустые порты.

### Волна 5 — наблюдаемость и расширенный статус

Цель: `postify status` показывает результаты последнего запуска, число кандидатов, очередь, публикации и последнюю ошибку.

Новые файлы:

```text
migrations/versions/*_add_run_logs.py
src/postify/domain/shared/errors.py
src/postify/application/ports/run_log_repository.py
src/postify/application/jobs/get_status.py
src/postify/infrastructure/observability/run_logs.py
src/postify/infrastructure/repositories/sqlalchemy_run_logs.py
tests/unit/application/jobs/test_get_status.py
tests/integration/infrastructure/test_sqlalchemy_run_logs.py
tests/e2e/test_cli_status.py
```

## Будущий видеосервис

Когда появится самостоятельный видеосервис, для него создаётся отдельный пакет и отдельные systemd-unit'ы. Он получает контентный/медиабриф из волны 3 через явно определённый контракт. До начала этой волны не создаются ни каталог видеосервиса, ни его адаптеры, ни пустые интерфейсы.

## Принцип дополнения архитектуры

Каждая будущая спецификация волны обязана содержать два раздела:

1. «Создаваемые файлы» — точный список новых файлов этой волны.
2. «Изменяемые файлы» — существующие файлы, которые меняются, с кратким назначением изменения.

Файл создаётся только если он нужен работающему сценарию или тесту текущей волны. Не создаются пустые каталоги, заготовки адаптеров будущих интеграций и преждевременные абстракции.

## Последовательность планов и зависимости

Создаётся и проходит ревью один план за раз:

1. `2026-08-01-wave-1-hn-import.md` — импорт и идемпотентное хранение;
2. `YYYY-MM-DD-wave-2-selection-decisions.md` — отбор и журнал решений;
3. `YYYY-MM-DD-wave-3-content-package.md` — только после выбора генератора, ключа и политики прав на визуал;
4. `YYYY-MM-DD-wave-4-telegram-publication.md` — только после получения токена, идентификатора чата и правила трёх слотов;
5. `YYYY-MM-DD-wave-5-observability-status.md` — статус и долговечный журнал по уже созданным сущностям.

```text
волна 1 → волна 2 → волна 3 → волна 4 → волна 5
                 ├→ подготовка решения о генераторе и правах
                 └→ подготовка решения о Telegram и расписании
```

Две подготовительные ветки не меняют код и могут идти параллельно после волны 2. Реализация волн остаётся последовательной: одна БД, общие миграции и обязательные ворота ревью делают параллельных implementer-агентов внутри волны источником конфликтов.
