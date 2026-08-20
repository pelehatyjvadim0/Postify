# Рабочий UI и настройки проекта — план реализации

> **Для agentic workers:** REQUIRED SUB-SKILL: использовать
> `superpowers:subagent-driven-development` (рекомендуется) или
> `superpowers:executing-plans` и выполнять задачи по порядку. Каждый пункт
> отмечается checkbox.

**Цель:** Подключить утверждённый UI Postify к существующему backend, добавить
универсальные настройки проекта, источников, форматов, CTA, каналов и маршрутов.

**Архитектура:** PostgreSQL хранит проектную конфигурацию и project scope.
Application actions продолжают владеть изменениями, отдельный query-сервис
готовит данные экранов, FastAPI предоставляет JSON API и пакетные статические
ресурсы. Источники и каналы создаются через реестры провайдеров.

**Стек:** Python 3.12, SQLAlchemy, PostgreSQL 16, Alembic, Pydantic, FastAPI,
Uvicorn, Cryptography/Fernet, HTML/CSS, ES modules, Playwright, Pytest.

## Общие ограничения

- Первый релиз однопользовательский и содержит один активный проект.
- Все рабочие сущности изолированы по `project_id`.
- Общие модели не содержат HN- или Telegram-специфичных полей.
- Рабочие провайдеры первой версии: источник `hn_algolia`, канал `telegram`.
- Токен канала не возвращается через API и не попадает в ошибки.
- UI не использует демонстрационный fallback.
- Аналитика и генерация видео не реализуются.
- Сервер по умолчанию слушает `127.0.0.1`.
- Документация пишется кратко и по-русски.
- Push и merge не выполняются.

---

### Задача 1: Домен конфигурации и реестры провайдеров

**Файлы:**
- Создать: `src/postify/domain/projects/models.py`
- Создать: `src/postify/domain/projects/__init__.py`
- Создать: `src/postify/application/ports/project_repository.py`
- Создать: `src/postify/application/projects/manage_project.py`
- Создать: `src/postify/adapters/sources/registry.py`
- Создать: `src/postify/adapters/channels/registry.py`
- Тест: `tests/unit/domain/projects/test_models.py`
- Тест: `tests/unit/adapters/test_provider_registries.py`

**Интерфейсы:**
- Создаёт `ContentProject`, `SourceConnection`, `ContentFormat`,
  `CallToAction`, `ChannelConnection`, `PublicationRoute`, `ProjectConfiguration`.
- Создаёт `SourceProviderRegistry.validate(provider, configuration)` и
  `ChannelProviderRegistry.validate(provider, configuration)`.
- Создаёт `ManageProject.get(project_id)` и
  `ManageProject.update(project_id, section, payload, now)`.

- [ ] **Шаг 1: написать RED-тесты моделей**

```python
def test_project_configuration_rejects_invalid_quota_share():
    with pytest.raises(ValueError, match="100"):
        valid_configuration(fresh_share=80, reserve_share=10)

def test_route_references_format_channel_and_optional_cta():
    route = PublicationRoute(1, 7, 8, 9, True)
    assert (route.project_id, route.format_id, route.channel_id, route.cta_id) == (1, 7, 8, 9)
```

- [ ] **Шаг 2: проверить RED**

Запуск: `uv run pytest -q tests/unit/domain/projects tests/unit/adapters/test_provider_registries.py`

Ожидание: импорт `postify.domain.projects` завершается ошибкой.

- [ ] **Шаг 3: реализовать модели и строгую валидацию**

`ProjectConfiguration` проверяет непустые тему, язык и аудиторию, положительные
лимиты, `package_limit <= analysis_limit`, доли ровно 100, положительные
freshness/timeout/byte limits и timezone через `ZoneInfo`. Реестр источников
принимает `hn_algolia` с `query`, `tags`, `hits`; реестр каналов принимает
`telegram` с непустым `chat_id`. Неизвестный provider возвращает доменную
ошибку `UnsupportedProvider`.

- [ ] **Шаг 4: запустить unit-тесты**

Запуск: `uv run pytest -q tests/unit/domain/projects tests/unit/adapters/test_provider_registries.py`

Ожидание: PASS.

- [ ] **Шаг 5: коммит**

```bash
git add src/postify/domain/projects src/postify/application/ports/project_repository.py src/postify/application/projects src/postify/adapters/sources/registry.py src/postify/adapters/channels tests/unit/domain/projects tests/unit/adapters/test_provider_registries.py
git commit -m "Добавлена модель настроек проекта"
```

### Задача 2: Проектная схема PostgreSQL и миграция существующих данных

**Файлы:**
- Создать: `src/postify/infrastructure/database/migrations/versions/20260812_06_add_projects_and_connections.py`
- Изменить: `src/postify/infrastructure/database/models.py`
- Тест: `tests/integration/test_migrations.py`
- Тест: `tests/integration/infrastructure/test_sqlalchemy_projects.py`

**Интерфейсы:**
- Создаёт таблицы `content_projects`, `source_connections`, `content_formats`,
  `calls_to_action`, `channel_connections`, `publication_routes`.
- Переименовывает `telegram_deliveries`/`telegram_delivery_attempts` в
  `deliveries`/`delivery_attempts`.
- Добавляет обязательный `project_id` к рабочим таблицам после backfill.

- [ ] **Шаг 1: написать RED migration-тест**

```python
def test_wave6_migrates_existing_rows_into_default_project(connection):
    migrate_to("20260809_05")
    seed_wave5_graph(connection)
    migrate_to("20260812_06")
    assert connection.execute(text("select count(*) from content_projects")).scalar_one() == 1
    assert connection.execute(text("select project_id from candidates")).scalar_one() == 1
    assert table_names(connection) >= {"deliveries", "delivery_attempts", "source_connections"}
```

- [ ] **Шаг 2: проверить RED**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/integration/test_migrations.py -k wave6`

Ожидание: revision `20260812_06` не существует.

- [ ] **Шаг 3: реализовать миграцию**

Миграция создаёт проект ID 1 из нейтральных значений, переносит существующие
строки, создаёт project-scoped unique constraints, добавляет snapshots JSONB к
пакетам и route/channel ссылки к доставкам. Downgrade восстанавливает исходные
имена таблиц и ограничения без потери старых полей Wave 1–5.

- [ ] **Шаг 4: реализовать ORM-модели конфигурации**

Добавить SQLAlchemy-модели с timezone-aware timestamps, JSONB configuration,
уникальностью `(project_id, name)` и check constraints для provider/enabled.

- [ ] **Шаг 5: запустить migration и repository tests**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/integration/test_migrations.py tests/integration/infrastructure/test_sqlalchemy_projects.py`

Ожидание: PASS.

- [ ] **Шаг 6: коммит**

```bash
git add src/postify/infrastructure/database tests/integration/test_migrations.py tests/integration/infrastructure/test_sqlalchemy_projects.py
git commit -m "Добавлено хранение проектов и подключений"
```

### Задача 3: Репозиторий проекта, bootstrap из окружения и секреты

**Файлы:**
- Изменить: `pyproject.toml`
- Изменить: `uv.lock`
- Изменить: `src/postify/config.py`
- Создать: `src/postify/infrastructure/security/secrets.py`
- Создать: `src/postify/infrastructure/repositories/sqlalchemy_projects.py`
- Создать: `src/postify/application/projects/bootstrap_project.py`
- Тест: `tests/unit/infrastructure/test_secrets.py`
- Тест: `tests/unit/application/projects/test_bootstrap_project.py`
- Тест: `tests/integration/infrastructure/test_sqlalchemy_projects.py`

**Интерфейсы:**
- `SecretCipher.encrypt(value: str) -> str` и `decrypt(value: str) -> str`.
- `SqlAlchemyProjectRepository` реализует CRUD и project-scoped lookup.
- `BootstrapProject.execute(settings, telegram_settings | None)` создаёт только
  отсутствующий проект и исходные подключения.

- [ ] **Шаг 1: написать RED-тесты секрета и bootstrap**

```python
def test_secret_cipher_round_trip_without_plaintext():
    cipher = SecretCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt("123:token")
    assert encrypted != "123:token"
    assert cipher.decrypt(encrypted) == "123:token"

def test_bootstrap_is_idempotent(repository, settings):
    action = BootstrapProject(repository, source_registry, channel_registry, cipher=None)
    first = action.execute(settings, None)
    second = action.execute(settings, None)
    assert first.id == second.id
    assert repository.count_projects() == 1
```

- [ ] **Шаг 2: проверить RED**

Запуск: `uv run pytest -q tests/unit/infrastructure/test_secrets.py tests/unit/application/projects/test_bootstrap_project.py`

Ожидание: классы отсутствуют.

- [ ] **Шаг 3: добавить зависимости и реализацию**

Добавить `fastapi`, `uvicorn` и `cryptography`. В `Settings` добавить
необязательный `postify_secret_key: SecretStr | None`; отсутствие ключа не
мешает read-only работе. Bootstrap переносит продуктовые `.env`-значения в
проект, источник, формат B, CTA и Telegram-канал, если credentials доступны.

- [ ] **Шаг 4: запустить тесты**

Запуск: `uv run pytest -q tests/unit/infrastructure/test_secrets.py tests/unit/application/projects/test_bootstrap_project.py tests/integration/infrastructure/test_sqlalchemy_projects.py`

Ожидание: PASS.

- [ ] **Шаг 5: коммит**

```bash
git add pyproject.toml uv.lock src/postify/config.py src/postify/infrastructure/security src/postify/infrastructure/repositories/sqlalchemy_projects.py src/postify/application/projects tests/unit/infrastructure/test_secrets.py tests/unit/application/projects tests/integration/infrastructure/test_sqlalchemy_projects.py
git commit -m "Добавлена безопасная конфигурация проекта"
```

### Задача 4: Project scope в существующем конвейере

**Файлы:**
- Изменить: application ports и actions в `src/postify/application/`
- Изменить: репозитории в `src/postify/infrastructure/repositories/`
- Изменить: `src/postify/bootstrap.py`
- Изменить: соответствующие unit/integration/e2e тесты Wave 1–5

**Интерфейсы:**
- Каждый action принимает `project_id: int` через конструктор.
- Каждый repository query и mutation ограничивается `project_id`.
- `open_run_once(settings, project_id=1)` загружает актуальную конфигурацию.

- [ ] **Шаг 1: добавить RED-тесты изоляции**

```python
def test_candidate_import_deduplicates_inside_project_not_globally(repository):
    assert repository.save_new(1, [candidate]) == 1
    assert repository.save_new(2, [candidate]) == 1
    assert repository.save_new(1, [candidate]) == 0

def test_review_cannot_open_package_from_another_project(review):
    with pytest.raises(LookupError):
        review.for_project(1).show(package_from_project_2)
```

- [ ] **Шаг 2: проверить RED на каждом repository boundary**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/integration/infrastructure`

Ожидание: новые isolation-тесты FAIL.

- [ ] **Шаг 3: протянуть project_id через actions и repositories**

Обновить import, selection, content, delivery, observability и operation runs.
Запретить lookup только по ID. Сохранить совместимый default `project_id=1` в
CLI factories, чтобы прежние команды продолжили работать.

- [ ] **Шаг 4: загрузить настройки проекта в bootstrap**

`open_run_once` строит источник через registry, selection profile и content
limits из сохранённого проекта. `open_publish_once` выбирает активный маршрут,
расшифровывает secret и строит channel adapter. Codex analyzer получает
`GenerationBrief(topic, language, audience, format_instructions, cta)`.

- [ ] **Шаг 5: запустить retained gates**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/unit tests/integration tests/e2e`

Ожидание: PASS.

- [ ] **Шаг 6: коммит**

```bash
git add src/postify tests/unit tests/integration tests/e2e
git commit -m "Конвейер изолирован по проектам"
```

### Задача 5: Несколько источников и универсальная доставка

**Файлы:**
- Создать: `src/postify/application/ingestion/import_project_sources.py`
- Создать: `src/postify/application/delivery/publish_route.py`
- Изменить: `src/postify/adapters/ai/codex_content_analyzer.py`
- Переименовать: `src/postify/infrastructure/repositories/sqlalchemy_delivery.py` → `sqlalchemy_deliveries.py`
- Тест: `tests/unit/application/ingestion/test_import_project_sources.py`
- Тест: `tests/unit/application/delivery/test_publish_route.py`
- Изменить: adapter/repository tests доставки

**Интерфейсы:**
- `ImportProjectSources.execute() -> ProjectImportResult` содержит итог и
  результат каждого source connection.
- `PublishRoute.execute() -> PublishContentResult` выбирает route и channel.
- `GenerationBrief` является независимым от платформы DTO.

- [ ] **Шаг 1: написать RED-тест частичного успеха источников**

```python
def test_import_continues_after_one_source_failure():
    result = action_with(failing_source, successful_source).execute()
    assert result.created == 2
    assert result.sources[0].outcome == "failed"
    assert result.sources[1].outcome == "completed"
```

- [ ] **Шаг 2: написать RED-тест выбора канала через route**

```python
def test_publish_uses_channel_selected_by_route():
    result = action.execute()
    assert result.outcome == "published"
    telegram.publish.assert_called_once()
    assert saved_delivery.channel_id == route.channel_id
```

- [ ] **Шаг 3: реализовать orchestration и registries**

Ошибки отдельных источников входят в operation details. Общий run считается
успешным, если хотя бы один включённый источник завершился; при полном отказе
action поднимает нормализованную ошибку. Delivery repository работает с общими
таблицами, а Telegram остаётся adapter implementation.

- [ ] **Шаг 4: передать GenerationBrief в prompt**

Prompt явно включает тему, язык, аудиторию, структуру формата и CTA. Source URL
добавляется только при разрешённом CTA-режиме и проходит существующую проверку.

- [ ] **Шаг 5: запустить scoped-тесты**

Запуск: `uv run pytest -q tests/unit/application/ingestion tests/unit/application/delivery tests/unit/adapters/ai tests/unit/adapters/telegram`

Ожидание: PASS.

- [ ] **Шаг 6: коммит**

```bash
git add src/postify/application/ingestion src/postify/application/delivery src/postify/adapters src/postify/infrastructure/repositories tests/unit/application tests/unit/adapters
git commit -m "Источники и каналы сделаны подключаемыми"
```

### Задача 6: Query-сервис для семи экранов

**Файлы:**
- Создать: `src/postify/application/dashboard/models.py`
- Создать: `src/postify/application/dashboard/show_dashboard.py`
- Создать: `src/postify/application/ports/dashboard_repository.py`
- Создать: `src/postify/infrastructure/repositories/sqlalchemy_dashboard.py`
- Тест: `tests/unit/application/dashboard/test_show_dashboard.py`
- Тест: `tests/integration/infrastructure/test_sqlalchemy_dashboard.py`

**Интерфейсы:**
- `DashboardRepository.overview/materials/packages/queue/publications/operations`.
- Методы возвращают immutable DTO; ни один метод не выполняет mutation.

- [ ] **Шаг 1: написать RED-тесты DTO и project scope**

```python
def test_materials_return_persisted_decision_without_fake_score(repository):
    item = repository.materials(project_id=1, status="selected", query=None)[0]
    assert item.reason == "eligible_for_ai"
    assert not hasattr(item, "score")

def test_queue_marks_unreserved_slots_as_forecast(repository):
    queue = repository.queue(project_id=1, day=local_day)
    assert queue.slots[0].assignment_kind in {"confirmed", "forecast", "empty"}
```

- [ ] **Шаг 2: проверить RED**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/unit/application/dashboard tests/integration/infrastructure/test_sqlalchemy_dashboard.py`

Ожидание: модули dashboard отсутствуют.

- [ ] **Шаг 3: реализовать read model**

Использовать bounded SQL-запросы, фильтры, limit/offset и один read-only
repeatable-read snapshot для overview. Детали доставок включают attempts;
операции включают duration и безопасные codes.

- [ ] **Шаг 4: запустить тесты**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/unit/application/dashboard tests/integration/infrastructure/test_sqlalchemy_dashboard.py`

Ожидание: PASS.

- [ ] **Шаг 5: коммит**

```bash
git add src/postify/application/dashboard src/postify/application/ports/dashboard_repository.py src/postify/infrastructure/repositories/sqlalchemy_dashboard.py tests/unit/application/dashboard tests/integration/infrastructure/test_sqlalchemy_dashboard.py
git commit -m "Добавлены данные рабочих экранов"
```

### Задача 7: FastAPI, схемы и обработка ошибок

**Файлы:**
- Создать: `src/postify/web/app.py`
- Создать: `src/postify/web/dependencies.py`
- Создать: `src/postify/web/schemas.py`
- Создать: `src/postify/web/errors.py`
- Создать: `src/postify/web/routes/`
- Изменить: `src/postify/cli.py`
- Тест: `tests/unit/web/test_api.py`
- Тест: `tests/integration/test_web_component.py`

**Интерфейсы:**
- `create_app(container: WebContainer | None = None) -> FastAPI`.
- `postify ui --host 127.0.0.1 --port 8000`.
- API маршруты точно соответствуют дизайн-спецификации.

- [ ] **Шаг 1: написать RED API-тесты**

```python
def test_bootstrap_returns_active_project(client):
    response = client.get("/api/v1/bootstrap")
    assert response.status_code == 200
    assert response.json()["activeProject"]["id"] == 1

def test_channel_response_never_contains_secret(client):
    payload = client.get("/api/v1/projects/1/settings").json()
    assert "token" not in json.dumps(payload).casefold()
    assert payload["channels"][0]["secretConfigured"] is True
```

- [ ] **Шаг 2: проверить RED**

Запуск: `uv run pytest -q tests/unit/web/test_api.py`

Ожидание: `postify.web` отсутствует.

- [ ] **Шаг 3: реализовать API и schemas**

Все request schemas запрещают extra fields. Not found возвращает 404,
конфликт перехода — 409, validation — 422, занятая операция — 409,
инфраструктурная ошибка — безопасный 503 с `code` и `requestId`.

- [ ] **Шаг 4: реализовать команды операций**

`run-once` ставится в bounded executor и отвечает 202. `publish-once`,
approve/reject и settings mutations выполняются через application actions.
Reject принимает обязательную причину длиной 3–500 символов.

- [ ] **Шаг 5: добавить CLI-команду и static mount**

Команда создаёт app factory и запускает Uvicorn. `/` отдаёт пакетный
`static/index.html`; `/media/packages/{id}` читает только media пакета проекта.

- [ ] **Шаг 6: запустить API/component tests**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/unit/web tests/integration/test_web_component.py`

Ожидание: PASS.

- [ ] **Шаг 7: коммит**

```bash
git add src/postify/web src/postify/cli.py tests/unit/web tests/integration/test_web_component.py
git commit -m "Добавлен HTTP API Postify"
```

### Задача 8: Пакетный frontend и реальные данные шести экранов

**Файлы:**
- Создать: `src/postify/web/static/index.html`
- Создать: `src/postify/web/static/styles.css`
- Создать: `src/postify/web/static/app.js`
- Создать: `src/postify/web/static/api.js`
- Создать: `src/postify/web/static/screens.js`
- Изменить: `pyproject.toml`
- Изменить: `tests/ui_mockup/test_static_contract.py`
- Изменить: `tests/ui_mockup/test_browser_flows.py`

**Интерфейсы:**
- `api.js`: `request(path, options)`, typed-by-contract resource functions.
- `app.js`: router, loading/error state, event delegation, resource refresh.
- `screens.js`: pure render functions без сетевых вызовов.

- [ ] **Шаг 1: заменить offline-контракт RED-тестом API frontend**

```python
def test_frontend_uses_api_without_demo_state():
    script = STATIC.joinpath("app.js").read_text()
    assert "INITIAL_STATE" not in script
    assert "Демо-данные" not in script
    assert 'from "./api.js"' in script
```

- [ ] **Шаг 2: добавить browser RED для loading/error/real data**

Playwright перехватывает `/api/v1/**`, возвращает fixtures с ID `9001` и
проверяет, что overview, materials, review, queue, publications и journal
показывают эти значения. Отдельный тест возвращает 503 и проверяет кнопку
«Повторить» без появления демо-карточек.

- [ ] **Шаг 3: проверить RED**

Запуск: `uv run pytest -q tests/ui_mockup`

Ожидание: frontend всё ещё содержит `INITIAL_STATE`.

- [ ] **Шаг 4: перенести утверждённую оболочку в package static**

Сохранить визуальный язык, логотип и адаптивность. Удалить demo reset и
disabled «Настройки». Реальные значения форматируются на клиенте, доменные
codes отображаются русским словарём.

- [ ] **Шаг 5: подключить шесть экранов к API**

Каждый маршрут загружает только свои данные, отменяет устаревший запрос через
`AbortController`, показывает skeleton/empty/error. Approve/reject и запуск
операций перечитывают связанные ресурсы после успешного ответа.

- [ ] **Шаг 6: запустить UI-тесты**

Запуск: `uv run pytest -q tests/ui_mockup`

Ожидание: PASS.

- [ ] **Шаг 7: коммит**

```bash
git add src/postify/web/static pyproject.toml tests/ui_mockup
git commit -m "Рабочие экраны подключены к backend"
```

### Задача 9: Компактный экран настроек

**Файлы:**
- Создать: `src/postify/web/static/settings.js`
- Изменить: `src/postify/web/static/index.html`
- Изменить: `src/postify/web/static/styles.css`
- Изменить: `src/postify/web/static/app.js`
- Изменить: `src/postify/web/static/screens.js`
- Тест: `tests/ui_mockup/test_browser_flows.py`

**Интерфейсы:**
- `renderSettings(settings, providers)` создаёт восемь accordion-секций.
- `serializeSettingsSection(form)` возвращает JSON только выбранной секции.

- [ ] **Шаг 1: написать browser RED для всех секций**

```python
def test_settings_are_compact_editable_and_persisted(page, api):
    page.goto(f"{api}/#settings")
    assert page.locator("[data-settings-section]").count() == 8
    assert page.locator("[data-settings-section][open]").count() == 1
    page.get_by_role("button", name="Основное").click()
    page.get_by_label("Название проекта").fill("Новая редакция")
    page.get_by_role("button", name="Сохранить").click()
    assert api.last_put["name"] == "Новая редакция"
```

- [ ] **Шаг 2: добавить RED для источника, CTA и канала**

Проверить каталог provider, provider-specific поля, masked token, сохранение
пустого token без удаления, маршрут `format + channel + CTA`, три слота и
проверку суммы долей до запроса.

- [ ] **Шаг 3: реализовать экран**

Секции: Основное, Источники, Аудитория и отбор, Генерация и форматы, CTA,
Каналы и маршруты, Расписание, Дополнительно. В заголовке каждой секции есть
короткий итог. На mobile секция занимает всю ширину; sticky footer содержит
сохранение только при dirty state.

- [ ] **Шаг 4: реализовать доступность и feedback**

Accordion использует native `details`, ошибки связаны через `aria-describedby`,
секрет имеет show/hide, сохранение блокируется на время запроса, успешный ответ
обновляет summary и toast.

- [ ] **Шаг 5: запустить browser tests на трёх ширинах**

Запуск: `uv run pytest -q tests/ui_mockup/test_browser_flows.py`

Ожидание: PASS без horizontal overflow на 360, 768 и 1440.

- [ ] **Шаг 6: коммит**

```bash
git add src/postify/web/static tests/ui_mockup/test_browser_flows.py
git commit -m "Добавлены понятные настройки проекта"
```

### Задача 10: Планировщик из конфигурации проекта

**Файлы:**
- Создать: `src/postify/application/scheduling/project_scheduler.py`
- Создать: `src/postify/infrastructure/repositories/sqlalchemy_schedule.py`
- Изменить: `src/postify/web/app.py`
- Тест: `tests/unit/application/scheduling/test_project_scheduler.py`
- Тест: `tests/integration/infrastructure/test_sqlalchemy_schedule.py`

**Интерфейсы:**
- `ProjectScheduler.tick(now) -> tuple[ScheduledCommand, ...]`.
- Repository использует project-scoped PostgreSQL advisory lock и сохраняет
  последний созданный slot, чтобы повтор tick был идемпотентным.

- [ ] **Шаг 1: написать RED-тесты расписания**

```python
def test_tick_starts_each_due_slot_once():
    first = scheduler.tick(at("2026-08-12T09:00:00+03:00"))
    second = scheduler.tick(at("2026-08-12T09:00:30+03:00"))
    assert [item.kind for item in first] == ["publish_once"]
    assert second == ()
```

- [ ] **Шаг 2: написать integration RED advisory lock**

Два repository instance одновременно claim одного slot; ровно один получает
команду.

- [ ] **Шаг 3: реализовать scheduler**

Lifespan FastAPI запускает один polling task с коротким cancel-safe ожиданием.
Scheduler читает enabled source schedules и publication slots, создаёт команды
через тот же operation runner, что HTTP. При выключенном автопостинге publish
slots не запускаются.

- [ ] **Шаг 4: запустить тесты**

Запуск: `TEST_DATABASE_URL=... uv run pytest -q tests/unit/application/scheduling tests/integration/infrastructure/test_sqlalchemy_schedule.py`

Ожидание: PASS.

- [ ] **Шаг 5: коммит**

```bash
git add src/postify/application/scheduling src/postify/infrastructure/repositories/sqlalchemy_schedule.py src/postify/web/app.py tests/unit/application/scheduling tests/integration/infrastructure/test_sqlalchemy_schedule.py
git commit -m "Расписание подключено к настройкам проекта"
```

### Задача 11: Упаковка, документация и финальная проверка

**Файлы:**
- Изменить: `pyproject.toml`
- Изменить: `.env.example`
- Изменить: `README.md`
- Создать: `docs/development-loop/evidence/2026-08-12-wave-6-red.md`
- Создать: `docs/development-loop/evidence/2026-08-12-wave-6-review.md`
- Создать: `docs/development-loop/runs/2026-08-12-run-006.md`
- Тест: `tests/integration/test_import_component.py`
- Тест: `tests/e2e/test_cli_ui.py`

**Интерфейсы:**
- Wheel содержит `postify.web.static`.
- README описывает миграцию, secret key, `postify ui` и конфликт старых timers.

- [ ] **Шаг 1: написать RED wheel/e2e тест**

Собрать wheel, установить во временный venv, перейти в `/tmp`, запустить
`postify ui` на свободном порту, проверить `/`, `/static/styles.css` и
`/api/v1/bootstrap`.

- [ ] **Шаг 2: обновить package data и инструкции**

Добавить static assets в wheel. В `.env.example` добавить безопасный пример
ключа без рабочего секрета. README содержит команды migration и запуска,
ограничение single-owner и порядок отключения legacy timers.

- [ ] **Шаг 3: выполнить визуальную приёмку**

Снять desktop и mobile screenshots семи экранов на seeded PostgreSQL. Сверить
логотип, сетку, состояния загрузки/ошибок, формы настроек и отсутствие overflow.

- [ ] **Шаг 4: выполнить полный gate**

```bash
TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test uv run pytest -q
uv run python -m compileall -q src
git diff --check
```

Ожидание: все тесты PASS, compileall и diff-check завершаются кодом 0.

- [ ] **Шаг 5: записать Development Loop evidence**

Зафиксировать RED node IDs, проверенные мутации, полный gate, визуальные
разрешения, известные эксплуатационные ограничения и отсутствие push/merge.

- [ ] **Шаг 6: коммит**

```bash
git add pyproject.toml .env.example README.md docs/development-loop tests/integration/test_import_component.py tests/e2e/test_cli_ui.py
git commit -m "Завершено подключение рабочего UI Postify"
```
