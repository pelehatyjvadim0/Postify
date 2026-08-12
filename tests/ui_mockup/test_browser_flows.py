import contextlib
import functools
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, Route, sync_playwright


ROOT = Path(__file__).parents[2]
STATIC = ROOT / "src/postify/web/static"
PROJECT = "/api/v1/projects/41"

FIXTURES = {
    "/api/v1/bootstrap": {
        "activeProject": {"id": 41, "name": "Технологии просто"},
        "providers": {
            "sources": [{
                "code": "hn_algolia",
                "label": "HN Algolia",
                "fields": [
                    {"name": "url", "label": "Адрес API", "type": "url", "required": True},
                    {"name": "query", "label": "Поисковый запрос", "type": "text", "required": True},
                    {"name": "tags", "label": "Теги", "type": "text", "required": True},
                    {"name": "hits", "label": "Материалов за запрос", "type": "number", "required": True, "min": 1, "max": 1000},
                ],
            }],
            "channels": [{
                "code": "telegram",
                "label": "Telegram",
                "fields": [
                    {"name": "chat_id", "label": "ID чата", "type": "text", "required": True},
                ],
                "secret": {"name": "token", "label": "Токен бота"},
            }],
        },
    },
    f"{PROJECT}/dashboard": {
        "candidate_total": 9001,
        "undecided_materials": 3,
        "selected_materials": 8,
        "package_total": 5,
        "approved_packages": 2,
        "published_today": 1,
        "daily_analyses_started": 7,
        "daily_packages_created": 4,
    },
    f"{PROJECT}/materials": {
        "items": [{
            "candidate_id": 9001,
            "source_name": "Исследовательский блог",
            "title": "Материал 9001 <img src=x onerror=window.__unsafe=1>",
            "url": "https://example.test/material-9001",
            "discovered_at": "2026-08-12T08:15:00Z",
            "decision_status": "selected",
            "decision_reason": "eligible_for_ai",
            "decision_explanation": "Есть практическая польза",
            "decision_signals": {"topic": "ai"},
            "policy_version": "v7",
        }],
    },
    f"{PROJECT}/packages": {
        "items": [{
            "package_id": 9001,
            "status": "awaiting_review",
            "source_url": "https://example.test/material-9001",
            "post_text": "Пакет 9001: полезный разбор",
            "media_available": False,
            "media_status": "unavailable",
            "created_at": "2026-08-12T09:00:00Z",
            "updated_at": "2026-08-12T09:00:00Z",
        }],
    },
    f"{PROJECT}/queue": {
        "items": [{
            "route_id": 9,
            "provider": "telegram",
            "slot_time": "09:30",
            "assignment_kind": "forecast",
            "package_id": 9001,
            "delivery_id": None,
        }],
    },
    f"{PROJECT}/publications": {
        "items": [{
            "delivery_id": 9001,
            "package_id": 8001,
            "provider": "telegram",
            "status": "uncertain",
            "attempts": 2,
            "message_id": None,
            "failure_code": "telegram_transport_uncertain",
            "failure_reason": "Ответ канала не подтверждён",
            "sending_started_at": "2026-08-12T10:00:00Z",
            "confirmed_at": None,
            "created_at": "2026-08-12T10:00:00Z",
            "updated_at": "2026-08-12T10:01:00Z",
        }],
    },
    f"{PROJECT}/operations": {
        "items": [{
            "run_id": 9001,
            "kind": "run_once",
            "status": "succeeded",
            "outcome": "completed",
            "failure_code": None,
            "started_at": "2026-08-12T07:00:00Z",
            "finished_at": "2026-08-12T07:00:12Z",
            "duration": 12,
        }],
    },
    f"{PROJECT}/settings": {
        "project": {
            "id": 41,
            "name": "Технологии просто",
            "topic": "Практичные AI-инструменты",
            "language": "ru",
            "audience": "Продуктовые команды",
            "timezone": "Europe/Moscow",
            "configuration": {
                "selection_policy_version": "project-41-v7",
                "selection_rules": ["advertising", "out_of_scope", "hiring", "technical_without_use"],
                "topic_terms": ["ai", "автоматизация"],
                "topic_exclusion_terms": ["лотерея"],
                "advertising_terms": ["реклама"],
                "hiring_terms": ["вакансия"],
                "technical_release_terms": ["release notes"],
                "practical_terms": ["кейс"],
                "selection_freshness_days": 30,
                "daily_analysis_limit": 12,
                "daily_package_limit": 3,
                "priority_freshness_days": 14,
                "fresh_share_percent": 90,
                "reserve_share_percent": 10,
                "review_required": True,
                "article_max_bytes": 2000000,
                "media_max_bytes": 10000000,
                "analysis_timeout_seconds": 600,
            },
        },
        "sources": [{
            "id": 1,
            "provider": "hn_algolia",
            "name": "Новости разработчиков",
            "enabled": True,
            "configuration": {"url": "https://hn.algolia.com", "query": "AI", "tags": "story", "hits": 50},
            "schedule": "0 7 * * *",
        }],
        "formats": [{
            "id": 1,
            "name": "Практический разбор B",
            "kind": "text",
            "instructions": "Хук, польза, ограничение и следующий шаг.",
            "enabled": True,
        }],
        "ctas": [{
            "id": 1,
            "name": "Полезный источник",
            "text": "Открыть источник",
            "link_mode": "source",
            "custom_url": None,
            "enabled": True,
        }],
        "channels": [{
            "id": 1,
            "provider": "telegram",
            "name": "Основной канал",
            "enabled": True,
            "configuration": {"chat_id": "-100123"},
            "connection_status": "configured",
            "secretConfigured": True,
        }],
        "routes": [{
            "id": 1,
            "format_id": 1,
            "channel_id": 1,
            "cta_id": 1,
            "enabled": True,
            "schedule": {"autopublish": True, "slots": ["09:00", "14:00", "19:00"]},
        }],
    },
}


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(STATIC))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        yield _launch_browser(playwright)


def _launch_browser(playwright: Playwright) -> Browser:
    return playwright.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])


def install_api(page: Page, requests: list[tuple[str, str]] | None = None) -> None:
    def handle(route: Route) -> None:
        request = route.request
        path = request.url.split("?", 1)[0].split(request.url.split("//", 1)[0] + "//", 1)[-1]
        path = "/" + path.split("/", 1)[1]
        if requests is not None:
            requests.append((request.method, path))
        if request.method in {"POST", "PUT", "DELETE"}:
            route.fulfill(status=202 if path.endswith("run-once") else 200, content_type="application/json", body='{"status":"accepted"}')
            return
        payload = FIXTURES.get(path)
        route.fulfill(
            status=200 if payload is not None else 404,
            content_type="application/json",
            body=json.dumps(payload or {"code": "not_found"}),
        )

    page.route("**/api/v1/**", handle)


def install_settings_api(page: Page, calls: list[dict[str, object]]) -> None:
    state = json.loads(json.dumps(FIXTURES[f"{PROJECT}/settings"]))

    def handle(route: Route) -> None:
        request = route.request
        path = "/" + request.url.split("/", 3)[-1].split("?", 1)[0]
        if request.method == "GET":
            payload = FIXTURES["/api/v1/bootstrap"] if path.endswith("/bootstrap") else state
            route.fulfill(json=payload)
            return
        body = request.post_data_json if request.post_data else None
        calls.append({"method": request.method, "path": path, "body": body})
        if request.method == "PUT" and path.endswith("/settings/main"):
            state["project"].update(body)
        route.fulfill(status=204 if request.method == "DELETE" else 200, json=None if request.method == "DELETE" else {"status": "ok"})

    page.route("**/api/v1/**", handle)


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    browser_page = browser.new_page(viewport={"width": 1440, "height": 1000})
    console_errors: list[str] = []
    browser_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    install_api(browser_page)
    yield browser_page
    with contextlib.suppress(Exception):
        browser_page.close()
    assert console_errors == []


@pytest.mark.parametrize(
    ("route", "title", "marker"),
    [
        ("overview", "Сегодня", "9001"),
        ("materials", "Материалы", "Материал 9001"),
        ("review", "Проверка", "Пакет 9001"),
        ("queue", "Очередь публикаций", "09:30"),
        ("publications", "История публикаций", "9001"),
        ("journal", "Журнал работы", "9001"),
    ],
)
def test_each_screen_renders_its_real_api_fixture(page: Page, base_url: str, route: str, title: str, marker: str) -> None:
    # Break caught: a screen renders stale/demo state or reads a neighbouring endpoint.
    page.goto(f"{base_url}/#{route}")
    assert page.locator("h1").inner_text() == title
    assert page.locator("#screen-root").get_by_text(marker, exact=False).first.is_visible()
    assert page.locator("#screen-root [data-screen]").get_attribute("data-screen") == route


def test_selected_route_fetches_only_bootstrap_and_its_resource(browser: Browser, base_url: str) -> None:
    # Break caught: initial navigation downloads every screen instead of its own bounded resource.
    inspected = browser.new_page()
    requests: list[tuple[str, str]] = []
    install_api(inspected, requests)
    try:
        inspected.goto(f"{base_url}/#materials")
        inspected.get_by_text("Материал 9001", exact=False).wait_for()
        assert requests == [("GET", "/api/v1/bootstrap"), ("GET", f"{PROJECT}/materials")]
    finally:
        inspected.close()


@pytest.mark.parametrize("width", [360, 768, 1440])
def test_settings_render_eight_compact_provider_driven_sections_without_overflow(
    browser: Browser, base_url: str, width: int
) -> None:
    # Break caught: settings stay a placeholder, expose infrastructure, or hard-code provider fields outside the bootstrap catalog.
    inspected = browser.new_page(viewport={"width": width, "height": 1000})
    install_api(inspected)
    try:
        inspected.goto(f"{base_url}/#settings")
        sections = inspected.locator("[data-settings-section]")
        sections.first.wait_for()
        assert sections.count() == 8
        assert inspected.locator("[data-settings-section][open]").count() == 1
        source_form = inspected.locator('[data-settings-form="sources"]').first
        channel_form = inspected.locator('[data-settings-form="channels"]').first
        assert source_form.get_by_label("Провайдер источника").input_value() == "hn_algolia"
        assert source_form.get_by_label("Поисковый запрос").input_value() == "AI"
        assert channel_form.get_by_label("ID чата").input_value() == "-100123"
        page_text = inspected.locator("#screen-root").inner_text().casefold()
        for forbidden in ("dsn", "media dir", "encryption key", "systemd"):
            assert forbidden not in page_text
        assert inspected.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

        for section in ("sources", "selection", "generation", "cta", "channels", "schedule", "advanced"):
            inspected.locator(f'[data-settings-section="{section}"] > summary').click()
            assert inspected.locator(f'[data-settings-section="{section}"]').get_attribute("open") == ""
            assert inspected.locator("[data-settings-section][open]").count() == 1
            assert inspected.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    finally:
        inspected.close()


def test_settings_save_is_section_scoped_dirty_busy_and_refreshes_summary(
    browser: Browser, base_url: str
) -> None:
    # Break caught: save sends the whole settings graph, stays clickable while busy, or leaves the server summary stale.
    inspected = browser.new_page(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    inspected.set_default_timeout(3000)
    try:
        inspected.goto(f"{base_url}/#settings")
        form = inspected.locator('[data-settings-form="main"]')
        savebar = form.locator(".settings-savebar")
        assert savebar.is_hidden()
        inspected.get_by_label("Название проекта").fill("Новая редакция")
        assert savebar.is_visible()
        save = form.get_by_role("button", name="Сохранить")
        save.click()
        assert save.is_disabled()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
        assert calls == [{
            "method": "PUT",
            "path": f"{PROJECT}/settings/main",
            "body": {
                "name": "Новая редакция",
                "topic": "Практичные AI-инструменты",
                "language": "ru",
                "audience": "Продуктовые команды",
                "timezone": "Europe/Moscow",
            },
        }]
        assert inspected.locator('[data-settings-section="main"] .settings-summary-current').inner_text() == "Новая редакция · ru"
        assert savebar.is_hidden()
    finally:
        inspected.close()


def test_serialize_settings_section_is_pure_and_keeps_nested_provider_values(
    page: Page, base_url: str
) -> None:
    # Break caught: serialization reads global screen state or flattens provider configuration into the common connection model.
    page.goto(f"{base_url}/#overview")
    result = page.evaluate(
        """async () => {
            const {serializeSettingsSection} = await import('/settings.js');
            const host = document.createElement('div');
            host.innerHTML = `<form data-settings-form="sources">
              <input name="name" value="Источник">
              <input name="enabled" type="checkbox" checked>
              <input name="configuration.query" value="AI">
              <input name="configuration.hits" type="number" value="25">
            </form>`;
            return serializeSettingsSection(host.querySelector('form'));
        }"""
    )
    assert result == {
        "name": "Источник",
        "enabled": True,
        "configuration": {"query": "AI", "hits": 25},
    }


def test_settings_validate_shares_slots_url_and_route_references_before_request(
    browser: Browser, base_url: str
) -> None:
    # Break caught: invalid cross-field settings reach an API that is forced to reject them after a network request.
    inspected = browser.new_page(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="generation"] > summary').click()
        generation = inspected.locator('[data-settings-form="generation"]')
        generation.get_by_label("Доля свежих, %").fill("80")
        generation.get_by_role("button", name="Сохранить").click()
        error = generation.locator("[data-settings-error]")
        assert "100" in error.inner_text()
        assert generation.get_by_label("Доля свежих, %").get_attribute("aria-describedby") == error.get_attribute("id")

        inspected.locator('[data-settings-section="schedule"] > summary').click()
        schedule = inspected.locator('[data-settings-form="schedule"]')
        schedule.get_by_label("Дневной слот").fill("09:00")
        schedule.get_by_role("button", name="Сохранить").click()
        assert "разными" in schedule.locator("[data-settings-error]").inner_text()

        inspected.locator('[data-settings-section="cta"] > summary').click()
        cta = inspected.locator('[data-settings-form="cta"]').first
        cta.get_by_label("Режим ссылки").select_option("custom")
        cta.get_by_label("Адрес ссылки").fill("javascript:alert(1)")
        cta.get_by_role("button", name="Сохранить").click()
        assert "HTTP" in cta.locator("[data-settings-error]").inner_text()
        assert calls == []
    finally:
        inspected.close()


def test_channel_token_keep_replace_remove_and_real_check_are_distinct_intents(
    browser: Browser, base_url: str
) -> None:
    # Break caught: a masked placeholder becomes a token value, blank save clears it, or remove/check remain decorative controls.
    inspected = browser.new_page(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="channels"] > summary').click()
        form = inspected.locator('[data-settings-form="channels"]').first
        token = form.get_by_label("Токен бота")
        assert token.input_value() == ""
        assert token.get_attribute("placeholder") == "Токен сохранён"
        assert form.get_by_role("button", name="Показать токен").is_disabled()

        form.get_by_label("ID чата").fill("-100456")
        form.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
        keep = next(call for call in calls if call["path"] == f"{PROJECT}/channels/1")
        assert "token" not in keep["body"]

        form = inspected.locator('[data-settings-form="channels"]').first
        token = form.get_by_label("Токен бота")
        token.fill("new-secret")
        reveal = form.get_by_role("button", name="Показать токен")
        assert reveal.is_enabled()
        reveal.click()
        assert token.get_attribute("type") == "text"
        inspected.locator('[data-settings-form="channels"]').first.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
        replacements = [call for call in calls if call["path"] == f"{PROJECT}/channels/1"]
        assert replacements[-1]["body"]["token"] == "new-secret"

        inspected.get_by_role("button", name="Удалить токен").click()
        inspected.get_by_role("button", name="Проверить канал").click()
        assert any(call["path"] == f"{PROJECT}/channels/1/secret/remove" for call in calls)
        assert any(call["path"] == f"{PROJECT}/channels/1/check" for call in calls)
        assert not any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/channels/1" for call in calls)
    finally:
        inspected.close()


def test_source_cta_channel_and_route_mutations_use_resource_endpoints(
    browser: Browser, base_url: str
) -> None:
    # Break caught: resource controls mutate an in-memory demo model instead of Task 7 CRUD endpoints.
    inspected = browser.new_page(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        changes = {
            "sources": ("Название источника", "Новости AI"),
            "cta": ("Название CTA", "Ссылка на материал"),
            "channels": ("Название канала", "Канал редакции"),
        }
        for section, (label, value) in changes.items():
            inspected.locator(f'[data-settings-section="{section}"] > summary').click()
            form = inspected.locator(f'[data-settings-form="{section}"]').first
            form.get_by_label(label).fill(value)
            form.get_by_role("button", name="Сохранить").click()
            inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
            inspected.wait_for_timeout(100)

        paths = {call["path"] for call in calls if call["method"] == "PUT"}
        assert paths >= {
            f"{PROJECT}/sources/1",
            f"{PROJECT}/ctas/1",
            f"{PROJECT}/channels/1",
            f"{PROJECT}/routes/1",
        }
        route = next(call for call in calls if call["path"] == f"{PROJECT}/routes/1")
        assert route["body"] | {"schedule": route["body"].get("schedule")} == {
            "format_id": 1,
            "channel_id": 1,
            "cta_id": 1,
            "enabled": True,
            "schedule": {"autopublish": True, "slots": ["09:00", "14:00", "19:00"]},
        }
    finally:
        inspected.close()


def test_resource_add_and_delete_controls_call_crud_endpoints(
    browser: Browser, base_url: str
) -> None:
    # Break caught: add/delete controls are decorative or routes can only be edited, not managed as resources.
    inspected = browser.new_page(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    inspected.set_default_timeout(3000)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="sources"] > summary').click()
        inspected.get_by_role("button", name="Добавить источник").click()
        source = inspected.locator('[data-resource="sources"][data-resource-mode="create"]')
        source.get_by_label("Название источника").fill("Второй источник")
        source.get_by_label("Адрес API").fill("https://hn.algolia.com")
        source.get_by_label("Поисковый запрос").fill("Python")
        source.get_by_label("Теги").fill("story")
        source.get_by_label("Материалов за запрос").fill("20")
        source.get_by_label("Расписание получения").fill("0 8 * * *")
        source.get_by_role("button", name="Сохранить").click()
        inspected.wait_for_timeout(100)

        inspected.locator('[data-settings-section="cta"] > summary').click()
        inspected.locator('[data-resource="ctas"][data-resource-mode="update"]').get_by_role("button", name="Удалить").click()
        inspected.wait_for_timeout(100)

        inspected.locator('[data-settings-section="channels"] > summary').click()
        inspected.get_by_role("button", name="Добавить маршрут").click()
        route_form = inspected.locator('[data-resource="routes"][data-resource-mode="create"]')
        route_form.get_by_role("button", name="Сохранить").click()
        inspected.wait_for_timeout(100)
        inspected.get_by_role("button", name="Удалить маршрут").click()
        inspected.wait_for_timeout(100)

        assert any(call["method"] == "POST" and call["path"] == f"{PROJECT}/sources" for call in calls)
        assert any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/ctas/1" for call in calls)
        assert any(call["method"] == "POST" and call["path"] == f"{PROJECT}/routes" for call in calls)
        assert any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/routes/1" for call in calls)
    finally:
        inspected.close()


def test_loading_error_retry_and_empty_are_explicit(browser: Browser, base_url: str) -> None:
    # Break caught: an unavailable API leaks demo cards or retry cannot recover the selected screen.
    inspected = browser.new_page()
    held_routes: list[Route] = []
    released = False

    def handle(route: Route) -> None:
        nonlocal released
        if route.request.url.endswith("/bootstrap"):
            route.fulfill(json=FIXTURES["/api/v1/bootstrap"])
        elif not released:
            held_routes.append(route)
        else:
            route.fulfill(json={"items": []})

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#materials", wait_until="domcontentloaded")
        loading = inspected.locator('[data-screen="materials"][data-loading]')
        loading.wait_for()
        assert loading.is_visible()
        assert loading.get_attribute("aria-busy") == "true"
        assert len(held_routes) == 1

        released = True
        held_routes.pop().fulfill(
            status=503,
            content_type="application/json",
            body='{"code":"service_unavailable"}',
        )
        inspected.get_by_text("Не удалось загрузить", exact=False).wait_for()
        assert inspected.get_by_text("Материал 9001", exact=False).count() == 0
        inspected.get_by_role("button", name="Повторить").click()
        inspected.get_by_text("Материалов пока нет", exact=False).wait_for()
    finally:
        inspected.close()


def test_retry_reloads_bootstrap_after_initial_connection_failure(browser: Browser, base_url: str) -> None:
    # Break caught: initial retry requests /projects/null instead of reconnecting and discovering the active project.
    inspected = browser.new_page()
    bootstrap_calls = 0

    def handle(route: Route) -> None:
        nonlocal bootstrap_calls
        path = "/" + route.request.url.split("/", 3)[-1]
        if path == "/api/v1/bootstrap":
            bootstrap_calls += 1
            if bootstrap_calls == 1:
                route.fulfill(status=503, json={"code": "service_unavailable"})
            else:
                route.fulfill(json=FIXTURES[path])
            return
        route.fulfill(json=FIXTURES[path])

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#materials")
        inspected.get_by_role("button", name="Повторить").click()
        inspected.get_by_text("Материал 9001", exact=False).wait_for()
        assert bootstrap_calls == 2
    finally:
        inspected.close()


def test_api_text_is_escaped_instead_of_inserted_as_markup(page: Page, base_url: str) -> None:
    # Break caught: API-owned content executes through innerHTML.
    page.goto(f"{base_url}/#materials")
    page.get_by_text("Материал 9001", exact=False).wait_for()
    assert page.evaluate("window.__unsafe") is None
    assert page.locator("#screen-root img").count() == 0


@pytest.mark.parametrize(
    ("source_url", "expected_href"),
    [
        ("https://example.test/source", "https://example.test/source"),
        ("http://example.test/source", "http://example.test/source"),
        ("javascript:window.__unsafeUrl=1", None),
    ],
)
def test_package_source_url_allows_only_http_and_https(
    browser: Browser,
    base_url: str,
    source_url: str,
    expected_href: str | None,
) -> None:
    # Break caught: escaping quotes still leaves a javascript: URL executable in href.
    inspected = browser.new_page()

    def handle(route: Route) -> None:
        path = "/" + route.request.url.split("/", 3)[-1]
        if path == f"{PROJECT}/packages":
            payload = json.loads(json.dumps(FIXTURES[path]))
            payload["items"][0]["source_url"] = source_url
            route.fulfill(json=payload)
            return
        route.fulfill(json=FIXTURES[path])

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        source = inspected.locator("#detail-content dd").filter(has_text=source_url)
        assert source.is_visible()
        if expected_href is None:
            assert source.locator("a").count() == 0
        else:
            assert source.locator("a").get_attribute("href") == expected_href
        assert inspected.evaluate("window.__unsafeUrl") is None
    finally:
        inspected.close()


def test_all_emitted_domain_codes_have_explicit_russian_labels(page: Page, base_url: str) -> None:
    # Break caught: a backend enum reaches the UI as an English snake_case fallback.
    expected = {
        "selected": "Выбран",
        "rejected": "Отклонён",
        "eligible_for_ai": "Подходит для анализа",
        "advertising": "Реклама",
        "out_of_scope": "Вне темы",
        "hiring": "Вакансия",
        "technical_without_use": "Технический релиз без практической пользы",
        "not_started": "Не начат",
        "processing": "Обрабатывается",
        "awaiting_review": "Ждёт проверки",
        "approved": "Одобрен",
        "failed": "Ошибка",
        "published": "Опубликовано",
        "available": "Доступно",
        "unavailable": "Недоступно",
        "deleted": "Удалено",
        "confirmed": "Подтверждён",
        "forecast": "Прогноз",
        "empty": "Свободно",
        "sending": "Отправляется",
        "retryable": "Можно повторить",
        "uncertain": "Результат не подтверждён",
        "run_once": "Поиск и подготовка",
        "publish_once": "Публикация",
        "running": "Выполняется",
        "succeeded": "Успешно",
        "completed": "Завершено",
        "cleanup_completed": "Медиа очищено",
        "cleanup_pending": "Ожидает очистки медиа",
        "run_once_failed": "Поиск завершился ошибкой",
        "publish_once_failed": "Публикация завершилась ошибкой",
        "media_unavailable": "Медиа недоступно",
        "telegram_transport_uncertain": "Ответ канала не подтверждён",
        "telegram_invalid_response": "Некорректный ответ канала",
        "telegram_retryable": "Канал временно недоступен",
        "telegram_rejected": "Канал отклонил публикацию",
        "stale_sending": "Отправка не завершена",
    }
    page.goto(f"{base_url}/#overview")
    actual = page.evaluate(
        """async codes => {
            const {label} = await import('/screens.js');
            return Object.fromEntries(codes.map(code => [code, label(code)]));
        }""",
        list(expected),
    )
    assert actual == expected


@pytest.mark.parametrize(("action", "method", "suffix", "toast"), [
    ("approve-package", "POST", "/packages/9001/approve", "Пост одобрен"),
    ("reject-package", "POST", "/packages/9001/reject", "Пост отклонён"),
])
def test_review_mutations_are_real_and_refresh_packages(browser: Browser, base_url: str, action: str, method: str, suffix: str, toast: str) -> None:
    # Break caught: review only mutates local UI state or fails to refresh after success.
    inspected = browser.new_page()
    requests: list[tuple[str, str]] = []
    install_api(inspected, requests)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        if action == "reject-package":
            inspected.locator('[data-action="show-reject-form"]').click()
            inspected.locator("#reject-reason").fill("Недостаточно практических деталей")
        inspected.locator(f'[data-action="{action}"]').click()
        inspected.get_by_text(toast, exact=True).wait_for()
        inspected.locator('[data-screen="review"]:not([data-loading])').wait_for()
        assert (method, f"{PROJECT}{suffix}") in requests
        assert requests.count(("GET", f"{PROJECT}/packages")) >= 2
    finally:
        inspected.close()


@pytest.mark.parametrize(("action", "suffix", "toast"), [
    ("new-run", "/operations/run-once", "Поиск запущен"),
    ("publish-once", "/operations/publish-once", "Публикация запущена"),
])
def test_operation_commands_are_real_and_refresh_journal(browser: Browser, base_url: str, action: str, suffix: str, toast: str) -> None:
    # Break caught: operational controls are decorative or leave stale journal data.
    inspected = browser.new_page()
    requests: list[tuple[str, str]] = []
    install_api(inspected, requests)
    try:
        inspected.goto(f"{base_url}/#journal")
        inspected.locator(f'[data-action="{action}"]').first.click()
        inspected.get_by_text(toast, exact=True).wait_for()
        inspected.locator('[data-screen="journal"]:not([data-loading])').wait_for()
        assert ("POST", f"{PROJECT}{suffix}") in requests
        assert requests.count(("GET", f"{PROJECT}/operations")) >= 2
    finally:
        inspected.close()


@pytest.mark.parametrize("width,height", [(360, 800), (768, 1024), (1440, 1000)])
@pytest.mark.parametrize("route", ["overview", "materials", "review", "queue", "publications", "journal"])
def test_every_screen_has_no_horizontal_overflow(page: Page, base_url: str, width: int, height: int, route: str) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#{route}")
    page.locator("[data-screen]").wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_mobile_navigation_and_detail_targets_are_touch_ready(page: Page, base_url: str) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{base_url}/#review")
    assert page.locator(".sidebar").is_hidden()
    assert page.locator(".mobile-nav").is_visible()
    heights = page.locator(".mobile-nav a, .mobile-nav button").evaluate_all("elements => elements.map(element => element.getBoundingClientRect().height)")
    assert min(heights) >= 44
    page.locator('[data-action="open-package"]').click()
    bounds = page.locator("#detail-layer").bounding_box()
    assert bounds is not None
    assert bounds["width"] == pytest.approx(360, abs=1)
    assert bounds["height"] == pytest.approx(800, abs=1)


@pytest.mark.parametrize(("route", "title"), [("publications", "История публикаций"), ("journal", "Журнал работы"), ("settings", "Настройки")])
def test_mobile_more_menu_keeps_secondary_routes_reachable(page: Page, base_url: str, route: str, title: str) -> None:
    # Break caught: hiding the desktop sidebar makes secondary working routes unreachable on mobile.
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{base_url}/#overview")
    assert page.locator('[data-action="open-mobile-menu"]').count() == 1
    page.locator('[data-action="open-mobile-menu"]').click()
    page.locator(f'#detail-layer [href="#{route}"]').click()
    page.locator(f'[data-screen="{route}"]').wait_for()
    assert page.locator("h1").inner_text() == title


def test_reduced_motion_removes_visible_screen_transition(browser: Browser, base_url: str) -> None:
    inspected = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    install_api(inspected)
    try:
        inspected.goto(f"{base_url}/#overview")
        screen = inspected.locator('[data-screen="overview"]:not([data-loading])')
        screen.wait_for()
        duration = screen.evaluate("element => getComputedStyle(element).animationDuration")
        assert duration in {"0s", "1e-05s"}
    finally:
        inspected.close()


def test_overview_summary_and_logo_keep_approved_optical_alignment(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/#overview")
    page.locator(".studio-strip").wait_for()
    columns = page.locator(".studio-strip > div").evaluate_all(
        "elements => elements.map(element => element.getBoundingClientRect().toJSON())"
    )
    brand = page.locator(".brand").evaluate("""element => {
        const mark = element.querySelector('.brand-mark').getBoundingClientRect();
        const name = element.querySelector('.brand-name').getBoundingClientRect();
        return {mark: mark.y + mark.height / 2, name: name.y + name.height / 2};
    }""")
    assert max(column["width"] for column in columns) - min(column["width"] for column in columns) <= 1
    assert len({round(column["height"], 1) for column in columns}) == 1
    assert brand["mark"] == pytest.approx(brand["name"], abs=1)


@pytest.mark.parametrize("width", [360, 768, 1440])
def test_queue_timeline_rule_runs_through_marker_centres(
    page: Page, base_url: str, width: int
) -> None:
    # Break caught: a responsive grid offset separates the day rhythm rule from its markers.
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{base_url}/#queue")
    assert page.locator('[data-screen="queue"]').is_visible()
    assert page.locator("h1").inner_text() == "Очередь публикаций"
    geometry = page.locator(".timeline").evaluate("""element => {
        const timeline = element.getBoundingClientRect();
        const marker = element.querySelector('.timeline-marker').getBoundingClientRect();
        const rule = getComputedStyle(element, '::before');
        return {
            ruleX: timeline.x + parseFloat(rule.left) + parseFloat(rule.width) / 2,
            markerX: marker.x + marker.width / 2,
        };
    }""")
    assert geometry["ruleX"] == pytest.approx(geometry["markerX"], abs=0.5)


def test_mobile_review_keeps_thumbnail_copy_and_both_actions_visible(page: Page, base_url: str) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{base_url}/#review")
    card = page.locator(".content-card").first
    thumbnail = card.locator(".material-thumb").bounding_box()
    copy = card.locator(".content-card-copy").bounding_box()
    assert thumbnail is not None and copy is not None
    assert thumbnail["x"] + thumbnail["width"] <= copy["x"]

    page.locator('[data-action="open-package"]').click()
    assert page.locator('[data-action="show-reject-form"]').is_visible()
    assert page.locator('[data-action="approve-package"]').is_visible()


def test_journal_starts_with_operational_content_without_status_banner(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/#journal")
    assert page.locator(".system-banner").count() == 0
    assert page.locator(".journal-list").is_visible()
