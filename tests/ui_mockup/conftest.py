from __future__ import annotations

import contextlib
import functools
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

from tests.ui_mockup.browser_support import install_api


STATIC = Path(__file__).parents[2] / "src/postify/web/static"


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(STATIC)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    """Keep Playwright's sync dispatcher within one UI test module only.

    A session-scoped dispatcher leaves its asyncio loop active while unrelated
    synchronous FastAPI tests call ``asyncio.run`` later in the collection.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page_factory(browser: Browser):
    pages: list[tuple[Page, list[str]]] = []

    def create(**options) -> Page:
        page = browser.new_page(**options)
        errors: list[str] = []
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error" and not message.text.startswith("Failed to load resource:")
            else None,
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_default_timeout(3_000)
        pages.append((page, errors))
        return page

    yield create
    for page, _ in pages:
        with contextlib.suppress(Exception):
            page.close()
    assert [error for _, errors in pages for error in errors] == []


@pytest.fixture
def page(page_factory):
    """Default observable API page for flows without special responses."""
    browser_page = page_factory(viewport={"width": 1440, "height": 1000})
    install_api(browser_page)
    return browser_page
