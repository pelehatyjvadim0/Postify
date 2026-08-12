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
        "providers": {"sources": ["hn_algolia"], "channels": ["telegram"]},
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
            "media_status": "missing",
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
            "status": "failed",
            "attempts": 2,
            "message_id": None,
            "failure_code": "network_error",
            "failure_reason": "Сеть недоступна",
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
            "status": "completed",
            "outcome": "succeeded",
            "failure_code": None,
            "started_at": "2026-08-12T07:00:00Z",
            "finished_at": "2026-08-12T07:00:12Z",
            "duration": 12,
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
        if request.method == "POST":
            route.fulfill(status=202 if path.endswith("run-once") else 200, content_type="application/json", body='{"status":"accepted"}')
            return
        payload = FIXTURES.get(path)
        route.fulfill(
            status=200 if payload is not None else 404,
            content_type="application/json",
            body=json.dumps(payload or {"code": "not_found"}),
        )

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


def test_loading_error_retry_and_empty_are_explicit(browser: Browser, base_url: str) -> None:
    # Break caught: an unavailable API leaks demo cards or retry cannot recover the selected screen.
    inspected = browser.new_page()
    calls = 0

    def handle(route: Route) -> None:
        nonlocal calls
        if route.request.url.endswith("/bootstrap"):
            route.fulfill(json=FIXTURES["/api/v1/bootstrap"])
        elif calls == 0:
            calls += 1
            route.fulfill(status=503, json={"code": "service_unavailable"})
        else:
            route.fulfill(json={"items": []})

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#materials")
        assert inspected.locator("[data-loading]").count() or inspected.get_by_text("Не удалось загрузить", exact=False).is_visible()
        assert inspected.get_by_text("Не удалось загрузить", exact=False).is_visible()
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
        duration = inspected.locator("[data-screen]").evaluate("element => getComputedStyle(element).animationDuration")
        assert duration in {"0s", "1e-05s"}
    finally:
        inspected.close()


def test_timeline_and_logo_keep_approved_optical_alignment(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/#overview")
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

    page.goto(f"{base_url}/#queue")
    geometry = page.locator(".timeline").evaluate("""element => {
        const timeline = element.getBoundingClientRect();
        const marker = element.querySelector('.timeline-marker').getBoundingClientRect();
        const rule = getComputedStyle(element, '::before');
        return {ruleX: timeline.x + parseFloat(rule.left), markerX: marker.x + marker.width / 2};
    }""")
    assert geometry["ruleX"] == pytest.approx(geometry["markerX"], abs=1)


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
