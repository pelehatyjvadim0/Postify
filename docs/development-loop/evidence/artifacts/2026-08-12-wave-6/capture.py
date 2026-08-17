from __future__ import annotations

import functools
from hashlib import sha256
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from playwright.sync_api import Route, sync_playwright


ROOT = Path(__file__).resolve().parents[5]
OUTPUT = Path(__file__).resolve().parent
STATIC = ROOT / "src/postify/web/static"
ROUTES = ("overview", "materials", "review", "queue", "publications", "journal", "settings")
VIEWPORTS = {"desktop": (1440, 1000), "mobile": (360, 800)}


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from tests.ui_mockup.test_browser_flows import FIXTURES

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=STATIC)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    entries: list[dict[str, object]] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("POSTIFY_CHROME", "/usr/bin/google-chrome"),
                headless=True,
                args=["--no-sandbox"],
            )
            try:
                for viewport, (width, height) in VIEWPORTS.items():
                    for screen in ROUTES:
                        page = browser.new_page(viewport={"width": width, "height": height})
                        install_api(page, FIXTURES)
                        page.goto(f"{base_url}/#{screen}")
                        page.locator(f'[data-screen="{screen}"]:not([data-loading])').wait_for()
                        entries.append(capture(page, f"{viewport}-{screen}.png", screen, viewport, "ready"))
                        page.close()

                loading = browser.new_page(viewport={"width": 1440, "height": 1000})
                loading.add_init_script("window.fetch = () => new Promise(() => {})")
                loading.goto(f"{base_url}/#journal", wait_until="domcontentloaded")
                loading.locator("[data-loading]").wait_for()
                entries.append(capture(loading, "desktop-loading.png", "journal", "desktop", "loading"))
                loading.close()

                error = browser.new_page(viewport={"width": 360, "height": 800})
                error.route("**/api/v1/**", lambda route: route.fulfill(status=503, json={"code": "service_unavailable"}))
                error.goto(f"{base_url}/#overview")
                error.locator(".error-state").wait_for()
                entries.append(capture(error, "mobile-error.png", "overview", "mobile", "error"))
                error.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    manifest = {
        "schema_version": 1,
        "capture_command": "uv run python docs/development-loop/evidence/artifacts/2026-08-12-wave-6/capture.py",
        "product_commit": subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%H",
                "--",
                "src/postify",
                "tests",
                "README.md",
                ".env.example",
                "pyproject.toml",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "captures": entries,
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )


def install_api(page, fixtures: dict[str, object]) -> None:
    def handle(route: Route) -> None:
        request = route.request
        path = "/" + request.url.split("/", 3)[-1].split("?", 1)[0]
        if request.method in {"POST", "PUT", "DELETE"}:
            route.fulfill(status=200, json={"status": "accepted"})
            return
        payload = fixtures.get(path)
        route.fulfill(status=200 if payload is not None else 404, json=payload or {"code": "not_found"})

    page.route("**/api/v1/**", handle)


def capture(page, filename: str, route: str, viewport: str, state: str) -> dict[str, object]:
    target = OUTPUT / filename
    page.wait_for_timeout(500)
    page.screenshot(path=target, full_page=False)
    dimensions = page.evaluate(
        """() => ({scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth,
                    scrollHeight: document.documentElement.scrollHeight})"""
    )
    return {
        "path": filename,
        "route": route,
        "viewport": viewport,
        "state": state,
        "sha256": sha256(target.read_bytes()).hexdigest(),
        "bytes": target.stat().st_size,
        "width": page.viewport_size["width"],
        "height": page.viewport_size["height"],
        **dimensions,
        "horizontal_overflow": dimensions["scrollWidth"] > dimensions["clientWidth"],
        "checks": {
            "overflow_free": dimensions["scrollWidth"] <= dimensions["clientWidth"]
        },
    }


if __name__ == "__main__":
    main()
