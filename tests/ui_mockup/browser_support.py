"""Reusable, state-isolated browser API fakes for the UI contract tests."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.sync_api import Page, Route
from tests.ui_mockup.fixture_data import FIXTURE_TEMPLATE, PIXEL_PNG


PROJECT = "/api/v1/projects/41"


@dataclass(frozen=True, slots=True, eq=False)
class HttpCall:
    method: str
    path: str
    body: object | None
    headers: dict[str, str]

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, tuple):
            return (self.method, self.path) == other
        if isinstance(other, dict):
            return all(getattr(self, key) == value for key, value in other.items())
        return isinstance(other, HttpCall) and (
            self.method, self.path, self.body, self.headers
        ) == (other.method, other.path, other.body, other.headers)


def fixture_payloads() -> dict[str, object]:
    """Return data that a test may safely change without leaking state."""
    return copy.deepcopy(FIXTURE_TEMPLATE)


def _path(route: Route) -> str:
    parsed = urlsplit(route.request.url)
    return f"{parsed.path}{f'?{parsed.query}' if parsed.query else ''}"


def install_api(
    page: Page,
    calls: list[HttpCall] | None = None,
    *,
    fixtures: dict[str, object] | None = None,
    failures: dict[str, int] | None = None,
    terminal_outcomes: dict[str, tuple[str, str | None]] | None = None,
) -> None:
    """Install a truthful accepted-operation fake with one running poll."""
    payloads = fixtures if fixtures is not None else fixture_payloads()
    failures = failures or {}
    terminal_outcomes = terminal_outcomes or {}
    polls: dict[int, int] = {}
    next_run = 100

    def handle(route: Route) -> None:
        nonlocal next_run
        path = _path(route)
        request = route.request
        body = request.post_data_json if request.post_data else None
        if calls is not None:
            calls.append(HttpCall(request.method, path, body, dict(request.headers)))
        if path in failures:
            route.fulfill(status=failures[path], json={"code": "service_unavailable"})
            return
        if path.startswith(f"{PROJECT}/operations/") and request.method == "GET":
            run_id = int(path.rsplit("/", 1)[1])
            polls[run_id] = polls.get(run_id, 0) + 1
            running = polls[run_id] == 1
            status, outcome = terminal_outcomes.get(path, ("succeeded", "completed"))
            route.fulfill(json={"run_id": run_id, "status": "running" if running else status, "outcome": None if running else outcome, "failure_code": None})
            return
        background = ("/operations/search", "/operations/publish-once", "/packages/load-more", "/retry-analysis", "/return-to-analysis", "/regenerate", "/media/replace", "/publish-now", "/deliveries/")
        if request.method == "POST" and any(token in path for token in background):
            next_run += 1
            route.fulfill(status=202, json={"status": "accepted", "operationRunId": next_run})
            return
        if "/media/packages/" in path:
            route.fulfill(status=200, content_type="image/png", body=PIXEL_PNG)
            return
        if request.method in {"POST", "PUT", "DELETE"}:
            route.fulfill(status=204 if request.method == "DELETE" else 200, json=None if request.method == "DELETE" else {"status": "ok"})
            return
        key = path.split("?", 1)[0]
        payload = payloads.get(key)
        route.fulfill(status=200 if payload is not None else 404, content_type="application/json", body=json.dumps(payload if payload is not None else {"code": "not_found"}))

    page.route("**/api/v1/**", handle)


def install_settings_api(
    page: Page,
    calls: list[HttpCall],
    *,
    initial_settings: dict[str, object] | None = None,
    failures: set[str] | None = None,
    channel_check: dict[str, object] | None = None,
) -> None:
    """Small stateful settings fake, including an application-level check result."""
    fixtures = fixture_payloads()
    if initial_settings is not None:
        fixtures[f"{PROJECT}/settings"] = copy.deepcopy(initial_settings)
    failures = failures or set()

    def handle(route: Route) -> None:
        path = _path(route)
        request = route.request
        body = request.post_data_json if request.post_data else None
        if request.method != "GET":
            calls.append(HttpCall(request.method, path, body, dict(request.headers)))
        if path in failures:
            route.fulfill(status=503, json={"code": "service_unavailable"})
        elif request.method == "GET":
            route.fulfill(json=fixtures.get(path.split("?", 1)[0], fixtures.get("/api/v1/bootstrap")))
        else:
            relative = path.split("?", 1)[0].removeprefix(f"{PROJECT}/")
            parts = relative.split("/")
            resource = parts[0]
            settings = fixtures[f"{PROJECT}/settings"]
            assert isinstance(settings, dict)
            if path.endswith("/check"):
                item = next(item for item in settings[resource] if item["id"] == int(parts[1]))
                result = channel_check or {"connectionStatus": "ok", "reason": ""}
                item["connection_status"] = result["connectionStatus"]
            elif request.method == "PUT" and resource == "settings":
                section = parts[1]
                if section == "main":
                    settings["project"].update(body or {})
                elif section == "configuration":
                    settings["project"]["configuration"].update(body or {})
                elif section == "schedule":
                    for kind in ("sources", "routes"):
                        for update in (body or {}).get(kind, []):
                            item = next(item for item in settings[kind] if item["id"] == update["id"])
                            item["schedule"] = ({"autopublish": update["autopublish"], "slots": update["slots"]} if kind == "routes" else update["schedule"])
                result = settings["project"]
            elif resource in {"sources", "ctas", "channels", "routes"}:
                items = settings[resource]
                if request.method == "POST" and len(parts) == 1:
                    result = {"id": max((item["id"] for item in items), default=0) + 1, **(body or {})}
                    if resource == "channels":
                        result.pop("token", None)
                        result.update({"connection_status": "unconfigured", "secretConfigured": bool((body or {}).get("token"))})
                    items.append(result)
                else:
                    item = next(item for item in items if item["id"] == int(parts[1]))
                    if request.method == "DELETE":
                        items.remove(item)
                        route.fulfill(status=204)
                        return
                    if path.endswith("/secret/remove"):
                        item.update({"secretConfigured": False, "connection_status": "unconfigured"})
                    else:
                        update = dict(body or {})
                        token = update.pop("token", None)
                        item.update(update)
                        if token:
                            item["secretConfigured"] = True
                    result = item
            else:
                result = body or {"status": "ok"}
            route.fulfill(json=result)

    page.route("**/api/v1/**", handle)
