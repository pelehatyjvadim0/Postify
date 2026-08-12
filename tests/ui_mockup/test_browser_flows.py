import contextlib
import functools
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, sync_playwright


ROOT = Path(__file__).parents[2]
MOCKUP = ROOT / "ui-mockup"


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(MOCKUP),
    )
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
    return playwright.chromium.launch(
        executable_path="/usr/bin/google-chrome",
        headless=True,
        args=["--no-sandbox"],
    )


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    browser_page = browser.new_page(viewport={"width": 1440, "height": 1000})
    console_errors: list[str] = []
    browser_page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    yield browser_page
    with contextlib.suppress(Exception):
        browser_page.close()
    assert console_errors == []


def test_all_working_sections_are_reachable(page: Page, base_url: str) -> None:
    page.goto(base_url)
    for route, title in {
        "overview": "Сегодня",
        "materials": "Материалы",
        "review": "Проверка",
        "queue": "Очередь публикаций",
        "publications": "История публикаций",
        "journal": "Журнал работы",
    }.items():
        page.locator(f'.app-nav [href="#{route}"]').click()
        assert page.locator("h1").inner_text() == title
        assert page.url.endswith(f"#{route}")
        assert page.locator("#screen-root [data-screen]").get_attribute(
            "data-screen"
        ) == route


def test_unknown_hash_returns_to_overview(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/#missing")

    assert page.locator("h1").inner_text() == "Сегодня"
    assert page.url.endswith("#overview")


def test_approve_updates_review_queue_and_overview(
    page: Page, base_url: str
) -> None:
    page.goto(f"{base_url}/#review")
    before = int(page.locator('[data-metric="needs-review"]').inner_text())

    page.locator('[data-action="open-package"]').first.click()
    page.locator('[data-action="approve-package"]').click()

    assert page.get_by_text("Пост одобрен", exact=True).is_visible()
    page.locator('.app-nav [href="#overview"]').click()
    assert int(page.locator('[data-metric="needs-review"]').inner_text()) == before - 1
    assert page.locator(".timeline-slot .slot-package").count() == 2


def test_material_filter_detail_escape_and_reset(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/#materials")
    page.locator('[data-filter="rejected"]').click()

    assert page.locator('[data-material-status="rejected"]').count() == 2
    assert page.locator('[data-material-status="selected"]').count() == 0

    opener = page.locator('[data-action="open-material"]').first
    opener.click()
    assert page.locator("#detail-layer[open]").is_visible()
    assert page.locator("#detail-layer").get_attribute("aria-modal") == "true"
    page.keyboard.press("Escape")
    assert not page.locator("#detail-layer").is_visible()
    assert opener.evaluate("element => element === document.activeElement")

    page.locator("#demo-reset").click()
    assert page.get_by_text("Демо-данные восстановлены", exact=True).is_visible()
    assert page.locator('[data-material-status="selected"]').count() == 4


def test_reject_requires_a_reason_and_removes_package_from_queue(
    page: Page, base_url: str
) -> None:
    page.goto(f"{base_url}/#review")
    before = int(page.locator('[data-metric="needs-review"]').inner_text())
    page.locator('[data-action="open-package"]').first.click()
    page.locator('[data-action="show-reject-form"]').click()

    page.locator('[data-action="reject-package"]').click()
    assert page.get_by_text("Укажите причину отклонения", exact=True).is_visible()
    page.locator("#reject-reason").fill("Слишком общий текст без конкретного примера")
    page.locator('[data-action="reject-package"]').click()

    assert page.get_by_text("Пост отклонён", exact=True).is_visible()
    assert int(page.locator('[data-metric="needs-review"]').inner_text()) == before - 1


@pytest.mark.parametrize(
    ("route", "action", "expected"),
    [
        ("publications", "open-delivery", "История попыток"),
        ("journal", "open-run", "Подробности запуска"),
    ],
)
def test_operational_details_open_in_the_shared_layer(
    page: Page, base_url: str, route: str, action: str, expected: str
) -> None:
    page.goto(f"{base_url}/#{route}")
    page.locator(f'[data-action="{action}"]').first.click()

    assert page.locator("#detail-layer[open]").is_visible()
    assert page.locator("#detail-title").inner_text() == expected


@pytest.mark.parametrize("width,height", [(360, 800), (768, 1024), (1440, 1000)])
@pytest.mark.parametrize(
    "route",
    ["overview", "materials", "review", "queue", "publications", "journal"],
)
def test_every_screen_has_no_horizontal_overflow(
    page: Page, base_url: str, width: int, height: int, route: str
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#{route}")

    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_mobile_navigation_and_detail_targets_are_touch_ready(
    page: Page, base_url: str
) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{base_url}/#review")

    assert page.locator(".sidebar").is_hidden()
    assert page.locator(".mobile-nav").is_visible()
    target_heights = page.locator(".mobile-nav a, .mobile-nav button").evaluate_all(
        "elements => elements.map(element => element.getBoundingClientRect().height)"
    )
    assert min(target_heights) >= 44

    page.locator('[data-action="open-package"]').first.click()
    bounds = page.locator("#detail-layer").bounding_box()
    assert bounds is not None
    assert bounds["width"] == pytest.approx(360, abs=1)
    assert bounds["height"] == pytest.approx(800, abs=1)


def test_mobile_review_thumbnail_does_not_cover_copy(
    page: Page, base_url: str
) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{base_url}/#review")
    card = page.locator(".content-card").first
    thumbnail = card.locator(".material-thumb").bounding_box()
    copy = card.locator(".content-card-copy").bounding_box()

    assert thumbnail is not None and copy is not None
    assert thumbnail["x"] + thumbnail["width"] <= copy["x"]


def test_mobile_package_keeps_both_editorial_actions_visible(
    page: Page, base_url: str
) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').first.click()

    assert page.locator('[data-action="show-reject-form"]').is_visible()
    assert page.locator('[data-action="approve-package"]').is_visible()


def test_reduced_motion_removes_visible_screen_transition(
    browser: Browser, base_url: str
) -> None:
    reduced_page = browser.new_page(
        viewport={"width": 1440, "height": 1000},
        reduced_motion="reduce",
    )
    try:
        reduced_page.goto(f"{base_url}/#overview")
        duration = reduced_page.locator("[data-screen]").evaluate(
            "element => getComputedStyle(element).animationDuration"
        )
        assert duration in {"0s", "1e-05s"}
    finally:
        reduced_page.close()


def test_journal_starts_with_operational_content_without_status_banner(
    page: Page, base_url: str
) -> None:
    page.goto(f"{base_url}/#journal")

    assert page.locator(".system-banner").count() == 0
    assert page.locator(".journal-layout").is_visible()


@pytest.mark.parametrize("width", [360, 1440])
@pytest.mark.parametrize("route", ["overview", "queue"])
def test_timeline_rule_runs_through_marker_centres(
    page: Page, base_url: str, width: int, route: str
) -> None:
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{base_url}/#{route}")
    geometry = page.locator(".timeline").first.evaluate(
        """element => {
            const timeline = element.getBoundingClientRect();
            const marker = element.querySelector('.timeline-marker').getBoundingClientRect();
            const rule = getComputedStyle(element, '::before');
            return {
                ruleX: timeline.x + parseFloat(rule.left),
                markerX: marker.x + marker.width / 2,
            };
        }"""
    )

    assert geometry["ruleX"] == pytest.approx(geometry["markerX"], abs=1)


def test_overview_summary_columns_and_logo_are_optically_aligned(
    page: Page, base_url: str
) -> None:
    page.goto(f"{base_url}/#overview")
    column_boxes = page.locator(".studio-strip > div").evaluate_all(
        "elements => elements.map(element => element.getBoundingClientRect().toJSON())"
    )
    brand_geometry = page.locator(".brand").evaluate(
        """element => {
            const mark = element.querySelector('.brand-mark').getBoundingClientRect();
            const name = element.querySelector('.brand-name').getBoundingClientRect();
            return {
                markCenter: mark.y + mark.height / 2,
                nameCenter: name.y + name.height / 2,
            };
        }"""
    )

    assert max(box["width"] for box in column_boxes) - min(
        box["width"] for box in column_boxes
    ) <= 1
    assert len({round(box["height"], 1) for box in column_boxes}) == 1
    assert brand_geometry["markCenter"] == pytest.approx(
        brand_geometry["nameCenter"], abs=1
    )
