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

Цель: команда `postify run-once` получает кандидатов HN Algolia, сохраняет их в PostgreSQL и не создаёт дубликаты. CLI готовит основу для `start`, `status` и `stop`; systemd запускает задачу по timer.

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
src/postify/application/jobs/run_once.py
src/postify/adapters/sources/hn_algolia.py
src/postify/infrastructure/database/engine.py
src/postify/infrastructure/database/models.py
src/postify/infrastructure/repositories/sqlalchemy_candidates.py
src/postify/infrastructure/systemd.py
tests/unit/domain/candidates/test_models.py
tests/unit/application/ingestion/test_import_candidates.py
tests/unit/adapters/sources/test_hn_algolia.py
tests/integration/infrastructure/test_sqlalchemy_candidates.py
tests/e2e/test_cli_run_once.py
```

`postify start`, `postify status` и `postify stop` создаются в этой волне только в объёме проверки PostgreSQL и timer. Счётчики очереди, публикаций и последняя ошибка добавляются вместе с соответствующими таблицами, а не имитируются заранее.

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

Новые файлы:

```text
migrations/versions/*_add_content_packages.py
src/postify/domain/content/models.py
src/postify/application/ports/content_generator.py
src/postify/application/ports/media_provider.py
src/postify/application/content_creation/create_package.py
src/postify/adapters/generators/openrouter.py
src/postify/adapters/media/official_assets.py
src/postify/infrastructure/repositories/sqlalchemy_content_packages.py
tests/unit/application/content_creation/test_create_package.py
tests/unit/adapters/generators/test_openrouter.py
```

До выдачи ключа OpenRouter его адаптер не подключается в `bootstrap.py`; сценарий тестируется подставным генератором.

### Волна 4 — Telegram-очередь и автопостинг

Цель: контентные пакеты занимают слоты фермы, публикуются без дублей и сохраняют результат каждой попытки.

Новые файлы:

```text
migrations/versions/*_add_publications.py
src/postify/domain/publishing/models.py
src/postify/application/ports/publisher.py
src/postify/application/ports/publication_repository.py
src/postify/application/publication/schedule_publications.py
src/postify/application/publication/publish_ready.py
src/postify/adapters/publishers/telegram.py
src/postify/infrastructure/repositories/sqlalchemy_publications.py
tests/unit/application/publication/test_schedule_publications.py
tests/unit/application/publication/test_publish_ready.py
tests/unit/adapters/publishers/test_telegram.py
tests/integration/infrastructure/test_sqlalchemy_publications.py
```

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
