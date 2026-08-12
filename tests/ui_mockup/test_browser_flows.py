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
