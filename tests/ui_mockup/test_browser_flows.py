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
    expect(page.get_by_text("Правила публикации", exact=True)).to_have_count(0)


def test_source_schedule_uses_human_readable_choices(page_factory, base_url):
    page = page_factory()
    install_api(page)
    page.goto(f"{base_url}/#settings")
    page.locator('[data-settings-section="schedule"] summary').click()
    schedule = page.locator("[data-source-schedule-id]").first
    expect(schedule).to_have_value("0 7 * * *")
    expect(schedule.locator("option:checked")).to_have_text("Каждый день в 07:00")


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
    expect(page.get_by_text("Доступно до одобрения", exact=True)).to_be_visible()


@pytest.mark.parametrize("width", [360, 1280])
def test_list_opens_modal_and_calendar_renders_selected_post_below_it(page_factory, base_url, width):
    page = page_factory(viewport={"width": width, "height": 900})
    page.clock.install(time=datetime(2026, 9, 5, 9, tzinfo=timezone.utc))
    fixtures = fixture_payloads()
    fixtures[f"{PROJECT}/packages"]["items"][0].update(status="approved", scheduled_at="2026-09-05T12:00:00Z", route_id=1)
    fixtures[f"{PROJECT}/packages/9001"].update(status="approved", scheduled_at="2026-09-05T12:00:00Z", route_id=1)
    install_api(page, fixtures=fixtures)
    page.goto(f"{base_url}/#review")

    page.locator('[data-work-stage="all"]').click()
    page.locator('[data-action="open-package"]').click()
    expect(page.locator("#detail-layer")).to_have_attribute("open", "")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator('[data-action="close-detail"]').click()

    page.locator('[data-work-view="calendar"]').click()
    page.locator('[data-work-key="post-9001"]').click()
    expect(page.locator(".work-calendar + .work-editor")).to_be_visible()
    expect(page.locator("#detail-layer")).not_to_have_attribute("open", "")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_calendar_ignores_late_response_from_previously_selected_post(page_factory, base_url):
    page = page_factory(viewport={"width": 1280, "height": 900})
    page.clock.install(time=datetime(2026, 9, 5, 9, tzinfo=timezone.utc))
    fixtures = fixture_payloads()
    first = fixtures[f"{PROJECT}/packages"]["items"][0]
    first.update(status="approved", scheduled_at="2026-09-05T12:00:00Z", route_id=1, post_text="Первый пост")
    second = dict(first, package_id=9002, post_text="Второй пост", scheduled_at="2026-09-05T13:00:00Z")
    fixtures[f"{PROJECT}/packages"]["items"].append(second)
    fixtures[f"{PROJECT}/packages/9001"].update(first)
    fixtures[f"{PROJECT}/packages/9002"] = {**fixtures[f"{PROJECT}/packages/9001"], **second}
    held = []

    def api(route):
        path = urlsplit(route.request.url).path
        if path == f"{PROJECT}/packages/9001":
            held.append(route)
        else:
            route.fulfill(json=fixtures.get(path, {"items": []}))

    page.route("**/api/v1/**", api)
    page.goto(f"{base_url}/#review")
    page.locator('[data-work-view="calendar"]').click()
    page.locator('[data-work-key="post-9001"]').click()
    page.locator('[data-work-key="post-9002"]').click()
    expect(page.locator("#work-editor")).to_contain_text("Второй пост")
    held.pop().fulfill(json=fixtures[f"{PROJECT}/packages/9001"])
    page.wait_for_timeout(50)
    expect(page.locator("#work-editor")).to_contain_text("Второй пост")


def test_reject_post_reports_success_and_calls_exact_package(page_factory, base_url):
    page = page_factory()
    calls = []
    install_api(page, calls)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[data-action="reject-package"]').click()
    expect(page.get_by_text("Пост отклонён", exact=True)).to_be_visible()
    assert any(call.method == "POST" and call.path == f"{PROJECT}/packages/9001/reject" for call in calls)


def test_published_post_has_no_rewrite_or_date_controls(page_factory, base_url):
    fixtures = fixture_payloads()
    fixtures[f"{PROJECT}/packages"]["items"][0].update(status="published", scheduled_at="2026-09-05T12:00:00Z", route_id=1)
    fixtures[f"{PROJECT}/packages/9001"].update(status="published", scheduled_at="2026-09-05T12:00:00Z", route_id=1)
    page = page_factory()
    install_api(page, fixtures=fixtures)
    page.goto(f"{base_url}/#review")
    page.locator('[data-work-stage="published"]').click()
    page.locator('[data-action="open-package"]').click()
    expect(page.get_by_text("План публикации", exact=True)).to_be_visible()
    expect(page.locator('[data-action="regenerate-post"]')).to_have_count(0)
    expect(page.locator('[data-action="edit-package-plan"]')).to_have_count(0)
    expect(page.locator('[name="scheduled_local"]')).to_have_count(0)


def test_published_delivery_overrides_stale_package_review_status(page_factory, base_url):
    fixtures = fixture_payloads()
    fixtures[f"{PROJECT}/packages/9001"].update(
        status="awaiting_review", delivery_status="published", scheduled_at="2026-09-05T12:00:00Z", route_id=1
    )
    page = page_factory()
    install_api(page, fixtures=fixtures)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    expect(page.locator('#detail-content .status-badge--published')).to_have_count(1)
    expect(page.locator('#detail-content').get_by_text("Ждёт проверки", exact=True)).to_have_count(0)
    expect(page.locator('#detail-content [data-action="approve-package"]')).to_have_count(0)
    expect(page.locator('#detail-content [data-action="reject-package"]')).to_have_count(0)
    expect(page.locator('#detail-content [data-action="edit-package-plan"]')).to_have_count(0)
