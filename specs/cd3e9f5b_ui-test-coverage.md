# UI Test Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** довести автоматизированные проверки всей реализованной UI-логики до надёжного регрессионного контура, исправить ложные и неполные тесты и доказать их запуск детерминированным quality gate SSSF.

**Architecture:** оставить pytest + Playwright единым публичным контуром UI-проверок, но вынести общую механику browser pages, API fixtures и фоновых операций из перегруженного `test_browser_flows.py`. Проверять поведение через публичный DOM и HTTP-контракт, а чистые экспорты `api.js`/`settings.js` — через импорт ES-модулей в реальном Chromium. SSSF должен явно запускать весь каталог `tests/`, куда входят browser flows.

**Tech Stack:** Python 3.12, pytest, Playwright/Chromium, FastAPI TestClient/httpx, JavaScript ES modules, `uv`, SSSF `adws/adw_modules/postify_quality.py`.

**Spec:** `wave-10.md` для текущих manual UI flows; полный набор уже готовых возможностей задают `src/postify/web/static/index.html`, `api.js`, `app.js`, `screens.js` и `settings.js`.

## Global Constraints

- Работать в текущем грязном worktree `feature/ui-v1-html-mockup`; не сбрасывать и не перезаписывать существующие несвязанные изменения.
- Не добавлять продуктовые UI-фичи и не менять UX; исходники UI менять только если новый тест доказал реальную поломку уже заявленного поведения.
- Не выполнять commit, push или merge.
- Судить о каждой команде по exit status. Тесты не должны скрывать `console.error`, uncaught `pageerror`, ложный success после HTTP 202 или состояние из другого теста.
- Не дублировать полный pytest в отдельном browser gate: один SSSF test check запускает весь `tests/`, а `node --check` остаётся быстрой синтаксической проверкой каждого JS-модуля.

## Verified Baseline

- `uv run pytest -p no:cacheprovider -q tests/ui_mockup tests/unit/web/test_static.py tests/unit/web/test_api.py` завершается с exit 1: **3 failed, 117 passed**.
- Падают два варианта `test_manual_package_revision_actions_are_real_owner_commands` и `test_manual_publish_now_is_a_project_scoped_owner_command`. Их fake возвращает `{"status":"accepted"}` без `operationRunId`, поэтому обходит реальный контракт `accepted -> polling -> terminal`, а ожидаемые toast-строки не совпадают с текущим UI.
- `uv run pytest -p no:cacheprovider -q tests/unit/adws/test_quality_profile.py` проходит: **2 passed**.
- `uv run pytest -p no:cacheprovider --collect-only -q` собирает **816 tests**, включая `tests/ui_mockup`, но SSSF-контракт не фиксирует каталог `tests` в argv и не защищается от будущего сужения pytest selection.
- Найденные пробелы: CSRF header со стороны browser client, sanitization `ApiError`, фильтр материалов, отмена stale route response, fallback неизвестного hash, возврат фокуса и закрытие dialog, защита от двойной команды, все ветви serializer/validator настроек, provider switch, CRUD для CTA/channel и application-level ошибка channel check.

## File Map

- Create `tests/ui_mockup/browser_support.py`: изолированные копии API fixtures, route installers и реалистичный accepted-operation stub.
- Create `tests/ui_mockup/conftest.py`: static HTTP server, Chromium и единая page factory с коротким timeout и проверкой browser errors.
- Create `tests/ui_mockup/test_client_logic.py`: прямые поведенческие тесты `api.js` и чистой логики `settings.js`.
- Modify `tests/ui_mockup/test_browser_flows.py`: исправленные end-to-end flows, навигация, details, мутации, настройки и адаптивность.
- Modify `tests/ui_mockup/test_static_contract.py`: статический контракт всех производственных UI assets и маркеров доступности.
- Modify `adws/adw_modules/postify_quality.py`: явная selection полного `tests/` в тестовом check.
- Modify `tests/unit/adws/test_quality_profile.py`: регрессия, доказывающая запуск UI-набора в SSSF без exclude filters.
- Create `docs/ui-v1-user-scenario.md`: проверенный сценарий от первого лица только для уже работающих UI-возможностей.

---

### Task 1: Make the Browser Harness Fail Fast and Model the Real API

**Files:**
- Create: `tests/ui_mockup/browser_support.py`
- Create: `tests/ui_mockup/conftest.py`
- Modify: `tests/ui_mockup/test_browser_flows.py:1-385`

**Interfaces:**
- `fixture_payloads() -> dict[str, object]` returns a deep copy per test.
- `install_api(page: Page, *, fixtures: dict[str, object] | None = None, calls: list[HttpCall] | None = None) -> None` intercepts API requests without global mutation.
- `install_settings_api(page: Page, calls: list[HttpCall], *, initial_settings: dict[str, object] | None = None, failures: set[str] | None = None, channel_check: dict[str, object] | None = None) -> None` owns stateful settings CRUD.
- `page_factory(**browser_context_options) -> Page` creates a page, applies a 3-second default timeout, records `console.error` and `pageerror`, and fails during fixture teardown if either list is non-empty.
- `HttpCall` is `@dataclass(frozen=True, slots=True)` with `method: str`, `path: str` (including query), `body: object | None`, and `headers: dict[str, str]`.

- [ ] **Step 1: Extract shared mechanics without changing assertions**

Move `PROJECT`, fixture payloads, `install_api`, and `install_settings_api` into `browser_support.py`; move `base_url`, `browser`, and page creation into `conftest.py`. Keep product meaning in individual tests and reusable HTTP/browser mechanics in helpers.

Use an isolated fixture factory rather than mutating `FIXTURES`:

```python
def fixture_payloads() -> dict[str, object]:
    return copy.deepcopy(FIXTURE_TEMPLATE)
```

- [ ] **Step 2: Make every custom page observable**

Replace every raw `browser.new_page(...)` in `test_browser_flows.py` with `page_factory(...)`. Register both error channels and assert them after closing all pages:

```python
page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
page.on("pageerror", lambda error: errors.append(str(error)))
page.set_default_timeout(3_000)
```

Replace fixed `wait_for_timeout(100)` calls in touched CRUD flows with an observable endpoint call, toast, refreshed form, or detached locator. This removes the current 30-second penalty for a stale assertion.

- [ ] **Step 3: Model background operations correctly**

For `operations/search`, `operations/publish-once`, `packages/load-more`, retry/regenerate/media/publish-now, and delivery retry, make the default fake return HTTP 202 plus `operationRunId`, then return `running` once and the configured terminal response from `GET /operations/{id}`. Approve/reject and settings CRUD remain synchronous responses.

```python
{"status": "accepted", "operationRunId": operation_id}
{"run_id": operation_id, "status": "running", "outcome": None, "failure_code": None}
{"run_id": operation_id, "status": "succeeded", "outcome": "completed", "failure_code": None}
```

- [ ] **Step 4: Remove the three false regressions and retain stronger coverage**

Delete the two shallow parameter cases in `test_manual_package_revision_actions_are_real_owner_commands` and the shallow `test_manual_publish_now_is_a_project_scoped_owner_command`; their endpoints are already covered by `test_package_background_actions_wait_for_terminal_run_and_refresh_review`. Expand that stronger parameterized test to assert exactly one POST, at least two operation reads, refreshed packages, closed detail, and the implemented terminal toast:

```python
[
    ("regenerate-post", "/packages/9001/regenerate", "Новая версия поста готова"),
    ("replace-media", "/packages/9001/media/replace", "Медиа обновлено"),
    ("publish-now", "/packages/9001/publish-now", "Публикация завершена"),
]
```

Rewrite delivery retry and successful journal commands to use the same accepted-operation mechanic rather than treating 202 as completion.

- [ ] **Step 5: Prove the corrected harness catches the previous break**

Run:

```bash
uv run pytest -p no:cacheprovider -q \
  tests/ui_mockup/test_browser_flows.py::test_package_background_actions_wait_for_terminal_run_and_refresh_review \
  tests/ui_mockup/test_browser_flows.py::test_manual_delivery_retry_is_a_project_scoped_owner_command \
  tests/ui_mockup/test_browser_flows.py::test_operation_commands_are_real_and_refresh_journal
```

Expected: exit 0; every case observes polling before success and no case waits for the obsolete strings `создаётся`, `Подбираем новое медиа`, or `Публикация запущена`.

### Task 2: Cover the API Client and Pure Settings Logic

**Files:**
- Create: `tests/ui_mockup/test_client_logic.py`
- Reuse: `tests/ui_mockup/browser_support.py`

**Interfaces:**
- Public JS imports: `getBootstrap`, `getDashboard`, `deleteResource`, `request`, `ApiError` from `/api.js`; `serializeSettingsSection`, `validateSettingsSection`, `renderProviderConfiguration` from `/settings.js`.

- [ ] **Step 1: Test browser-side capability and response handling**

Add a fresh-page test that imports `/api.js`, obtains bootstrap, performs one GET and one DELETE, and asserts:

- `X-Postify-CSRF: browser-fixture-capability` appears on the mutation only;
- the mutation sends no invented body;
- HTTP 204 resolves to `null`;
- a JSON error preserves safe `status`/`code` and filters `unresolvedPackageIds` to positive integers, at most 50;
- a non-JSON error becomes `ApiError(status, "request_failed")` without exposing response text.

- [ ] **Step 2: Exercise every serializer value class**

Build one detached form in the browser and assert the exact object for nested names, number conversion, checkbox booleans, hidden boolean values, comma arrays, repeated `data-multi`, `data-null-empty`, `data-omit-empty`, disabled controls, and ignored buttons. Add a separate schedule-form case asserting numeric resource IDs, trimmed cron/slots, and route autopublish.

Expected representative payload:

```python
{
    "name": "Источник",
    "enabled": True,
    "configuration": {"hits": 25, "query": "AI"},
    "terms": ["AI", "Python"],
    "cta_id": None,
    "schedule": {"autopublish": True, "slots": ["09:00", "14:00", "19:00"]},
}
```

- [ ] **Step 3: Complete validator branch coverage with meaningful DOM assertions**

Add parameterized tests for the branches not currently exercised:

- invalid project timezone;
- `daily_package_limit > daily_analysis_limit`;
- native missing required field;
- malformed/non-HTTP custom CTA URL;
- a schedule value outside `HH:MM` and a schedule with other than three slots;
- missing route format/channel reference;
- clearing a previous error before a subsequent valid validation.

For each invalid case assert `False`, exact user-facing message fragment, `aria-describedby` on the form and offending control, and zero mutation calls. For the corrected value assert `True` and removal of the stale accessibility relation.

- [ ] **Step 4: Test provider-driven rendering as data, not hard-coded markup**

Call `renderProviderConfiguration` with two provider descriptors and assert that switching provider code changes field name/type/constraints, escapes descriptor text, and returns no fields for an unknown provider. This protects the dynamic branch used by source/channel forms.

- [ ] **Step 5: Run the focused logic tests**

Run:

```bash
uv run pytest -p no:cacheprovider -q tests/ui_mockup/test_client_logic.py
```

Expected: exit 0 with no browser console or page errors.

### Task 3: Close Behavioral Gaps Across Every Implemented Screen and Command

**Files:**
- Modify: `tests/ui_mockup/test_browser_flows.py`
- Modify: `tests/ui_mockup/test_static_contract.py`

**Interfaces:**
- Assertions use public routes `#overview`, `#materials`, `#review`, `#queue`, `#publications`, `#journal`, `#settings` and project-scoped `/api/v1/projects/{id}/...` calls.

- [ ] **Step 1: Complete navigation and request-race coverage**

Add tests proving:

- an unknown hash is normalized to `#overview`, updates title, and sets exactly the overview desktop/mobile links to `aria-current="page"`;
- material filter clicks issue `GET /materials?status=selected` and `?status=rejected`, while `all` omits the query;
- navigating away while the materials response is held aborts/ignores that response, renders the destination, and never lets the stale payload overwrite it.

- [ ] **Step 2: Cover empty render branches for every list screen**

Parameterize materials, review, queue, publications, and journal with `{"items": []}` and assert each route's own empty copy and `data-screen`. For review also assert the load-more action remains present; for journal assert operation controls remain available. Keep overview's zero counters as a separate exact-metrics case because it has no list-level empty branch.

- [ ] **Step 3: Verify detail lifecycle and inaccessible/error branches**

Add browser flows that assert:

- package detail GET failure leaves the dialog open with `Не удалось загрузить пакет` and no action buttons;
- close button returns focus to the exact opener;
- Escape and route change close the dialog without a stale overlay;
- material, publication, and journal detail values remain escaped and unknown codes render `Неизвестное состояние`.

- [ ] **Step 4: Prove rapid repeated actions do not duplicate owner commands**

Hold the first response, issue two rapid click attempts on a topbar search action and on a package background action, and assert exactly one POST per action while the initiating button is disabled. Release the response, complete polling, and assert one terminal toast and one resource refresh.

- [ ] **Step 5: Complete settings feature coverage**

Expand stateful CRUD cases so source, CTA, channel, and route each prove create, update, and delete against the ID returned by the fake server. Add exact successful section-only saves for selection, generation, and advanced configuration. Add a provider-change test that replaces the provider fieldset and serializes only the new provider's values. Add the application-level channel-check failure case (`HTTP 200`, `connectionStatus != "ok"`) and assert the server `reason` is attached to the refreshed form/check button instead of showing a success toast.

Do not introduce a project switch test: `#farm-switcher` has no implemented action. Do not add rejection-reason behavior: the current public contract intentionally sends no reject body and is already tested.

- [ ] **Step 6: Strengthen static feature inventory**

Update `test_static_contract.py` to assert all seven route links, skip link target, dialog labelling, live toast region, module script, and the complete six-file production asset set. Keep these as structural packaging regressions; dynamic behavior belongs in Playwright tests.

- [ ] **Step 7: Run all UI-facing tests**

Run:

```bash
uv run pytest -p no:cacheprovider -q \
  tests/ui_mockup \
  tests/unit/web/test_static.py \
  tests/unit/web/test_api.py \
  tests/integration/test_web_component.py \
  tests/e2e/test_cli_ui.py
```

Expected: exit 0; all seven screens, settings, installed-wheel serving, API commands, terminal operations, error/empty/loading states, security headers, mobile layout, and accessibility interactions pass.

### Task 4: Make SSSF Explicitly Own the Full UI Test Suite

**Files:**
- Modify: `adws/adw_modules/postify_quality.py:79-96`
- Modify: `tests/unit/adws/test_quality_profile.py`

**Interfaces:**
- `test_spec() -> QualityCheckSpec` remains the only full pytest definition used by both `run_tests()` and `run_quality()`.

- [ ] **Step 1: Write the failing quality-profile regression**

Add `test_full_suite_command_explicitly_selects_all_tests_without_exclusions` and assert the exact test argv:

```python
assert postify_quality.test_spec().argv == [
    "uv", "run", "pytest", "-p", "no:cacheprovider", "-q", "tests",
]
```

Also assert no `-m`, `-k`, `--ignore`, or individual test path narrows the suite, and that `quality_specs(run)` contains this exact spec once plus `node_api`, `node_screens`, `node_settings`, and `node_app` once each.

- [ ] **Step 2: Make the deterministic command explicit**

Append `tests` to `test_spec().argv`. Do not add a second browser-specific pytest invocation; the explicit full directory already collects `tests/ui_mockup` and avoids doubling the two-minute browser run.

- [ ] **Step 3: Prove collection and profile wiring**

Run:

```bash
uv run pytest -p no:cacheprovider -q tests/unit/adws/test_quality_profile.py
uv run pytest -p no:cacheprovider --collect-only -q tests
```

Expected: both commands exit 0; collection includes `tests/ui_mockup/test_browser_flows.py` and `tests/ui_mockup/test_client_logic.py`.

### Task 5: Document the Verified First-Person User Scenario

**Files:**
- Create: `docs/ui-v1-user-scenario.md`

- [ ] **Step 1: Write only implemented capabilities in first person**

Structure the Russian scenario as a real pass through the active project:

1. «Я запускаю `postify ui` и открываю панель»: bootstrap, active project, overview counters, automatic/manual metrics, recent operations.
2. «Я фильтрую материалы»: all/selected/rejected and explainable material detail.
3. «Я разбираю пакеты»: text, safe source link, analysis, media, history, approve/reject, unresolved guidance, load-more and terminal states.
4. «Я исправляю и доставляю контент»: retry analysis, return to analysis, regenerate, replace media, publish now, queue, publication attempts, delivery retry.
5. «Я слежу за операциями»: manual search/publish, polling, journal outcome/failure, model/effort and counts.
6. «Я настраиваю проект по секциям»: main, sources, selection, generation, CTA, channels/routes, schedule, advanced; token keep/replace/remove and channel check.
7. «Я вижу честную обратную связь»: loading, empty, validation, conflict, terminal failure, safe retry, mobile navigation.

- [ ] **Step 2: Tie each paragraph to verified behavior**

End each section with a compact `Проверено:` line naming the relevant browser/API test, without claiming project switching, rejection reasons, analytics, or video features.

### Task 6: Run the Same Acceptance Path the Factory Uses

**Files:**
- Verify all files above; do not create commit artifacts.

- [ ] **Step 1: Run the focused suite once after all edits**

```bash
uv run pytest -p no:cacheprovider -q \
  tests/ui_mockup \
  tests/unit/web/test_static.py \
  tests/unit/web/test_api.py \
  tests/unit/adws/test_quality_profile.py
```

Expected: exit 0 and no skipped browser-flow feature group.

- [ ] **Step 2: Run the deterministic SSSF quality gate**

```bash
uv run adws/adw_quality.py "Verify complete UI test coverage and full Postify quality profile"
```

Expected: exit 0; the `postgresql16_full_suite` check runs `pytest ... tests`, and all ten current checks pass: full suite, ruff, compileall, lock, wheel build, diff, and four `node --check` modules.

- [ ] **Step 3: Inspect generated evidence and repository integrity**

Read the quality command logs named by the successful ADW output and confirm the full-suite log contains the UI tests with zero failures. Then run:

```bash
git diff --check
git status --short
```

Expected: exit 0 from `git diff --check`; status contains only the pre-existing work plus the planned test, quality-profile, and documentation changes. Do not commit, push, or merge.

## Self-Review Checklist

- Every implemented route, detail type, manual command, settings section, error/empty/loading state, mobile navigation path, browser security contract, packaging contract, and SSSF wiring maps to an explicit task above.
- The plan does not add project switching, rejection-reason UX, analytics, video, or another test framework.
- Public names and payload fields match the current implementation: `operationRunId`, `unresolvedPackageIds`, `csrfToken`, `connectionStatus`, `analysis_model`, and `analysis_reasoning_effort`.
- The user scenario is documentation of tested behavior, not a future feature specification.
