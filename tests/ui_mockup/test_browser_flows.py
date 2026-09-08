from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.ui_mockup.browser_support import PROJECT, fixture_payloads, install_api, install_settings_api


@pytest.mark.parametrize("width", [360, 1280])
def test_workspace_calendar_connections_and_settings_keep_current_screen(page_factory, base_url, width):
    page = page_factory(viewport={"width": width, "height": 900})
    page.clock.install(time=datetime(2026, 9, 5, 9, tzinfo=timezone.utc))
    fixtures = fixture_payloads()
    fixtures[f"{PROJECT}/packages"]["items"][0].update(status="approved", scheduled_at="2026-09-05T12:00:00Z", route_id=1)
    def api(route):
        path = urlsplit(route.request.url).path
        route.fulfill(json=fixtures.get(path, {"items": []}))
    page.route("**/api/v1/**", api)
    page.goto(f"{base_url}/#review")
    page.locator('[data-work-view="calendar"]').click()
    expect(page.locator('.work-calendar')).to_be_visible()
    expect(page.locator('[data-work-key="post-9001"]')).to_be_visible()
    page.evaluate("location.hash='#connections'")
    expect(page.get_by_role("heading", name="Подключения")).to_be_visible()
    expect(page.locator('.resource-heading strong').filter(has_text="Основной канал")).to_be_visible()
    page.evaluate("location.hash='#settings'")
    expect(page.get_by_role("heading", name="Настройки")).to_be_visible()


def test_new_search_is_single_owner_command_and_journal_is_available(page_factory, base_url):
    page = page_factory(); calls = []; install_api(page, calls)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="new-run"]').click()
    expect(page.get_by_text("Поиск завершён", exact=True)).to_be_visible()
    assert [(call.method, call.path) for call in calls if call.method == "POST"] == [("POST", f"{PROJECT}/operations/search")]
    page.evaluate("location.hash='#journal'")
    expect(page.get_by_role("heading", name="Журнал работы")).to_be_visible()


def test_connections_use_telegram_group_and_channel_check_is_bound_to_form(page_factory, base_url):
    page = page_factory(); calls = []
    install_settings_api(page, calls, channel_check={"connectionStatus": "failed", "reason": "Токен отклонён"})
    page.goto(f"{base_url}/#connections")
    page.locator('[data-settings-section="sources"] summary').click()
    expect(page.locator('[data-settings-form="sources"] [name="provider"]').first).to_have_value("telegram_group")
    channel = page.locator('[data-settings-form="channels"]').first
    expect(channel.get_by_role("button", name="Проверить канал")).to_be_visible()


def test_regeneration_is_available_before_approval(page_factory, base_url):
    page = page_factory()
    install_api(page)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    expect(page.get_by_role("button", name="Переписать пост")).to_be_enabled()


def test_regeneration_is_disabled_after_approval(page_factory, base_url):
    fixtures = fixture_payloads()
    fixtures[f"{PROJECT}/packages"]["items"][0]["status"] = "approved"
    fixtures[f"{PROJECT}/packages/9001"]["status"] = "approved"
    page = page_factory()
    install_api(page, fixtures=fixtures)
    page.goto(f"{base_url}/#review")
    page.locator('[data-work-stage="plan"]').click()
    page.locator('[data-action="open-package"]').click()
    expect(page.get_by_role("button", name="Переписать пост")).to_be_disabled()
    expect(page.get_by_text("Переписывание доступно до одобрения", exact=True)).to_be_visible()
