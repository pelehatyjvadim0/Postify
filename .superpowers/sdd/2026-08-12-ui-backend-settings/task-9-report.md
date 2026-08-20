# Задача 9 — компактные настройки проекта

## RED

- `tests/ui_mockup/test_browser_flows.py`: `#settings` оставался
  placeholder без секций, реальных DTO и мутаций.
- `tests/unit/web/test_api.py`: `RouteRequest` отклонял
  `schedule` с 422, а явного endpoint удаления секрета не было.
- `tests/unit/application/projects/test_manage_resources.py`: application action
  не умел удалять только credential канала.
- `tests/unit/adapters/test_provider_registries.py`: bootstrap мог вернуть
  только коды провайдеров; generic frontend не знал поля и их типы.
- `tests/integration/infrastructure/test_sqlalchemy_projects.py`: отсутствовал
  repository boundary для удаления encrypted secret без удаления
  connection.
- `tests/ui_mockup/test_static_contract.py`: новый `settings.js` не
  входил в wheel package data.

RED evidence:

```text
uv run pytest -q tests/ui_mockup/test_browser_flows.py -k 'settings_render_eight' -x
# 1 failed: expected 8 settings sections, got 0

uv run pytest -q tests/unit/web/test_api.py::test_route_schedule_and_explicit_secret_removal_have_strict_commands tests/unit/application/projects/test_manage_resources.py::test_remove_channel_secret_is_an_explicit_action
# 2 failed: route schedule returned 422; remove_channel_secret отсутствовал

uv run pytest -q tests/unit/adapters/test_provider_registries.py::test_provider_catalog_describes_configuration_without_leaking_common_model_details
# 1 failed: SourceProviderRegistry.catalog отсутствовал

TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test uv run pytest -q tests/integration/infrastructure/test_sqlalchemy_projects.py::test_repository_removes_only_channel_secret_and_keeps_connection
# 1 failed: SqlAlchemyProjectRepository.remove_channel_secret отсутствовал

uv run pytest -q tests/ui_mockup/test_static_contract.py::test_wheel_configuration_includes_all_static_assets
# 1 failed: web/static/settings.js отсутствовал в package data
```

## GREEN

- Создан `settings.js` с pure `renderSettings(settings, providers)` и
  `serializeSettingsSection(form)`. Экран содержит ровно восемь native
  `details`-секций; browser-native одноимённая accordion-группа держит
  открытой ровно одну секцию.
- Формы покрывают project identity, policy/rules/markers, generation
  limits/shares/format description, source provider configuration/schedule, CTA,
  channel provider configuration/secret lifecycle, route references, ingestion
  schedule, three publication slots/autopublish и advanced limits.
- Sticky footer скрыт до dirty state конкретной формы.
  Busy state блокирует её кнопки; success перечитывает
  `GET /settings`, обновляет summary/project switcher и показывает toast.
  Ошибки показываются inline и связаны с control через
  `aria-describedby`.
- Клиент до request проверяет timezone, positive/bounded limits,
  package limit, сумму долей 100, HTTP(S) URL, три валидных
  уникальных слота и существование format/channel/CTA references.
- Source/channel configuration строится только по metadata
  provider registry, возвращаемой bootstrap. HN Algolia и Telegram
  остались опциями адаптеров, а не полями общей модели.
- Source/CTA/channel/route create/update/delete и channel check вызывают
  реальные Task 7 endpoints. Main/selection/generation/advanced используют
  только `main` или `configuration` request schema.
- GET токена не существует: input пуст, masked text — только
  placeholder. Пустой save опускает `token`, новое значение
  явно заменяет секрет, а отдельная команда
  `POST /channels/{id}/secret/remove` удаляет только encrypted
  credential. Show/hide активен только для нового value.
- `RouteRequest` принимает schedule с ровно тремя уникальными
  `HH:MM`; repository больше не затирает переданное расписание
  default-значением.
- Responsive-стили сохраняют «Тёплую студию»; каждая из
  восьми секций проверена без horizontal overflow на 360, 768 и
  1440 px.

## Изменённые границы

- Frontend: `src/postify/web/static/settings.js`, `app.js`, `api.js`,
  `screens.js`, `styles.css`.
- Thin HTTP/application/persistence: provider registry catalog,
  `PublicationScheduleRequest`, remove-secret endpoint/action/repository method.
- Packaging: `settings.js` добавлен в `pyproject.toml` package data.
- Tests: browser flows, static contract, web API/application/registry unit и
  PostgreSQL repository regression.

## Проверка

```text
uv run pytest -q tests/ui_mockup/test_browser_flows.py
# 56 passed in 19.35s

uv run pytest -q tests/ui_mockup/test_static_contract.py tests/unit/web tests/unit/application/projects/test_manage_resources.py tests/unit/adapters/test_provider_registries.py
# 23 passed in 0.61s

TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test uv run pytest -q tests/integration/infrastructure/test_sqlalchemy_projects.py tests/integration/test_web_component.py
# 5 passed in 1.13s

node --check src/postify/web/static/api.js
node --check src/postify/web/static/screens.js
node --check src/postify/web/static/settings.js
node --check src/postify/web/static/app.js
# exit 0

uv run ruff check <затронутые Python-файлы и тесты>
# All checks passed!

uv run python -m compileall -q src/postify/web src/postify/application/projects/manage_resources.py src/postify/infrastructure/repositories/sqlalchemy_projects.py
# exit 0

git diff --check
# без вывода

uv build --wheel --out-dir <temp>
unzip -l <wheel> | rg 'postify/web/static/(index.html|styles.css|app.js|api.js|screens.js|settings.js)'
# wheel собран; все 6 production assets включены
```

Browser-тесты и sync web/API-тесты запущены отдельными
pytest-процессами: session Playwright держит event loop, несовместимый
с существующим sync `ApiClient`, который вызывает `asyncio.run`.
Предписанные Task 9 команды также являются раздельными.

## Исправления после review

- resource settings рендерят 0, 1 и 2+ sources/CTA/channels/routes отдельными
  формами с собственными IDs и empty states;
- route editor использует реальные format/channel/CTA IDs, а stateful browser
  fake подтверждает create, update и delete именно созданного route ID;
- provider metadata передаёт HTTPS constraint; клиент блокирует HTTP source URL,
  пустой selection rules, пустые обязательные marker groups и дубли terms;
- `selection_policy_version` стал required editable persisted control;
- расписание переведено на один `PUT settings/schedule` с thin application
  action и одной repository transaction; PostgreSQL regression принудительно
  ломает commit и подтверждает rollback source и route schedule;
- общий `showSettingsError` связывает inline error через стабильный `id` и
  `aria-describedby` с формой и инициирующей кнопкой; покрыты source delete,
  token remove, channel check и route delete failures;
- route form хранит допустимые format/channel/CTA IDs из settings DTO в
  rendered metadata. Валидация сверяет payload с этими IDs, поэтому
  stale/tampered `<option>` блокируется до request.

### RED для stale route reference

```text
uv run pytest -q \
  tests/ui_mockup/test_browser_flows.py::test_route_references_are_checked_against_rendered_resource_ids_before_request -x
# 1 failed: ожидалась inline-ошибка «несуществующий», получена пустая строка
```

### GREEN после review fixes

```text
uv run pytest -q \
  tests/ui_mockup/test_browser_flows.py::test_route_references_are_checked_against_rendered_resource_ids_before_request -x
# 1 passed in 0.95s

uv run pytest -q tests/ui_mockup/test_browser_flows.py
# 70 passed in 26.58s

uv run pytest -q tests/ui_mockup/test_static_contract.py tests/unit/web \
  tests/unit/application/projects/test_manage_resources.py \
  tests/unit/application/projects/test_manage_schedule.py \
  tests/unit/adapters/test_provider_registries.py
# 25 passed in 0.76s

TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q tests/integration/infrastructure/test_sqlalchemy_projects.py \
  tests/integration/test_web_component.py
# 6 passed in 1.31s

node --check src/postify/web/static/api.js
node --check src/postify/web/static/screens.js
node --check src/postify/web/static/settings.js
node --check src/postify/web/static/app.js
# exit 0

uv run ruff check <12 затронутых Python-файлов review-fix>
# All checks passed!

uv run python -m compileall -q src
# exit 0

git diff --check
# без вывода

uv build --wheel --out-dir <temp>
unzip -Z1 <wheel> | rg \
  '^postify/web/static/(index.html|styles.css|app.js|api.js|screens.js|settings.js)$'
# wheel собран; все 6 production assets включены
```

Первая попытка PostgreSQL gate получила 6 setup errors из-за
`connection refused` на остановленной test DB. После запуска изолированного
PostgreSQL 16 тот же набор прошёл 6/6.

Полный `uv run ruff check src tests` отдельно нашёл 11 давних F401 в
`bootstrap_project.py`, `test_sqlalchemy_content.py` и
`test_process_content.py`. Эти файлы не изменены Task 9; исправление оставлено вне
scope. Scoped Ruff по всем затронутым Task 9 Python-файлам прошёл.

## Исправление validation parity после scoped re-review

- required text в provider configuration проверяется после trim и
  collapse internal whitespace; пробельное значение не доходит до API;
- provider URL должен содержать явный `${protocol}://`, непустую
  authority в исходной строке и host после разбора; `https:foo` блокируется;
- marker duplicates сравниваются после trim, collapse internal whitespace и
  lowercase, как на server domain boundary;
- все три границы покрыты browser tests с no-request assertion и
  `aria-describedby` для form и конкретного control.

### RED

```text
uv run pytest -q \
  tests/ui_mockup/test_browser_flows.py::test_required_provider_text_is_not_empty_after_normalization -x
# 1 failed: inline error пуст, mutation request не заблокирован

uv run pytest -q \
  tests/ui_mockup/test_browser_flows.py::test_https_provider_url_requires_explicit_authority_before_request \
  tests/ui_mockup/test_browser_flows.py::test_marker_duplicates_collapse_internal_whitespace_before_request
# 2 failed: обе inline errors пусты, mutation requests не заблокированы
```

### GREEN

```text
uv run pytest -q \
  tests/ui_mockup/test_browser_flows.py::test_required_provider_text_is_not_empty_after_normalization \
  tests/ui_mockup/test_browser_flows.py::test_https_provider_url_requires_explicit_authority_before_request \
  tests/ui_mockup/test_browser_flows.py::test_marker_duplicates_collapse_internal_whitespace_before_request
# 3 passed in 1.89s

uv run pytest -q tests/ui_mockup/test_browser_flows.py
# 73 passed in 28.46s

node --check src/postify/web/static/api.js
node --check src/postify/web/static/screens.js
node --check src/postify/web/static/settings.js
node --check src/postify/web/static/app.js
# exit 0

git diff --check
# без вывода
```

Production Python/API не изменялись, поэтому backend suites в этом
validation-only fix round не перезапускались.
