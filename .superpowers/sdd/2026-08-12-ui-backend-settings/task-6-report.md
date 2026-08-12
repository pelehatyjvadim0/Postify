# Task 6 — Query-сервис рабочих экранов

## Изменённые файлы

- `src/postify/application/dashboard/models.py` — неизменяемые DTO overview, materials, packages, queue, publications и operations.
- `src/postify/application/ports/dashboard_repository.py` — read-only порт с явным `project_id` во всех запросах.
- `src/postify/application/dashboard/show_dashboard.py` — тонкий action для overview.
- `src/postify/infrastructure/repositories/sqlalchemy_dashboard.py` — PostgreSQL read-модели, project isolation, пагинация и repeatable-read/read-only overview.
- `tests/unit/application/dashboard/test_show_dashboard.py` — unit-тест проксирования границ проекта и дня.
- `tests/integration/infrastructure/test_sqlalchemy_dashboard.py` — PostgreSQL integration-тесты отсутствия fake score, project isolation, foreign lookup, forecast slot, persisted fields и pagination bounds.

## RED

До production-кода выполнена команда:

```bash
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test uv run pytest -q tests/integration/infrastructure/test_sqlalchemy_dashboard.py tests/unit/application/dashboard/test_show_dashboard.py
```

Результат: `8 failed`. После исправления test fixture (явный `id=2` для второго проекта, потому что исходная migration не продвигает sequence после вставки default project) RED был вызван отсутствием новых модулей: `ModuleNotFoundError: No module named 'postify.infrastructure.repositories.sqlalchemy_dashboard'` и `No module named 'postify.application.dashboard'`.

## GREEN

После минимальной реализации выполнено:

```bash
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test uv run pytest -q tests/unit/application/dashboard tests/integration/infrastructure/test_sqlalchemy_dashboard.py
```

Результат: `8 passed in 1.06s`.

Статические проверки:

```bash
uv run ruff check src/postify/application/dashboard/models.py src/postify/application/dashboard/show_dashboard.py src/postify/application/ports/dashboard_repository.py src/postify/infrastructure/repositories/sqlalchemy_dashboard.py tests/unit/application/dashboard/test_show_dashboard.py tests/integration/infrastructure/test_sqlalchemy_dashboard.py
git diff --check
```

Результаты: `All checks passed!`; `git diff --check` без вывода (успех).

## Примечания

- Forecast создаётся только для approved package без сохранённой delivery; его `delivery_id` остаётся `None`.
- Queue использует три первых строки `schedule.slots` первого включённого route проекта; подтверждённые доставки отбираются только по этому route и локальному дню проекта.

## Исправление review (legacy delivery)

Добавлен integration regression-тест через фактический `SqlAlchemyDeliveryRepository.reserve_next()` и `confirm_published()`. Этот путь сохраняет delivery с `route_id=NULL`.

RED:

```bash
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test uv run pytest -q tests/integration/infrastructure/test_sqlalchemy_dashboard.py::test_queue_confirms_legacy_delivery_created_by_delivery_repository
```

Результат: `1 failed`; первый slot имел `assignment_kind == 'empty'` вместо `'confirmed'`.

GREEN:

```bash
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test uv run pytest -q tests/unit/application/dashboard tests/integration/infrastructure/test_sqlalchemy_dashboard.py
uv run ruff check src/postify/infrastructure/repositories/sqlalchemy_dashboard.py tests/integration/infrastructure/test_sqlalchemy_dashboard.py
git diff --check
```

Результат: `9 passed in 1.26s`; `All checks passed!`; `git diff --check` без вывода (успех).

`queue()` включает persisted delivery с `route_id=NULL` только при ровно одном включённом route проекта. При нескольких route такая delivery остаётся не назначенной, чтобы не смешать неоднозначную legacy-запись между маршрутами.
