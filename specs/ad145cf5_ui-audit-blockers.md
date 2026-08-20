# План устранения блокеров аудита UI-тестов

## Цель и границы

Завершить только оставшиеся требования аудита: перевести весь legacy Playwright-набор на один observable/state-isolated harness, закрыть отсутствующие direct-ветви client/settings и недостающие browser/CRUD-сценарии. Не добавлять продуктовые UI-возможности, не менять UX, не удалять, не ослаблять, не `skip`/`xfail` существующие тесты и не выполнять commit, push или merge. Производственные UI-модули менять только если новый тест воспроизводимо обнаружит дефект уже заявленного поведения; сначала добавить падающую регрессию, затем внести минимальное исправление.

Сохранять все посторонние изменения грязного worktree. Каждую команду оценивать по exit status.

## Подтверждённое исходное состояние

- Последний review в `adws/adw_data/sessions/cd3e9f5b/context_handoff/review.md` зафиксировал 824 проходящих теста и 10/10 зелёных quality checks, но не одобрил три из шести исходных требований.
- `tests/ui_mockup/test_browser_flows.py` всё ещё содержит второй mutable `FIXTURES`, собственные `install_api`/`install_settings_api`, собственную `page` fixture, 39 вызовов `browser.new_page()` и три `wait_for_timeout(100)`.
- Канонические заготовки уже есть в `tests/ui_mockup/browser_support.py` и `tests/ui_mockup/conftest.py`, но shared fixture слишком беден для legacy flows, а settings fake пока не хранит CRUD-состояние.
- `tests/ui_mockup/test_client_logic.py` не проверяет native required, non-HTTP custom CTA, неверное количество schedule slots и `data-omit-empty`.
- `tests/ui_mockup/test_browser_coverage.py` уже проверяет unknown hash, material filters, stale response, часть empty states, Escape/focus, application-level channel-check failure и повторный topbar click. Не хватает package-detail GET failure, остальных способов закрыть dialog, control-ов в empty state, повторного package action и полного stateful CRUD для source/CTA/channel/route.
- Полный quality command уже правильно закреплён как `uv run pytest -p no:cacheprovider -q tests` в `adws/adw_modules/postify_quality.py`; `tests/unit/adws/test_quality_profile.py` защищает отсутствие excludes и четыре JS checks. Эти файлы не менять без обнаруженной регрессии.

## Файлы

- Изменить `tests/ui_mockup/browser_support.py`: сделать его единственным источником API fixture data, HTTP call records, accepted-operation поведения и stateful settings CRUD.
- Изменить `tests/ui_mockup/conftest.py`: оставить единственную observable фабрику страниц и предоставить основанную на ней default API page fixture.
- Изменить `tests/ui_mockup/test_browser_flows.py`: удалить legacy harness, перевести все страницы и данные на shared helpers, убрать fixed-time waits, сохранить все существующие проверки.
- Изменить `tests/ui_mockup/test_client_logic.py`: добавить отсутствующие direct serializer/validator branches и accessibility assertions.
- Изменить `tests/ui_mockup/test_browser_coverage.py`: добавить недостающие dialog, empty-control и duplicate-package-action сценарии.
- При необходимости перераспределить только тестовый CRUD-код между `test_browser_flows.py` и `test_browser_coverage.py`; не дублировать один сценарий в обоих файлах.
- Условно изменить `src/postify/web/static/app.js` или `src/postify/web/static/settings.js` только если соответствующий новый тест сначала докажет реальный дефект текущего публичного поведения.

## 1. Сделать browser harness единственным и полнофункциональным

### `tests/ui_mockup/browser_support.py`

1. Перенести сюда богатый fixture graph из начала `test_browser_flows.py`: bootstrap provider catalog, dashboard, material, package summary/detail, queue, publications, operations и полный settings graph. Сохранить `PIXEL_PNG` как immutable test asset. `FIXTURE_TEMPLATE` не экспортировать для мутаций; каждый тест получает только `fixture_payloads()` с `copy.deepcopy`.
2. Сохранить единый `HttpCall(method, path, body, headers)`. Во всех helpers путь должен включать query string, а lookup fixture — использовать путь без query. Перевести legacy assertions с tuple/dict request logs на `HttpCall`.
3. Расширить `install_api(...)`, не создавая второго installer-а:
   - GET возвращает переданную конкретному тесту deep-copied fixture map;
   - media package endpoint возвращает `PIXEL_PNG`;
   - обычные POST/PUT возвращают синхронный JSON, DELETE — 204;
   - background operations возвращают 202 с `operationRunId`, затем минимум один `running` poll и terminal `succeeded/completed`;
   - дать тесту локальный способ задать failure response или terminal outcome для конкретного path, чтобы package-detail failure и отрицательные operation flows не требовали глобального состояния;
   - все вызовы, включая GET/polls, записываются в переданный `calls`.
4. Полностью реализовать stateful `install_settings_api(...)` поверх локальной deep copy:
   - GET bootstrap и GET settings читают локальное состояние;
   - PUT `settings/main`, `settings/configuration`, `settings/schedule` обновляют только соответствующую секцию;
   - POST `sources|ctas|channels|routes` выдаёт новый ID (`max(existing)+1`), нормализует server-owned channel fields и возвращает созданную сущность;
   - PUT `/resource/{id}` обновляет именно созданную сущность и сохраняет ID;
   - DELETE удаляет её и возвращает 204;
   - channel secret remove и check меняют локальное состояние; injected `channel_check` по-прежнему позволяет вернуть HTTP 200 с `connectionStatus != "ok"` и `reason`;
   - `failures` продолжает моделировать transport failure до изменения состояния;
   - после каждой мутации следующий GET settings отражает новое состояние.
5. Не оставлять ни одного другого mutable fixture graph или общего route installer в UI tests.

### `tests/ui_mockup/conftest.py`

1. Сохранить module-scoped Playwright dispatcher: это уже исправляет конфликт его asyncio loop с последующими FastAPI-тестами.
2. Оставить `page_factory` единственным местом, где вызывается `browser.new_page()`. Для каждой созданной страницы до навигации:
   - подписаться на `console` с фильтром `message.type == "error"`;
   - подписаться на `pageerror`;
   - установить default timeout 3000 ms;
   - зарегистрировать страницу для закрытия и teardown assertion всех накопленных ошибок.
3. Добавить/перенести сюда `page` fixture только как тонкую композицию `page_factory(viewport={"width": 1440, "height": 1000})` + shared `install_api(page)`. Это не второй harness: она обязана использовать те же factory, fixture copy и installer.

## 2. Мигрировать весь legacy `test_browser_flows.py`

1. Удалить из файла imports/константы/код старого harness: `contextlib`, локальные `ROOT`/`STATIC` при отсутствии другого применения, `PROJECT`-дубликат, `PIXEL_PNG`, `FIXTURES`, обе inline install functions и inline `page` fixture. Импортировать необходимые `PROJECT`, `PIXEL_PNG`, `HttpCall`, `fixture_payloads`, `install_api`, `install_settings_api` из `browser_support.py`.
2. Заменить все 39 raw page creations:
   - убрать `browser: Browser` из test signatures;
   - принять `page_factory`;
   - создавать `inspected = page_factory(...)`, включая viewport и `reduced_motion` options;
   - локальные `page.route(...)`, held routes, counters и special terminal handlers сохранить, потому что они проверяют конкретные race/operation outcomes, но каждая такая страница теперь observable.
3. Удалить `try/finally inspected.close()` там, где lifecycle уже принадлежит fixture. Явное раннее закрытие допустимо, но не должно обходить teardown error assertion.
4. Ни один тест не должен менять shared template. Все варианты данных строить через `fixtures = fixture_payloads()` и менять только эту копию. В частности, переписать временную замену package detail в manual analysis recovery и settings variants, которые сейчас меняют/копируют legacy `FIXTURES`.
5. Сохранить имена и смысл всех существующих тестов и assertions. Механически адаптировать request assertions к `HttpCall`; не удалять проверки под видом устранения дублей.
6. Удалить все три `wait_for_timeout(100)` в затронутых settings flows:
   - после update ждать повторно отрисованную форму/summary с серверным значением и соответствующий recorded call;
   - после create ждать update-form с возвращённым ID;
   - после delete ждать detached form конкретного ID;
   - toast использовать только вместе с observable DOM/state/call condition, а не как замену подтверждённому CRUD состоянию.
7. После миграции статическая проверка должна находить `browser.new_page()` только в `conftest.py`, а в `test_browser_flows.py` не находить `wait_for_timeout`, `FIXTURES`, inline installers или fixture `page`.

## 3. Закрыть отсутствующие direct client/settings branches

Дополнить `tests/ui_mockup/test_client_logic.py`, используя реальный Chromium import `/settings.js`; не подменять production functions Python-реализацией.

1. Расширить точный serializer payload контролами:
   - пустой `data-omit-empty` отсутствует в результате;
   - непустой `data-omit-empty` присутствует с trimmed value;
   - сохранить уже проверяемые nested names, numbers, checkbox/hidden booleans, arrays, multi, null-empty, disabled controls и ignored buttons.
2. Добавить direct native-required case: form с пустым `required` control и `[data-settings-error]`; `validateSettingsSection` возвращает `false`, показывает «Заполните все обязательные поля», связывает form и именно invalid control через один error ID и не выполняет network mutation.
3. Добавить direct custom CTA case для `data-settings-form="cta"`, `link_mode="custom"` и абсолютного URL с запрещённым protocol (например `ftp:`). Проверить `false`, сообщение про HTTP(S), `aria-describedby` на `custom_url`; после замены на `https:` проверить `true` и очистку stale error/ARIA.
4. Добавить direct schedule slot-count case, где route payload/DOM содержат не три значения (отдельно от уже имеющегося malformed `29:00`). Проверить сообщение «Укажите три корректных времени публикации», связь с первым slot control, затем восстановить ровно три валидных уникальных slot-а и проверить очистку ошибки.
5. Для каждой invalid branch проверять не только текст/boolean, но и form/control accessibility relation. Существующие timezone, generation-limit, malformed-time и provider-rendering проверки сохранить.

## 4. Закрыть browser/dialog/empty/duplicate-action сценарии

Добавить focused flows в `tests/ui_mockup/test_browser_coverage.py`, повторно используя `fixture_payloads`, `HttpCall`, `install_api` и `page_factory`.

1. **Package-detail failure:** список review содержит пакет, а GET `/packages/{id}` отвечает 503. После нажатия dialog остаётся open, показывает «Не удалось загрузить пакет», сохраняет заголовок и кнопку закрытия, не показывает approve/reject/manual action buttons и не выдаёт console/page errors.
2. **Все пользовательские пути закрытия dialog:** на свежем открытии проверить отдельными cases:
   - кнопка «Закрыть»;
   - Escape;
   - click по backdrop/dialog outside content;
   - изменение hash/переход на другой route.
   Для первых трёх dialog становится closed и focus возвращается точному opener. Для route change overlay закрыт, stale detail отсутствует, destination screen полностью загружен. Сохранить уже существующие action-success tests, которые доказывают закрытие после успешных approve/reject/background commands.
3. **Empty-state controls:** при пустом review одновременно видны текст «Пакетов для проверки нет» и enabled «Подобрать ещё 3 поста». При пустом journal одновременно видны «Запусков пока нет», «Опубликовать один» и «Запустить поиск». Остальные empty-state assertions сохранить.
4. **Package double-click / duplicate owner command:** открыть пакет, удержать первый POST одного background action (предпочтительно `regenerate-post`), дважды попытаться активировать одну кнопку, пока первая команда pending, и доказать:
   - initiating button disabled/`aria-busy` по текущему контракту;
   - записан ровно один POST;
   - после release выполнены operation polls до terminal state;
   - показан ровно один terminal toast;
   - packages resource обновлён и dialog закрылся.
   Не использовать timeout; синхронизация только через held route, recorded call, disabled state, poll и DOM.

Если тест backdrop или duplicate action выявит дефект текущего `app.js`, внести минимальную правку только в обработчик существующего dialog/action lifecycle и сохранить текущие тексты/UX.

## 5. Доказать полный stateful CRUD каждого settings resource

Доработать существующие settings flows в `test_browser_flows.py` (или вынести только новые cases в `test_browser_coverage.py`) так, чтобы каждый ресурс отдельно проходил один и тот же пользовательский lifecycle против stateful `install_settings_api`:

1. **Source:** «Добавить источник», заполнить provider-driven required fields и schedule, сохранить, дождаться form с server ID 2; изменить имя/поле созданного source, дождаться server-refreshed значения; удалить ID 2 и дождаться detached. Проверить последовательность POST collection, PUT `/sources/2`, DELETE `/sources/2` и отсутствие мутации ID 1.
2. **CTA:** создать CTA, затем обновить созданный ID (включая `link_mode`/`custom_url` валидным HTTP(S) значением), удалить его; проверить DOM и exact endpoint/body на каждом шаге.
3. **Channel:** создать channel с provider-driven configuration и token intent, убедиться, что refresh возвращает server-owned `secretConfigured` без утечки token; обновить созданный channel, удалить его; проверить только ID 2 и exact POST/PUT/DELETE sequence. Существующий keep/replace/remove/check test для ID 1 сохранить.
4. **Route:** сохранить существующий create/update/delete flow, но привязать assertions к состоянию fake: созданный ID 2 появляется после GET refresh, update меняет именно его enabled/references/schedule, delete отсоединяет именно ID 2, исходный route ID 1 остаётся.
5. После каждого create/update/delete ждать observable refreshed DOM. Не принимать один лишь факт исходящего HTTP-вызова как доказательство CRUD.
6. Сохранить уже существующие section-only save, provider switching, validation, empty resource state, application-level channel-check failure и failure accessibility tests.

## 6. Focused verification во время реализации

После каждого блока запускать узкий набор без повторения полного suite:

```bash
uv run pytest -p no:cacheprovider -q tests/ui_mockup/test_client_logic.py
uv run pytest -p no:cacheprovider -q tests/ui_mockup/test_browser_coverage.py
uv run pytest -p no:cacheprovider -q \
  tests/ui_mockup/test_browser_flows.py -k 'settings or package or dialog or empty or operation'
```

Затем проверить отсутствие legacy механики; команда должна завершиться с exit 0:

```bash
! rg -n 'browser\.new_page|wait_for_timeout|^FIXTURES\s*=|^def install_api|^def install_settings_api|^def page\(' \
  tests/ui_mockup/test_browser_flows.py
```

Также выполнить:

```bash
uv run ruff check tests/ui_mockup
uv run pytest -p no:cacheprovider -q tests/ui_mockup
```

Ожидание: все прежние assertions остаются, новые cases проходят, нет browser console/page errors, fixed sleeps, raw pages или межтестовой утечки состояния.

## 7. Полная приёмка и evidence для повторного review

1. Запустить ровно тот full-suite command, который защищён quality profile:

```bash
uv run pytest -p no:cacheprovider -q tests
```

Exit 0 обязателен. Итоговое число должно быть не меньше исходных 824, без новых skipped/xfail и без сужения selection.

2. Запустить текущий полный SSSF profile:

```bash
uv run adws/adw_quality.py "Verify remaining UI test audit requirements"
```

Exit 0 обязателен; проверить 10/10 checks: `postgresql16_full_suite`, `ruff`, `compileall`, `lock`, `build_wheel`, `diff`, `node_api`, `node_screens`, `node_settings`, `node_app`. Full-suite log должен показывать pytest selection `tests` и включать `tests/ui_mockup`.

3. Выполнить финальные read-only/integrity checks:

```bash
git diff --check
git status --short
```

Не очищать грязный worktree и не создавать commit.

4. Передать reviewer точную карту исходных шести требований:
   - Task 1 теперь подтверждается отсутствием legacy harness/raw pages/timeouts и teardown observability;
   - Task 2 — direct cases native required, custom CTA, slot count и omit-empty вместе с прежними client branches;
   - Task 3 — package failure, все dialog close paths, empty controls, package duplicate action и stateful CRUD всех четырёх ресурсов;
   - Task 4 — неизменённый explicit full `tests` quality command;
   - Task 5 — уже принятый `docs/ui-v1-user-scenario.md`, не расширенный новыми product claims;
   - Task 6 — свежие full-suite и 10/10 SSSF logs.

Повторный review считается успешным только при одобрении всех шести требований и отсутствии Critical/Important замечаний по заявленному объёму.

## Definition of Done

- В UI tests существует один fixture template/factory/installer stack; каждая страница создаётся через observable `page_factory` и получает локальную deep copy состояния.
- В `test_browser_flows.py` отсутствуют raw `browser.new_page`, inline mutable harness и `wait_for_timeout`.
- Direct tests закрывают native required, non-HTTP custom CTA, неверное количество slots и `data-omit-empty`, включая error reset и ARIA wiring.
- Browser tests закрывают package-detail failure, close button, Escape, backdrop, route-change, review/journal empty controls и duplicate package command.
- Source, CTA, channel и route каждый доказан через create → server ID → update → delete с refreshed DOM и exact calls.
- Все прежние 824 теста не ослаблены; полный `tests` suite проходит, 10/10 SSSF checks зелёные, `git diff --check` проходит.
- Reviewer одобряет все исходные шесть требований. Нет новых продуктовых фич, UX-изменений, commit, push или merge.
