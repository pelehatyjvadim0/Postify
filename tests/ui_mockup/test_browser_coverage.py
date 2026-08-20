from __future__ import annotations

from tests.ui_mockup.browser_support import HttpCall, fixture_payloads, install_api, install_settings_api


def test_unknown_hash_normalizes_navigation_and_material_filters_use_public_query(page_factory, base_url: str) -> None:
    page = page_factory()
    fixtures = fixture_payloads()
    fixtures["/api/v1/projects/41/materials"] = {"items": [{"candidate_id": 1, "source_name": "Источник", "title": "Материал", "decision_status": "selected"}]}
    calls: list[HttpCall] = []
    install_api(page, fixtures=fixtures, calls=calls)
    page.goto(f"{base_url}/#not-a-route")
    page.locator('[data-screen="overview"]:not([data-loading])').wait_for()
    assert page.url.endswith("/#overview")
    assert page.locator("h1").inner_text() == "Сегодня"
    assert page.locator('[data-route="overview"][aria-current="page"]').count() == 2
    page.goto(f"{base_url}/#materials")
    page.get_by_role("button", name="Выбраны").click()
    page.get_by_role("button", name="Отклонены").click()
    page.get_by_role("button", name="Все").click()
    paths = [call.path for call in calls if call.method == "GET" and "/materials" in call.path]
    assert paths[-3:] == ["/api/v1/projects/41/materials?status=selected", "/api/v1/projects/41/materials?status=rejected", "/api/v1/projects/41/materials"]


def test_stale_material_response_cannot_overwrite_new_route(page_factory, base_url: str) -> None:
    page = page_factory()
    page.add_init_script("""(() => {
      let releaseMaterials; window.__releaseMaterials = () => releaseMaterials();
      window.fetch = (url) => {
        const json = (value) => Promise.resolve(new Response(JSON.stringify(value), {status: 200}));
        if (url.endsWith('/bootstrap')) return json({csrfToken: 'token', activeProject: {id: 41, name: 'Проект'}, providers: {sources: [], channels: []}});
        if (url.includes('/materials')) return new Promise(resolve => { releaseMaterials = () => resolve(new Response(JSON.stringify({items: [{candidate_id: 1, source_name: 'late', title: 'STALE', decision_status: 'selected'}]}))); });
        if (url.includes('/queue')) return json({items: []});
        return json({candidate_total: 0, undecided_materials: 0, selected_materials: 0, package_total: 0, approved_packages: 0, published_today: 0, daily_analyses_started: 0, daily_packages_created: 0, signals: [], runtime: {}, recent_operations: []});
      };
    })()""")
    page.goto(f"{base_url}/#materials")
    page.locator('[data-screen="materials"][data-loading="true"]').wait_for()
    page.evaluate("location.hash = '#queue'")
    page.locator('[data-screen="queue"]:not([data-loading])').wait_for()
    page.evaluate("window.__releaseMaterials()")
    assert page.locator('[data-screen="queue"]').count() == 1
    assert page.get_by_text("STALE", exact=True).count() == 0


def test_list_screen_empty_branches_and_detail_escape_focus_lifecycle(page_factory, base_url: str) -> None:
    page = page_factory()
    fixtures = fixture_payloads()
    fixtures["/api/v1/projects/41/packages"] = {"items": [{"package_id": 9, "status": "awaiting_review", "post_text": "Пакет", "source_url": "https://example.test"}]}
    fixtures["/api/v1/projects/41/packages/9"] = {"package_id": 9, "status": "awaiting_review", "post_text": "<img src=x>", "source_url": "javascript:bad", "analysis": "ok", "media_available": False, "media_status": "unknown", "history": []}
    for resource in ("materials", "queue", "publications", "operations"):
        fixtures[f"/api/v1/projects/41/{resource}"] = {"items": []}
    install_api(page, fixtures=fixtures)
    for route, text in [("materials", "Материалов пока нет"), ("queue", "Очередь пока пуста"), ("publications", "Публикаций пока нет"), ("journal", "Запусков пока нет")]:
        page.goto(f"{base_url}/#{route}")
        page.locator(f'[data-screen="{route}"]').get_by_text(text, exact=True).wait_for()
    page.goto(f"{base_url}/#review")
    opener = page.locator('[data-action="open-package"]')
    opener.click()
    page.locator('#detail-layer[open]').wait_for()
    assert page.locator('#detail-content img[src="x"]').count() == 0
    page.keyboard.press("Escape")
    assert not page.locator("#detail-layer").evaluate("dialog => dialog.open")
    assert page.evaluate("document.activeElement === document.querySelector('[data-action=\"open-package\"]')")
    fixtures["/api/v1/projects/41/packages"] = {"items": []}
    page.goto(f"{base_url}/#overview")
    page.goto(f"{base_url}/#review")
    page.locator('[data-screen="review"]').get_by_text("Пакетов для проверки нет", exact=True).wait_for()


def test_channel_check_application_failure_is_attached_to_refreshed_form(page_factory, base_url: str) -> None:
    page = page_factory()
    calls: list[HttpCall] = []
    install_settings_api(page, calls, channel_check={"connectionStatus": "failed", "reason": "Токен отклонён"})
    page.goto(f"{base_url}/#settings")
    page.locator('[data-settings-section="channels"] > summary').click()
    button = page.get_by_role("button", name="Проверить канал")
    button.click()
    form = page.locator('[data-settings-form="channels"]').first
    error = form.locator("[data-settings-error]")
    error.get_by_text("Токен отклонён", exact=True).wait_for()
    assert form.get_by_role("button", name="Проверить канал").get_attribute("aria-describedby") == error.get_attribute("id")
    assert not page.get_by_text("Канал готов к публикации", exact=True).is_visible()


def test_rapid_background_click_emits_one_owner_command(page_factory, base_url: str) -> None:
    page = page_factory()
    fixtures = fixture_payloads()
    calls: list[HttpCall] = []
    install_api(page, fixtures=fixtures, calls=calls)
    page.goto(f"{base_url}/#overview")
    button = page.locator('[data-action="new-run"]')
    button.click()
    button.click(force=True)
    page.get_by_text("Поиск завершён", exact=True).wait_for()
    assert len([call for call in calls if call.method == "POST" and call.path.endswith("/operations/search")]) == 1


def test_package_failure_close_paths_and_empty_controls_are_user_actionable(page_factory, base_url: str) -> None:
    page = page_factory()
    fixtures = fixture_payloads()
    fixtures["/api/v1/projects/41/packages"] = {"items": [{"package_id": 9, "status": "awaiting_review", "post_text": "Пакет", "source_url": "https://example.test"}]}
    install_api(page, fixtures=fixtures, failures={"/api/v1/projects/41/packages/9": 503})
    page.goto(f"{base_url}/#review")
    opener = page.locator('[data-action="open-package"]')
    opener.click()
    dialog = page.locator("#detail-layer")
    dialog.get_by_text("Не удалось загрузить пакет", exact=False).wait_for()
    assert dialog.evaluate("node => node.open")
    assert dialog.get_by_role("button", name="Закрыть").is_visible()
    assert dialog.get_by_role("button", name="Одобрить").count() == 0
    dialog.get_by_role("button", name="Закрыть").click()
    assert not dialog.evaluate("node => node.open")
    assert page.evaluate("document.activeElement === document.querySelector('[data-action=\"open-package\"]')")
    empty_page = page_factory()
    empty_fixtures = fixture_payloads()
    empty_fixtures["/api/v1/projects/41/packages"] = {"items": []}
    empty_fixtures["/api/v1/projects/41/operations"] = {"items": [], "operational": {"runtime": {}}}
    install_api(empty_page, fixtures=empty_fixtures)
    empty_page.goto(f"{base_url}/#review")
    empty_page.get_by_text("Пакетов для проверки нет", exact=True).wait_for()
    assert empty_page.get_by_role("button", name="Подобрать ещё 3 поста").is_enabled()
    empty_page.goto(f"{base_url}/#journal")
    empty_page.get_by_text("Запусков пока нет", exact=True).wait_for()
    assert empty_page.get_by_role("button", name="Опубликовать один").is_enabled()
    assert empty_page.get_by_role("button", name="Запустить поиск").is_enabled()


def test_detail_closes_by_escape_backdrop_and_route_change(page_factory, base_url: str) -> None:
    page = page_factory()
    install_api(page)
    page.goto(f"{base_url}/#review")

    def open_package():
        opener = page.locator('[data-action="open-package"]')
        opener.click()
        page.locator('#detail-layer[open]').wait_for()
        page.get_by_role("button", name="Перегенерировать пост").wait_for()
        return opener

    open_package()
    page.keyboard.press("Escape")
    assert not page.locator("#detail-layer").evaluate("node => node.open")
    assert page.evaluate("document.activeElement === document.querySelector('[data-action=\"open-package\"]')")

    open_package()
    page.locator("#detail-layer").click(position={"x": 2, "y": 2})
    assert not page.locator("#detail-layer").evaluate("node => node.open")
    assert page.evaluate("document.activeElement === document.querySelector('[data-action=\"open-package\"]')")

    open_package()
    page.evaluate("location.hash = '#queue'")
    page.locator('[data-screen="queue"]:not([data-loading])').wait_for()
    assert not page.locator("#detail-layer").evaluate("node => node.open")
    assert page.locator("#detail-content").get_by_text("Пакет №", exact=False).count() == 0


def test_package_background_action_is_owned_while_its_request_is_pending(page_factory, base_url: str) -> None:
    page = page_factory()
    calls: list[HttpCall] = []
    held = []
    install_api(page, calls=calls)

    def hold_regenerate(route):
        if route.request.method == "POST" and route.request.url.endswith("/regenerate"):
            calls.append(HttpCall(
                route.request.method,
                "/api/v1/projects/41/packages/9001/regenerate",
                route.request.post_data_json,
                dict(route.request.headers),
            ))
            held.append(route)
            return
        route.fallback()

    page.route("**/api/v1/**", hold_regenerate)
    page.goto(f"{base_url}/#review")
    page.locator('[data-action="open-package"]').click()
    action = page.get_by_role("button", name="Перегенерировать пост")
    action.wait_for()
    with page.expect_request("**/regenerate"):
        action.click()
    assert action.is_disabled()
    assert len(held) == 1
    action.click(force=True, timeout=500)
    assert len(held) == 1
    held[0].fulfill(status=202, json={"status": "accepted", "operationRunId": 303})
    page.get_by_text("Новая версия поста готова", exact=True).wait_for()
    assert len([call for call in calls if call.method == "POST" and call.path.endswith("/regenerate")]) == 1
    polls = [call for call in calls if call.method == "GET" and call.path.endswith("/operations/303")]
    assert len(polls) >= 2
    assert len([call for call in calls if call.method == "GET" and call.path.endswith("/packages")]) >= 2
    assert page.get_by_text("Новая версия поста готова", exact=True).count() == 1
    assert not page.locator("#detail-layer").evaluate("node => node.open")
