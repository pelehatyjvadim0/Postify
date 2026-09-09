from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.ui_mockup.browser_support import PROJECT, fixture_payloads, install_api, install_settings_api


@pytest.mark.parametrize("width", [360, 1280])
def test_workspace_navigation_keeps_connections_after_delayed_workspace_response(page_factory, base_url, width):
    """A late workspace response must never repaint the connections screen."""
    page = page_factory(viewport={"width": width, "height": 900})
    fixed_now = datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc)
    page.clock.install(time=fixed_now)
    fixtures = fixture_payloads()
    scheduled_at = "2026-09-05T12:00:00Z"
    fixtures[f"{PROJECT}/packages"]["items"][0].update(status="approved", scheduled_at=scheduled_at, route_id=1)
    held = []
    delay_next_packages = False

    def handle(route):
        nonlocal delay_next_packages
        path = urlsplit(route.request.url).path
        if path == f"{PROJECT}/packages" and delay_next_packages:
            delay_next_packages = False
            held.append(route)
            return
        route.fulfill(json=fixtures.get(path, {}))

    page.route("**/api/v1/**", handle)
    page.goto(f"{base_url}/#review")
    page.locator('[data-work-stage="all"]').click()
    page.locator('[data-work-view="calendar"]').click()
    expect(page.locator(".work-calendar")).to_be_visible()
    expect(page.locator('[data-work-key="post-9001"]')).to_be_visible()

    page.evaluate("location.hash = '#connections'")
    expect(page.get_by_role("heading", name="Подключения")).to_be_visible()
    delay_next_packages = True
    page.evaluate("location.hash = '#review'")
    page.locator('[data-screen="review"][data-loading="true"]').wait_for()
    page.evaluate("location.hash = '#connections'")
    expect(page.get_by_role("heading", name="Подключения")).to_be_visible()
    channel_name = page.locator(".connections-screen .resource-heading strong").filter(has_text="Основной канал")
    expect(channel_name).to_be_visible()

    held.pop().fulfill(json=fixtures[f"{PROJECT}/packages"])
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(page.get_by_role("heading", name="Подключения")).to_be_visible()
    expect(channel_name).to_be_visible()

    page.evaluate("location.hash = '#settings'")
    expect(page.get_by_role("heading", name="Настройки")).to_be_visible()
    page.evaluate("location.hash = '#review'")
    expect(page.locator('[data-work-key="post-9001"]')).to_be_visible()


def test_new_search_completes_once_and_journal_remains_accessible(page_factory, base_url):
    page = page_factory(viewport={"width": 1280, "height": 900})
    calls = []
    install_api(page, calls)

    page.goto(f"{base_url}/#review")
    page.locator('[data-action="new-run"]').click()
    expect(page.get_by_text("Поиск завершён", exact=True)).to_be_visible()
    search_calls = [call for call in calls if call.method == "POST" and call.path == f"{PROJECT}/operations/search"]
    assert len(search_calls) == 1

    page.evaluate("location.hash = '#journal'")
    expect(page.get_by_role("heading", name="Журнал работы")).to_be_visible()
    expect(page.locator('[data-action="open-run"][data-id="9001"]')).to_be_visible()
    expect(page.locator('[data-action="open-run"][data-id="9001"]')).to_contain_text("Успешно")


def install_plan_api(page, *, fail_save=False, fail_network_once=False, fail_csrf_once=False,
                     scheduled_at=None, approve_error=None, routes=None, delivery_status=None,
                     status="awaiting_review"):
    fixtures = fixture_payloads()
    detail = fixtures[f"{PROJECT}/packages/9001"]
    detail.update(original_text="نشر الفريق 12 تحديثًا", post_text="Команда выпустила 12 обновлений.",
                  scheduled_at=scheduled_at, route_id=8 if scheduled_at else None, timezone="Europe/Moscow",
                  routes=routes if routes is not None else [{"id": 8, "name": "Новости"}, {"id": 9, "name": "Другой канал"}],
                  delivery_status=delivery_status, status=status, media_available=False)
    calls = []
    network_failed = False
    csrf_failed = False

    def handle(route):
        nonlocal network_failed, csrf_failed, detail
        path = urlsplit(route.request.url).path
        method = route.request.method
        if method != "GET":
            calls.append((method, path, route.request.post_data_json if route.request.post_data else None))
        if method == "PATCH":
            if fail_network_once and not network_failed:
                network_failed = True
                route.abort("connectionreset")
                return
            if fail_csrf_once and not csrf_failed:
                csrf_failed = True
                fixtures["/api/v1/bootstrap"]["csrfToken"] = "refreshed-capability"
                route.fulfill(status=403, json={"code": "csrf_required"})
                return
            if fail_csrf_once:
                assert route.request.headers["x-postify-csrf"] == "refreshed-capability"
            if fail_save:
                route.fulfill(status=409, json={"code": "plan_conflict"})
                return
            detail.update(route.request.post_data_json)
            detail["status"] = "awaiting_review"
            fixtures[f"{PROJECT}/packages"]["items"][0].update(detail)
            route.fulfill(json=detail)
        elif path.endswith("/regenerate"):
            replacement = dict(detail, package_id=9002, previous_package_id=9001, post_text="Новая версия поста")
            detail["replacement_package_id"] = 9002
            detail = replacement
            fixtures[f"{PROJECT}/packages/9002"] = replacement
            fixtures[f"{PROJECT}/packages"]["items"][0].update(replacement)
            route.fulfill(status=202, json={"operationRunId": 100})
        elif path.endswith("/operations/100"):
            route.fulfill(json={"status": "succeeded"})
        elif path.endswith("/approve"):
            if approve_error:
                route.fulfill(status=409, json={"code": approve_error})
                return
            detail["status"] = "approved"
            fixtures[f"{PROJECT}/packages"]["items"][0].update(detail)
            route.fulfill(json=detail)
        else:
            route.fulfill(json=fixtures.get(path, {}))

    page.route("**/api/v1/**", handle)
    return calls


@pytest.mark.parametrize("width", [360, 1280])
@pytest.mark.parametrize("timing", ["past", "now", "expires_while_open", "server_expired"])
def test_expired_approval_requests_a_new_date(page_factory, base_url, width, timing):
    page = page_factory(viewport={"width": width, "height": 900})
    page.clock.install(time=datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc))
    scheduled_at = {
        "past": "2026-09-05T09:00:00Z",
        "now": "2026-09-09T09:00:00Z",
        "expires_while_open": "2026-09-09T09:01:00Z",
        "server_expired": "2026-09-09T09:01:00Z",
    }[timing]
    calls = install_plan_api(page, scheduled_at=scheduled_at,
                             approve_error="publication_plan_expired" if timing == "server_expired" else None)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    if timing == "expires_while_open":
        page.clock.fast_forward(61_000)
    page.locator('[data-action="approve-package"]').click()

    expect(page.locator('[data-plan-error]')).to_contain_text("Измените дату публикации, прежде чем одобрить пост.")
    expect(page.locator('[name="scheduled_local"]')).to_be_visible()
    expect(page.locator('#detail-content')).to_contain_text("Ждёт проверки")
    assert calls == ([("POST", f"{PROJECT}/packages/9001/approve", None)] if timing == "server_expired" else [])
    if timing != "server_expired":
        page.locator('[name="scheduled_local"]').fill("2026-09-10T12:00")
        page.get_by_role("button", name="Сохранить план").click()
        expect(page.get_by_text("План сохранён", exact=True)).to_be_visible()
        page.locator('[data-action="approve-package"]').click()
        expect(page.get_by_text("Пост одобрен", exact=True)).to_be_visible()
        assert calls[-1] == ("POST", f"{PROJECT}/packages/9001/approve", None)


@pytest.mark.parametrize("width", [360, 1280])
def test_plan_roundtrip_uses_project_timezone_and_requires_approval(page_factory, base_url, width):
    page = page_factory(viewport={"width": width, "height": 900})
    calls = install_plan_api(page)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.get_by_text("Оригинал", exact=True).click()
    expect(page.get_by_text("نشر الفريق 12 تحديثًا", exact=True)).to_be_visible()
    expect(page.locator('[data-action="approve-package"]')).to_be_disabled()
    page.locator('[name="scheduled_local"]').fill("2099-09-05T12:30")
    page.locator('[name="route_id"]').select_option("8")
    page.get_by_role("button", name="Сохранить план").click()
    expect(page.get_by_text("План сохранён", exact=True)).to_be_visible()
    assert calls == [("PATCH", f"{PROJECT}/packages/9001/plan",
                      {"scheduled_at": "2099-09-05T09:30:00.000Z", "route_id": 8})]
    expect(page.locator('[data-action="approve-package"]')).to_be_enabled()
    page.reload()
    page.locator('[data-action="open-package"]').click()
    expect(page.get_by_text("Публикация через", exact=False)).to_be_visible()
    page.locator('[data-action="edit-package-plan"]').click()
    expect(page.locator('[name="scheduled_local"]')).to_have_value("2099-09-05T12:30")
    expect(page.locator('[name="route_id"]')).to_have_value("8")
    page.locator('[data-action="approve-package"]').click()
    expect(page.get_by_text("Пост одобрен", exact=True)).to_be_visible()
    assert calls[-1] == ("POST", f"{PROJECT}/packages/9001/approve", None)
    page.locator('[data-work-stage="plan"]').click()
    expect(page.locator('[data-work-key="post-9001"]')).to_contain_text("Одобрен")


def test_failed_plan_save_preserves_draft_and_disabled_approval(page_factory, base_url):
    page = page_factory(viewport={"width": 1280, "height": 900})
    calls = install_plan_api(page, fail_save=True)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[name="route_id"]').select_option("8")
    page.locator('[name="scheduled_local"]').fill("2099-09-05T12:30")
    page.get_by_role("button", name="Сохранить план").click()
    expect(page.locator('[data-plan-error]')).to_contain_text("План не сохранён")
    expect(page.locator('[name="scheduled_local"]')).to_have_value("2099-09-05T12:30")
    expect(page.locator('[name="route_id"]')).to_have_value("8")
    expect(page.locator('[data-action="approve-package"]')).to_be_disabled()
    assert calls == [("PATCH", f"{PROJECT}/packages/9001/plan",
                      {"scheduled_at": "2099-09-05T09:30:00.000Z", "route_id": 8})]


def test_plan_save_retries_one_transient_network_failure(page_factory, base_url):
    page = page_factory()
    calls = install_plan_api(page, fail_network_once=True)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[name="scheduled_local"]').fill("2099-09-05T12:30")
    page.locator('[name="route_id"]').select_option("8")
    page.get_by_role("button", name="Сохранить план").click()
    expect(page.get_by_text("План сохранён", exact=True)).to_be_visible()
    assert [call[:2] for call in calls] == [
        ("PATCH", f"{PROJECT}/packages/9001/plan"),
        ("PATCH", f"{PROJECT}/packages/9001/plan"),
    ]


def test_plan_save_refreshes_expired_csrf_capability(page_factory, base_url):
    page = page_factory()
    calls = install_plan_api(page, fail_csrf_once=True)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[name="scheduled_local"]').fill("2099-09-05T12:30")
    page.locator('[name="route_id"]').select_option("8")
    page.get_by_role("button", name="Сохранить план").click()
    expect(page.get_by_text("План сохранён", exact=True)).to_be_visible()
    assert [call[:2] for call in calls] == [
        ("PATCH", f"{PROJECT}/packages/9001/plan"),
        ("PATCH", f"{PROJECT}/packages/9001/plan"),
    ]


@pytest.mark.parametrize("field", ["date", "route", "both"])
@pytest.mark.parametrize("resolution", ["save", "cancel"])
def test_rewrite_preserves_unsaved_plan_and_requires_resolution(page_factory, base_url, field, resolution):
    page = page_factory()
    calls = install_plan_api(page, scheduled_at="2099-09-05T09:30:00Z")
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[data-action="edit-package-plan"]').click()
    date = "2099-09-06T12:30" if field in {"date", "both"} else "2099-09-05T12:30"
    route = "9" if field in {"route", "both"} else "8"
    page.locator('[name="scheduled_local"]').fill(date)
    page.locator('[name="route_id"]').select_option(route)
    expect(page.locator('[data-action="approve-package"]')).to_be_disabled()
    page.locator('[data-action="regenerate-post"]').click()
    expect(page.locator('.rewrite-region .post-text')).to_have_text("Новая версия поста")
    expect(page.locator('[name="scheduled_local"]')).to_be_visible()
    expect(page.locator('[name="scheduled_local"]')).to_have_value(date)
    expect(page.locator('[name="route_id"]')).to_have_value(route)
    expect(page.locator('[data-action="approve-package"]')).to_be_disabled()
    assert calls == [("POST", f"{PROJECT}/packages/9001/regenerate", None)]

    if resolution == "save":
        page.get_by_role("button", name="Сохранить план").click()
        expect(page.get_by_text("План сохранён", exact=True)).to_be_visible()
        expected_date = "2099-09-06T09:30:00.000Z" if field in {"date", "both"} else "2099-09-05T09:30:00.000Z"
        assert calls[-1] == ("PATCH", f"{PROJECT}/packages/9002/plan", {"scheduled_at": expected_date, "route_id": int(route)})
    else:
        page.locator('[data-action="cancel-package-plan"]').click()
        page.locator('[data-action="edit-package-plan"]').click()
        expect(page.locator('[name="scheduled_local"]')).to_have_value("2099-09-05T12:30")
        expect(page.locator('[name="route_id"]')).to_have_value("8")
        assert len(calls) == 1
    expect(page.locator('[data-action="approve-package"]')).to_be_enabled()
    page.locator('[data-action="approve-package"]').click()
    expect(page.get_by_text("Пост одобрен", exact=True)).to_be_visible()
    assert calls[-1] == ("POST", f"{PROJECT}/packages/9002/approve", None)


def test_rewrite_without_plan_changes_keeps_approval_available(page_factory, base_url):
    page = page_factory()
    calls = install_plan_api(page, scheduled_at="2099-09-05T09:30:00Z")
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[data-action="regenerate-post"]').click()
    expect(page.locator('.rewrite-region .post-text')).to_have_text("Новая версия поста")
    expect(page.locator('[data-action="approve-package"]')).to_be_enabled()
    expect(page.locator('[data-plan-fields]')).to_be_hidden()
    assert calls == [("POST", f"{PROJECT}/packages/9001/regenerate", None)]


@pytest.mark.parametrize("width", [360, 1280])
def test_cancel_restores_saved_plan_and_approval_after_failed_save(page_factory, base_url, width):
    page = page_factory(viewport={"width": width, "height": 900})
    calls = install_plan_api(page, scheduled_at="2099-09-05T09:30:00Z", fail_save=True)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[data-action="edit-package-plan"]').click()
    page.locator('[name="scheduled_local"]').fill("2099-09-06T12:30")
    page.locator('[name="route_id"]').select_option("9")
    page.get_by_role("button", name="Сохранить план").click()
    expect(page.locator('[data-plan-error]')).not_to_be_empty()
    page.locator('[data-action="cancel-package-plan"]').click()
    expect(page.locator('[data-plan-error]')).to_be_empty()
    expect(page.locator('[data-action="approve-package"]')).to_be_enabled()
    page.locator('[data-action="edit-package-plan"]').click()
    expect(page.locator('[name="scheduled_local"]')).to_have_value("2099-09-05T12:30")
    expect(page.locator('[name="route_id"]')).to_have_value("8")
    page.locator('[data-action="approve-package"]').click()
    expect(page.get_by_text("Пост одобрен", exact=True)).to_be_visible()
    assert len(calls) == 2


@pytest.mark.parametrize("width", [360, 1280])
@pytest.mark.parametrize("status", ["awaiting_review", "approved"])
def test_unavailable_channel_can_be_replaced_and_requires_approval(page_factory, base_url, width, status):
    page = page_factory(viewport={"width": width, "height": 900})
    calls = install_plan_api(page, scheduled_at="2099-09-05T09:30:00Z", status=status,
                             routes=[{"id": 9, "name": "Другой канал"}])
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[data-action="edit-package-plan"]').click()
    expect(page.locator('[name="route_id"]')).to_be_visible()
    expect(page.locator('[name="route_id"] option:checked')).to_have_text("Канал недоступен")
    page.locator('[name="route_id"]').select_option("9")
    page.locator('[data-action="cancel-package-plan"]').click()
    if status == "awaiting_review":
        expect(page.locator('[data-action="approve-package"]')).to_be_disabled()
    page.locator('[data-action="edit-package-plan"]').click()
    expect(page.locator('[name="route_id"]')).to_have_value("8")
    page.locator('[name="route_id"]').select_option("9")
    page.get_by_role("button", name="Сохранить план").click()
    expect(page.get_by_text("План сохранён", exact=True)).to_be_visible()
    expect(page.locator('[data-action="approve-package"]')).to_be_enabled()
    page.locator('[data-action="approve-package"]').click()
    expect(page.get_by_text("Пост одобрен", exact=True)).to_be_visible()
    assert calls == [
        ("PATCH", f"{PROJECT}/packages/9001/plan", {"scheduled_at": "2099-09-05T09:30:00.000Z", "route_id": 9}),
        ("POST", f"{PROJECT}/packages/9001/approve", None),
    ]


@pytest.mark.parametrize("delivery_status", ["failed", "retryable"])
def test_channel_stays_fixed_after_delivery_attempt(page_factory, base_url, delivery_status):
    page = page_factory()
    install_plan_api(page, scheduled_at="2099-09-05T09:30:00Z", delivery_status=delivery_status)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    page.locator('[data-action="edit-package-plan"]').click()
    expect(page.locator('select[name="route_id"]')).to_have_count(0)
    expect(page.locator('[name="route_id"]')).to_have_value("8")
    expect(page.locator('[name="scheduled_local"]')).to_be_visible()


def test_settings_only_save_post_tone(page_factory, base_url):
    page = page_factory()
    calls = []
    install_settings_api(page, calls)
    page.goto(f"{base_url}/#settings")
    page.locator('[data-settings-section="advanced"] summary').click()
    page.get_by_label("Стиль поста", exact=True).fill("Кратко и спокойно")
    page.locator('[data-settings-form="advanced"] [type="submit"]').click()
    expect(page.get_by_text("Настройки сохранены", exact=True)).to_be_visible()
    assert [(call.method, call.path, call.body) for call in calls] == [
        ("PUT", f"{PROJECT}/settings/configuration", {"tone": "Кратко и спокойно"})]
    page.reload()
    page.locator('[data-settings-section="advanced"] summary').click()
    expect(page.get_by_label("Стиль поста", exact=True)).to_have_value("Кратко и спокойно")


def test_material_failure_preserves_original_and_retries_exact_attempt(page_factory, base_url):
    page = page_factory()
    fixtures = fixture_payloads()
    fixtures[f"{PROJECT}/materials"]["items"][0].update(
        generation_status="failed", generation_failure_code="gemini_timeout",
        original_text="نشر الفريق 12 تحديثًا", retry_attempt_id=731)
    calls = []
    install_api(page, calls, fixtures=fixtures)
    page.goto(f"{base_url}/#review")
    page.locator('[data-work-stage="error"]').click()
    page.locator('[data-action="open-material"]').click()
    detail = page.locator("#detail-content")
    expect(detail.get_by_text("نشر الفريق 12 تحديثًا", exact=True)).to_be_visible()
    expect(detail.get_by_text("Не удалось подготовить пост вовремя. Повторите позже.", exact=True)).to_be_visible()
    page.locator('[data-action="retry-analysis"]').click()
    expect(page.get_by_text("Пост подготовлен заново", exact=True)).to_be_visible()
    assert [(call.method, call.path, call.body) for call in calls if call.method == "POST"] == [
        ("POST", f"{PROJECT}/attempts/731/retry-analysis", None)]
