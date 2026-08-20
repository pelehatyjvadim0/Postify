import json

import pytest
from playwright.sync_api import Page, Route

from tests.ui_mockup.browser_support import (
    PROJECT,
    PIXEL_PNG,
    fixture_payloads,
    install_api,
    install_settings_api,
)


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


def test_selected_route_fetches_only_bootstrap_and_its_resource(page_factory, base_url: str) -> None:
    # Break caught: initial navigation downloads every screen instead of its own bounded resource.
    inspected = page_factory()
    requests: list[tuple[str, str]] = []
    install_api(inspected, requests)
    try:
        inspected.goto(f"{base_url}/#materials")
        inspected.get_by_text("Материал 9001", exact=False).wait_for()
        assert requests == [("GET", "/api/v1/bootstrap"), ("GET", f"{PROJECT}/materials")]
    finally:
        inspected.close()


@pytest.mark.parametrize("width", [360, 768, 1440])
def test_settings_render_eight_compact_provider_driven_sections_without_overflow(
    page_factory, base_url: str, width: int
) -> None:
    # Break caught: settings stay a placeholder, expose infrastructure, or hard-code provider fields outside the bootstrap catalog.
    inspected = page_factory(viewport={"width": width, "height": 1000})
    install_api(inspected)
    try:
        inspected.goto(f"{base_url}/#settings")
        sections = inspected.locator("[data-settings-section]")
        sections.first.wait_for()
        assert sections.count() == 8
        assert inspected.locator("[data-settings-section][open]").count() == 1
        source_form = inspected.locator('[data-settings-form="sources"]').first
        channel_form = inspected.locator('[data-settings-form="channels"]').first
        assert source_form.get_by_label("Провайдер источника").input_value() == "hn_algolia"
        assert source_form.get_by_label("Поисковый запрос").input_value() == "AI"
        assert channel_form.get_by_label("@username канала").input_value() == "@aioiai_ai_news"
        page_text = inspected.locator("#screen-root").inner_text().casefold()
        for forbidden in ("dsn", "media dir", "encryption key", "systemd"):
            assert forbidden not in page_text
        assert inspected.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

        for section in ("sources", "selection", "generation", "cta", "channels", "schedule", "advanced"):
            inspected.locator(f'[data-settings-section="{section}"] > summary').click()
            assert inspected.locator(f'[data-settings-section="{section}"]').get_attribute("open") == ""
            assert inspected.locator("[data-settings-section][open]").count() == 1
            assert inspected.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    finally:
        inspected.close()


def test_settings_save_is_section_scoped_dirty_busy_and_refreshes_summary(
    page_factory, base_url: str
) -> None:
    # Break caught: save sends the whole settings graph, stays clickable while busy, or leaves the server summary stale.
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    inspected.set_default_timeout(3000)
    try:
        inspected.goto(f"{base_url}/#settings")
        form = inspected.locator('[data-settings-form="main"]')
        savebar = form.locator(".settings-savebar")
        assert savebar.is_hidden()
        inspected.get_by_label("Название проекта").fill("Новая редакция")
        assert savebar.is_visible()
        save = form.get_by_role("button", name="Сохранить")
        save.click()
        assert save.is_disabled()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
        assert calls == [{
            "method": "PUT",
            "path": f"{PROJECT}/settings/main",
            "body": {
                "name": "Новая редакция",
                "topic": "Практичные AI-инструменты",
                "language": "ru",
                "audience": "Продуктовые команды",
                "timezone": "Europe/Moscow",
            },
        }]
        assert inspected.locator('[data-settings-section="main"] .settings-summary-current').inner_text() == "Новая редакция · ru"
        assert savebar.is_hidden()
    finally:
        inspected.close()


def test_serialize_settings_section_is_pure_and_keeps_nested_provider_values(
    page: Page, base_url: str
) -> None:
    # Break caught: serialization reads global screen state or flattens provider configuration into the common connection model.
    page.goto(f"{base_url}/#overview")
    result = page.evaluate(
        """async () => {
            const {serializeSettingsSection} = await import('/settings.js');
            const host = document.createElement('div');
            host.innerHTML = `<form data-settings-form="sources">
              <input name="name" value="Источник">
              <input name="enabled" type="checkbox" checked>
              <input name="configuration.query" value="AI">
              <input name="configuration.hits" type="number" value="25">
            </form>`;
            return serializeSettingsSection(host.querySelector('form'));
        }"""
    )
    assert result == {
        "name": "Источник",
        "enabled": True,
        "configuration": {"query": "AI", "hits": 25},
    }


def test_api_client_keeps_csrf_and_safe_error_details_at_the_browser_boundary(
    page: Page, base_url: str
) -> None:
    # Break caught: mutations lose their capability header or API error payloads leak untrusted fields.
    page.goto(f"{base_url}/#overview")
    result = page.evaluate("""async () => {
        const calls = [];
        window.fetch = async (url, options = {}) => {
          calls.push({url, method: options.method || 'GET', headers: [...new Headers(options.headers || {}).entries()], body: options.body ?? null});
          if (url.endsWith('/bootstrap')) return new Response(JSON.stringify({csrfToken: 'browser-fixture-capability'}), {status: 200});
          if (url.endsWith('/ctas/9')) return new Response(null, {status: 204});
          if (url.endsWith('/error-json')) return new Response(JSON.stringify({code: 'review_unresolved', unresolvedPackageIds: [1, -2, '3', 4, ...Array.from({length: 75}, (_, index) => index + 5)]}), {status: 409});
          return new Response('private upstream detail', {status: 502});
        };
        const api = await import('/api.js');
        await api.getBootstrap();
        const deleted = await api.deleteResource(41, 'ctas', 9);
        const failures = [];
        for (const path of ['/error-json', '/error-text']) {
          try { await api.request(path); }
          catch (error) { failures.push({status: error.status, code: error.code, ids: error.unresolvedPackageIds, message: error.message}); }
        }
        return {deleted, failures, calls};
    }""")

    delete_call = next(call for call in result["calls"] if call["method"] == "DELETE")
    assert ["x-postify-csrf", "browser-fixture-capability"] in delete_call["headers"]
    assert delete_call["body"] is None
    assert result["deleted"] is None
    assert result["failures"][0] == {"status": 409, "code": "review_unresolved", "ids": [1, 4, *range(5, 53)], "message": "review_unresolved"}
    assert result["failures"][1] == {"status": 502, "code": "request_failed", "ids": [], "message": "request_failed"}


def test_settings_serializer_handles_form_value_classes_and_provider_switching(
    page: Page, base_url: str
) -> None:
    # Break caught: a dynamic provider form serializes stale fields or treats typed values as strings.
    page.goto(f"{base_url}/#overview")
    result = page.evaluate("""async () => {
        const {serializeSettingsSection, renderProviderConfiguration} = await import('/settings.js');
        const host = document.createElement('div');
        host.innerHTML = `<form><input name="name" value=" Источник "><input name="enabled" type="checkbox" checked><input name="configuration.hits" type="number" value="25"><input name="terms" data-array value="AI, Python"><input name="cta_id" data-null-empty value=""><input name="hidden" type="hidden" value="false"><input name="slots" data-multi value="09:00"><input name="slots" data-multi value="14:00"><input name="ignored" disabled value="no"><button name="submit">go</button></form>`;
        const providers = {sources: [{code: 'one', fields: [{name: 'alpha', label: '<b>Alpha</b>', type: 'text', required: true}]}, {code: 'two', fields: [{name: 'count', label: 'Count', type: 'number', min: 1, max: 3}]}]};
        return {payload: serializeSettingsSection(host.querySelector('form')), one: renderProviderConfiguration(providers, 'sources', 'one', {}), two: renderProviderConfiguration(providers, 'sources', 'two', {}), none: renderProviderConfiguration(providers, 'sources', 'missing', {})};
    }""")
    assert result["payload"] == {"name": "Источник", "enabled": True, "configuration": {"hits": 25}, "terms": ["AI", "Python"], "cta_id": None, "hidden": False, "slots": ["09:00", "14:00"]}
    assert 'name="configuration.alpha"' in result["one"]
    assert "&lt;b&gt;Alpha&lt;/b&gt;" in result["one"]
    assert 'name="configuration.count"' in result["two"]
    assert 'type="number"' in result["two"]
    assert result["none"] == ""


def test_settings_validate_shares_slots_url_and_route_references_before_request(
    page_factory, base_url: str
) -> None:
    # Break caught: invalid cross-field settings reach an API that is forced to reject them after a network request.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="generation"] > summary').click()
        generation = inspected.locator('[data-settings-form="generation"]')
        generation.get_by_label("Доля свежих, %").fill("80")
        generation.get_by_role("button", name="Сохранить").click()
        error = generation.locator("[data-settings-error]")
        assert "100" in error.inner_text()
        assert generation.get_by_label("Доля свежих, %").get_attribute("aria-describedby") == error.get_attribute("id")

        inspected.locator('[data-settings-section="schedule"] > summary').click()
        schedule = inspected.locator('[data-settings-form="schedule"]')
        schedule.get_by_label("Дневной слот").fill("09:00")
        schedule.get_by_role("button", name="Сохранить").click()
        assert "разными" in schedule.locator("[data-settings-error]").inner_text()

        inspected.locator('[data-settings-section="cta"] > summary').click()
        cta = inspected.locator('[data-settings-form="cta"]').first
        cta.get_by_label("Режим ссылки").select_option("custom")
        cta.get_by_label("Адрес ссылки").fill("javascript:alert(1)")
        cta.get_by_role("button", name="Сохранить").click()
        assert "HTTP" in cta.locator("[data-settings-error]").inner_text()
        assert calls == []
    finally:
        inspected.close()


def test_schedule_save_is_one_section_only_request(
    page_factory, base_url: str
) -> None:
    # Break caught: schedule save can persist source state before a second route request fails.
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="schedule"] > summary').click()
        form = inspected.locator('[data-settings-form="schedule"]')
        form.get_by_label("Расписание получения").fill("0 8 * * *")
        form.get_by_label("Утренний слот").fill("08:30")
        form.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()

        assert calls == [{
            "method": "PUT",
            "path": f"{PROJECT}/settings/schedule",
            "body": {
                "sources": [{"id": 1, "schedule": "0 8 * * *"}],
                "routes": [{
                    "id": 1,
                    "autopublish": True,
                    "slots": ["08:30", "14:00", "19:00"],
                }],
            },
        }]
    finally:
        inspected.close()


def test_source_https_constraint_is_provider_driven_and_blocks_request(
    page_factory, base_url: str
) -> None:
    # Break caught: generic URL validity accepts HTTP although provider metadata/server require HTTPS.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="sources"] > summary').click()
        source = inspected.locator('[data-resource="sources"][data-resource-id="1"]')
        source.get_by_label("Адрес API").fill("http://hn.algolia.com")
        source.get_by_role("button", name="Сохранить").click()

        assert "HTTPS" in source.locator("[data-settings-error]").inner_text()
        assert calls == []
    finally:
        inspected.close()


def test_required_provider_text_is_not_empty_after_normalization(
    page_factory, base_url: str
) -> None:
    # Break caught: whitespace-only provider text passes HTML required and is sent empty after serialization.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="sources"] > summary').click()
        form = inspected.locator('[data-resource="sources"][data-resource-id="1"]')
        control = form.get_by_label("Поисковый запрос")
        control.fill("   ")
        form.get_by_role("button", name="Сохранить").click()

        error = form.locator("[data-settings-error]")
        error_id = error.get_attribute("id")
        assert "пуст" in error.inner_text().casefold()
        assert calls == []
        assert error_id
        assert form.get_attribute("aria-describedby") == error_id
        assert control.get_attribute("aria-describedby") == error_id
    finally:
        inspected.close()


def test_https_provider_url_requires_explicit_authority_before_request(
    page_factory, base_url: str
) -> None:
    # Break caught: Chromium normalizes https:foo to a URL with host although server urlsplit sees no netloc.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="sources"] > summary').click()
        form = inspected.locator('[data-resource="sources"][data-resource-id="1"]')
        control = form.get_by_label("Адрес API")
        control.fill("https:foo")
        form.get_by_role("button", name="Сохранить").click()

        error = form.locator("[data-settings-error]")
        error_id = error.get_attribute("id")
        assert "HTTPS" in error.inner_text()
        assert calls == []
        assert error_id
        assert form.get_attribute("aria-describedby") == error_id
        assert control.get_attribute("aria-describedby") == error_id
    finally:
        inspected.close()


def test_marker_duplicates_collapse_internal_whitespace_before_request(
    page_factory, base_url: str
) -> None:
    # Break caught: terms equal after server whitespace normalization still reach the API as distinct strings.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="selection"] > summary').click()
        form = inspected.locator('[data-settings-form="selection"]')
        control = form.get_by_label("Тематические маркеры")
        control.fill("foo  bar, foo bar")
        form.get_by_role("button", name="Сохранить").click()

        error = form.locator("[data-settings-error]")
        error_id = error.get_attribute("id")
        assert "повтор" in error.inner_text().casefold()
        assert calls == []
        assert error_id
        assert form.get_attribute("aria-describedby") == error_id
        assert control.get_attribute("aria-describedby") == error_id
    finally:
        inspected.close()


def test_route_references_are_checked_against_rendered_resource_ids_before_request(
    page_factory, base_url: str
) -> None:
    # Break caught: a stale/tampered route ID passes client validation and is needlessly rejected by the API.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="channels"] > summary').click()
        form = inspected.locator('[data-resource="routes"][data-resource-id="1"]')
        channel = form.get_by_label("Канал маршрута")
        channel.evaluate(
            """select => {
                const stale = new Option('Удалённый канал', '999', true, true);
                select.append(stale);
                select.dispatchEvent(new Event('change', {bubbles: true}));
            }"""
        )
        form.get_by_role("button", name="Сохранить").click()

        assert "несуществующий" in form.locator("[data-settings-error]").inner_text()
        assert calls == []
    finally:
        inspected.close()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        ("rules", "правило"),
        ("markers", "маркер"),
        ("duplicates", "повтор"),
    ],
)
def test_selection_domain_invariants_block_request(
    page_factory, base_url: str, mutate: str, message: str
) -> None:
    # Break caught: selection payloads known to fail ProjectConfiguration are still sent over the network.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="selection"] > summary').click()
        form = inspected.locator('[data-settings-form="selection"]')
        if mutate == "rules":
            for rule in form.locator('input[name="selection_rules"]').all():
                rule.uncheck()
        elif mutate == "markers":
            form.get_by_label("Маркеры рекламы").fill("")
        else:
            form.get_by_label("Тематические маркеры").fill("AI, ai")
        form.get_by_role("button", name="Сохранить").click()

        assert message in form.locator("[data-settings-error]").inner_text().casefold()
        assert calls == []
    finally:
        inspected.close()


def test_selection_policy_version_is_system_owned_and_not_submitted(
    page_factory, base_url: str
) -> None:
    # Break caught: audit policy revision becomes a client-controlled form value.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="selection"] > summary').click()
        form = inspected.locator('[data-settings-form="selection"]')
        assert form.get_by_label("Версия политики").count() == 0
        assert "project-41-v7" in form.inner_text()
        form.get_by_label("Окно свежести, дней").fill("31")
        form.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
        request = next(call for call in calls if call["path"].endswith("/settings/configuration"))
        assert "selection_policy_version" not in request["body"]
    finally:
        inspected.close()


def test_channel_token_keep_replace_remove_and_real_check_are_distinct_intents(
    page_factory, base_url: str
) -> None:
    # Break caught: a masked placeholder becomes a token value, blank save clears it, or remove/check remain decorative controls.
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="channels"] > summary').click()
        form = inspected.locator('[data-settings-form="channels"]').first
        token = form.get_by_label("Токен бота")
        assert token.input_value() == ""
        assert token.get_attribute("placeholder") == "Токен сохранён"
        assert form.get_by_role("button", name="Показать токен").is_disabled()

        form.get_by_label("@username канала").fill("@another_public_channel")
        form.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
        keep = next(call for call in calls if call["path"] == f"{PROJECT}/channels/1")
        assert "token" not in keep["body"]
        assert keep["body"]["configuration"] == {"chat_id": "@another_public_channel"}

        form = inspected.locator('[data-settings-form="channels"]').first
        token = form.get_by_label("Токен бота")
        token.fill("new-secret")
        reveal = form.get_by_role("button", name="Показать токен")
        assert reveal.is_enabled()
        reveal.click()
        assert token.get_attribute("type") == "text"
        inspected.locator('[data-settings-form="channels"]').first.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
        replacements = [call for call in calls if call["path"] == f"{PROJECT}/channels/1"]
        assert replacements[-1]["body"]["token"] == "new-secret"

        inspected.get_by_role("button", name="Удалить токен").click()
        inspected.get_by_role("button", name="Проверить канал").click()
        assert any(call["path"] == f"{PROJECT}/channels/1/secret/remove" for call in calls)
        assert any(call["path"] == f"{PROJECT}/channels/1/check" for call in calls)
        assert not any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/channels/1" for call in calls)
    finally:
        inspected.close()


@pytest.mark.parametrize(
    ("section", "form_selector", "button_name", "failure_path"),
    [
        ("sources", '[data-resource="sources"][data-resource-id="1"]', "Удалить", f"{PROJECT}/sources/1"),
        ("channels", '[data-resource="channels"][data-resource-id="1"]', "Удалить токен", f"{PROJECT}/channels/1/secret/remove"),
        ("channels", '[data-resource="channels"][data-resource-id="1"]', "Проверить канал", f"{PROJECT}/channels/1/check"),
        ("channels", '[data-resource="routes"][data-resource-id="1"]', "Удалить маршрут", f"{PROJECT}/routes/1"),
    ],
)
def test_failed_settings_command_describes_form_and_initiating_button(
    page_factory,
    base_url: str,
    section: str,
    form_selector: str,
    button_name: str,
    failure_path: str,
) -> None:
    # Break caught: command errors have no stable accessible relation to the button that initiated them.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    install_settings_api(inspected, [], failures={failure_path})
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator(f'[data-settings-section="{section}"] > summary').click()
        form = inspected.locator(form_selector)
        button = form.get_by_role("button", name=button_name)
        button.click()

        error = form.locator("[data-settings-error]")
        error.filter(has_text="Команда").wait_for()
        assert "не выполнена" in error.inner_text().casefold()
        error_id = error.get_attribute("id")
        assert error_id
        assert form.get_attribute("aria-describedby") == error_id
        assert button.get_attribute("aria-describedby") == error_id
    finally:
        inspected.close()


def test_source_cta_channel_and_route_mutations_use_resource_endpoints(
    page_factory, base_url: str
) -> None:
    # Break caught: resource controls mutate an in-memory demo model instead of Task 7 CRUD endpoints.
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    try:
        inspected.goto(f"{base_url}/#settings")
        changes = {
            "sources": ("Название источника", "Новости AI"),
            "cta": ("Название CTA", "Ссылка на материал"),
            "channels": ("Название канала", "Канал редакции"),
        }
        for section, (label, value) in changes.items():
            inspected.locator(f'[data-settings-section="{section}"] > summary').click()
            form = inspected.locator(f'[data-settings-form="{section}"]').first
            form.get_by_label(label).fill(value)
            form.get_by_role("button", name="Сохранить").click()
            inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
            inspected.locator("#screen-root").wait_for()

        route_form = inspected.locator('[data-resource="routes"][data-resource-id="1"]')
        route_form.get_by_label("Маршрут включён").uncheck()
        route_form.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()

        paths = {call["path"] for call in calls if call["method"] == "PUT"}
        assert paths >= {
            f"{PROJECT}/sources/1",
            f"{PROJECT}/ctas/1",
            f"{PROJECT}/channels/1",
            f"{PROJECT}/routes/1",
        }
        route = next(call for call in calls if call["path"] == f"{PROJECT}/routes/1")
        assert route["body"] | {"schedule": route["body"].get("schedule")} == {
            "format_id": 1,
            "channel_id": 1,
            "cta_id": 1,
            "enabled": False,
            "schedule": {"autopublish": True, "slots": ["09:00", "14:00", "19:00"]},
        }
    finally:
        inspected.close()


def test_source_create_and_cta_delete_controls_call_crud_endpoints(
    page_factory, base_url: str
) -> None:
    # Break caught: add/delete controls are decorative instead of using resource endpoints.
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    inspected.set_default_timeout(3000)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="sources"] > summary').click()
        inspected.get_by_role("button", name="Добавить источник").click()
        source = inspected.locator('[data-resource="sources"][data-resource-mode="create"]')
        source.get_by_label("Название источника").fill("Второй источник")
        source.get_by_label("Адрес API").fill("https://hn.algolia.com")
        source.get_by_label("Поисковый запрос").fill("Python")
        source.get_by_label("Теги").fill("story")
        source.get_by_label("Материалов за запрос").fill("20")
        source.get_by_label("Расписание получения").fill("0 8 * * *")
        source.get_by_role("button", name="Сохранить").click()
        inspected.locator("#screen-root").wait_for()

        inspected.locator('[data-settings-section="cta"] > summary').click()
        inspected.locator('[data-resource="ctas"][data-resource-mode="update"]').get_by_role("button", name="Удалить").click()
        inspected.locator("#screen-root").wait_for()

        assert any(call["method"] == "POST" and call["path"] == f"{PROJECT}/sources" for call in calls)
        assert any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/ctas/1" for call in calls)
    finally:
        inspected.close()


def test_stateful_source_cta_and_channel_crud_refreshes_created_ids(
    page_factory, base_url: str
) -> None:
    """Each resource must be created, refreshed, updated, and deleted by its server ID."""
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    install_settings_api(inspected, calls)
    inspected.goto(f"{base_url}/#settings")

    inspected.locator('[data-settings-section="sources"] > summary').click()
    inspected.get_by_role("button", name="Добавить источник").click()
    source = inspected.locator('[data-resource="sources"][data-resource-mode="create"]')
    source.get_by_label("Название источника").fill("Второй источник")
    source.get_by_label("Адрес API").fill("https://hn.algolia.com")
    source.get_by_label("Поисковый запрос").fill("Python")
    source.get_by_label("Теги").fill("story")
    source.get_by_label("Материалов за запрос").fill("20")
    source.get_by_label("Расписание получения").fill("0 8 * * *")
    source.get_by_role("button", name="Сохранить").click()
    source = inspected.locator('[data-resource="sources"][data-resource-id="2"]')
    source.wait_for()
    source.get_by_label("Название источника").fill("Обновлённый источник")
    source.get_by_role("button", name="Сохранить").click()
    source = inspected.locator('[data-resource="sources"][data-resource-id="2"]')
    source.get_by_label("Название источника").wait_for()
    assert source.get_by_label("Название источника").input_value() == "Обновлённый источник"
    source.get_by_role("button", name="Удалить").click()
    source.wait_for(state="detached")

    inspected.locator('[data-settings-section="cta"] > summary').click()
    inspected.get_by_role("button", name="Добавить CTA").click()
    cta = inspected.locator('[data-resource="ctas"][data-resource-mode="create"]')
    cta.get_by_label("Название CTA").fill("Новый CTA")
    cta.get_by_label("Текст действия").fill("Открыть")
    cta.get_by_label("Режим ссылки").select_option("custom")
    cta.get_by_label("Адрес ссылки").fill("https://example.test/cta")
    cta.get_by_role("button", name="Сохранить").click()
    cta = inspected.locator('[data-resource="ctas"][data-resource-id="2"]')
    cta.wait_for()
    cta.get_by_label("Текст действия").fill("Читать")
    cta.get_by_role("button", name="Сохранить").click()
    cta = inspected.locator('[data-resource="ctas"][data-resource-id="2"]')
    assert cta.get_by_label("Текст действия").input_value() == "Читать"
    cta.get_by_role("button", name="Удалить").click()
    cta.wait_for(state="detached")

    inspected.locator('[data-settings-section="channels"] > summary').click()
    inspected.get_by_role("button", name="Добавить канал").click()
    channel = inspected.locator('[data-resource="channels"][data-resource-mode="create"]')
    channel.get_by_label("Название канала").fill("Второй канал")
    channel.get_by_label("@username канала").fill("@second")
    channel.get_by_label("Токен бота").fill("new-channel-token")
    channel.get_by_role("button", name="Сохранить").click()
    channel = inspected.locator('[data-resource="channels"][data-resource-id="2"]')
    channel.wait_for()
    assert channel.get_by_label("Токен бота").input_value() == ""
    assert channel.get_by_label("Токен бота").get_attribute("placeholder") == "Токен сохранён"
    channel.get_by_label("Название канала").fill("Обновлённый канал")
    channel.get_by_role("button", name="Сохранить").click()
    inspected.get_by_text("Настройки сохранены", exact=True).wait_for()
    channel = inspected.locator('[data-resource="channels"][data-resource-id="2"]')
    assert channel.get_by_label("Название канала").input_value() == "Обновлённый канал"
    channel.get_by_role("button", name="Удалить", exact=True).click()
    channel.wait_for(state="detached")

    for resource in ("sources", "ctas", "channels"):
        assert any(call["method"] == "POST" and call["path"] == f"{PROJECT}/{resource}" for call in calls)
        assert any(call["method"] == "PUT" and call["path"] == f"{PROJECT}/{resource}/2" for call in calls)
        assert any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/{resource}/2" for call in calls)
        assert not any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/{resource}/1" for call in calls)
    source_posts = [call for call in calls if call["path"] == f"{PROJECT}/sources"]
    source_updates = [call for call in calls if call["path"] == f"{PROJECT}/sources/2" and call["method"] == "PUT"]
    assert source_posts[0]["body"] == {"provider": "hn_algolia", "name": "Второй источник", "configuration": {"url": "https://hn.algolia.com", "query": "Python", "tags": "story", "hits": 20}, "schedule": "0 8 * * *", "enabled": True}
    assert source_updates[0]["body"] == {"provider": "hn_algolia", "name": "Обновлённый источник", "configuration": {"url": "https://hn.algolia.com", "query": "Python", "tags": "story", "hits": 20}, "schedule": "0 8 * * *", "enabled": True}
    cta_posts = [call for call in calls if call["path"] == f"{PROJECT}/ctas"]
    cta_updates = [call for call in calls if call["path"] == f"{PROJECT}/ctas/2" and call["method"] == "PUT"]
    assert cta_posts[0]["body"] == {"name": "Новый CTA", "text": "Открыть", "link_mode": "custom", "custom_url": "https://example.test/cta", "enabled": True}
    assert cta_updates[0]["body"] == {"name": "Новый CTA", "text": "Читать", "link_mode": "custom", "custom_url": "https://example.test/cta", "enabled": True}
    channel_posts = [call for call in calls if call["path"] == f"{PROJECT}/channels"]
    channel_updates = [call for call in calls if call["path"] == f"{PROJECT}/channels/2" and call["method"] == "PUT"]
    assert channel_posts[0]["body"] == {"provider": "telegram", "name": "Второй канал", "configuration": {"chat_id": "@second"}, "token": "new-channel-token", "enabled": True}
    assert channel_updates[0]["body"] == {"provider": "telegram", "name": "Обновлённый канал", "configuration": {"chat_id": "@second"}, "enabled": True}


def test_settings_render_empty_resource_states_without_fake_update_forms(
    page_factory, base_url: str
) -> None:
    # Break caught: empty collections render update/delete controls with blank IDs instead of an actionable empty state.
    inspected = page_factory(viewport={"width": 768, "height": 1000})
    settings = json.loads(json.dumps(fixture_payloads()[f"{PROJECT}/settings"]))
    for resource in ("sources", "ctas", "channels", "routes"):
        settings[resource] = []
    install_settings_api(inspected, [], initial_settings=settings)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="sources"] > summary').click()
        assert inspected.get_by_text("Источники не настроены", exact=True).is_visible()
        inspected.locator('[data-settings-section="cta"] > summary').click()
        assert inspected.get_by_text("CTA не настроены", exact=True).is_visible()
        inspected.locator('[data-settings-section="channels"] > summary').click()
        assert inspected.get_by_text("Каналы не настроены", exact=True).is_visible()
        assert inspected.get_by_text("Маршруты не настроены", exact=True).is_visible()
        assert inspected.locator('[data-resource-mode="update"]').count() == 0
    finally:
        inspected.close()


def test_settings_render_every_resource_with_its_own_id_and_actual_route_references(
    page_factory, base_url: str
) -> None:
    # Break caught: only index zero is editable, or a route is displayed under the wrong channel.
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    settings = json.loads(json.dumps(fixture_payloads()[f"{PROJECT}/settings"]))
    settings["sources"].append({
        **settings["sources"][0], "id": 22, "name": "Второй источник", "configuration": {**settings["sources"][0]["configuration"], "query": "Python"},
    })
    settings["ctas"].append({**settings["ctas"][0], "id": 33, "name": "Второй CTA"})
    settings["channels"].append({
        **settings["channels"][0], "id": 44, "name": "Второй канал", "configuration": {"chat_id": "-100444"},
    })
    settings["routes"].append({
        **settings["routes"][0], "id": 55, "channel_id": 44, "cta_id": 33,
    })
    install_settings_api(inspected, [], initial_settings=settings)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="channels"] > summary').click()
        assert inspected.locator('[data-resource="sources"][data-resource-mode="update"]').count() == 2
        assert inspected.locator('[data-resource="ctas"][data-resource-mode="update"]').count() == 2
        assert inspected.locator('[data-resource="channels"][data-resource-mode="update"]').count() == 2
        assert inspected.locator('[data-resource="routes"][data-resource-mode="update"]').count() == 2
        second_route = inspected.locator('[data-resource="routes"][data-resource-id="55"]')
        assert second_route.get_by_label("Канал маршрута").input_value() == "44"
        assert second_route.get_by_label("CTA маршрута").input_value() == "33"
    finally:
        inspected.close()


def test_stateful_crud_updates_and_deletes_the_created_route_id(
    page_factory, base_url: str
) -> None:
    # Break caught: fake CRUD leaves state unchanged, so update/delete accidentally target the original route.
    inspected = page_factory(viewport={"width": 1440, "height": 1000})
    calls: list[dict[str, object]] = []
    settings = fixture_payloads()[f"{PROJECT}/settings"]
    settings["formats"].append({**settings["formats"][0], "id": 2, "name": "Второй формат"})
    settings["ctas"].append({**settings["ctas"][0], "id": 2, "name": "Второй CTA"})
    settings["channels"].append({**settings["channels"][0], "id": 2, "name": "Второй канал"})
    install_settings_api(inspected, calls, initial_settings=settings)
    try:
        inspected.goto(f"{base_url}/#settings")
        inspected.locator('[data-settings-section="channels"] > summary').click()
        inspected.get_by_role("button", name="Добавить маршрут").click()
        create = inspected.locator('[data-resource="routes"][data-resource-mode="create"]')
        create.get_by_role("button", name="Сохранить").click()
        created = inspected.locator('[data-resource="routes"][data-resource-id="2"]')
        created.wait_for()

        inspected.locator('[data-settings-section="schedule"] > summary').click()
        schedule = inspected.locator('[data-settings-form="schedule"]')
        slots = schedule.locator('[data-route-schedule-id="2"] input[name="slots"]')
        slots.nth(0).fill("08:30")
        slots.nth(1).fill("13:30")
        slots.nth(2).fill("18:30")
        schedule.get_by_role("button", name="Сохранить").click()
        inspected.get_by_text("Настройки сохранены", exact=True).wait_for()

        inspected.locator('[data-settings-section="channels"] > summary').click()
        created = inspected.locator('[data-resource="routes"][data-resource-id="2"]')
        created.get_by_label("Маршрут включён").uncheck()
        created.get_by_label("Формат").select_option("2")
        created.get_by_label("Канал маршрута").select_option("2")
        created.get_by_label("CTA маршрута").select_option("2")
        created.get_by_role("button", name="Сохранить").click()
        created = inspected.locator('[data-resource="routes"][data-resource-id="2"]')
        created.wait_for()
        assert created.get_by_label("Формат").input_value() == "2"
        assert created.get_by_label("Канал маршрута").input_value() == "2"
        assert created.get_by_label("CTA маршрута").input_value() == "2"
        assert [created.locator('input[name="schedule.slots"]').nth(index).input_value() for index in range(3)] == ["08:30", "13:30", "18:30"]
        inspected.locator('[data-resource="routes"][data-resource-id="2"]').get_by_role("button", name="Удалить маршрут").click()
        inspected.locator('[data-resource="routes"][data-resource-id="2"]').wait_for(state="detached")

        assert any(call["method"] == "POST" and call["path"] == f"{PROJECT}/routes" for call in calls)
        assert any(call["method"] == "PUT" and call["path"] == f"{PROJECT}/routes/2" for call in calls)
        assert any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/routes/2" for call in calls)
        assert not any(call["method"] == "DELETE" and call["path"] == f"{PROJECT}/routes/1" for call in calls)
        create_call = next(call for call in calls if call["method"] == "POST" and call["path"] == f"{PROJECT}/routes")
        update_call = next(call for call in calls if call["method"] == "PUT" and call["path"] == f"{PROJECT}/routes/2")
        schedule_call = next(call for call in calls if call["method"] == "PUT" and call["path"] == f"{PROJECT}/settings/schedule")
        assert create_call["body"] == {"format_id": 1, "channel_id": 1, "cta_id": None, "enabled": True, "schedule": {"autopublish": True, "slots": ["09:00", "14:00", "19:00"]}}
        assert update_call["body"] == {"format_id": 2, "channel_id": 2, "cta_id": 2, "enabled": False, "schedule": {"autopublish": True, "slots": ["08:30", "13:30", "18:30"]}}
        assert {"id": 2, "autopublish": True, "slots": ["08:30", "13:30", "18:30"]} in schedule_call["body"]["routes"]
    finally:
        inspected.close()


def test_loading_error_retry_and_empty_are_explicit(page_factory, base_url: str) -> None:
    # Break caught: an unavailable API leaks demo cards or retry cannot recover the selected screen.
    inspected = page_factory()
    held_routes: list[Route] = []
    released = False

    def handle(route: Route) -> None:
        nonlocal released
        if route.request.url.endswith("/bootstrap"):
            route.fulfill(json=fixture_payloads()["/api/v1/bootstrap"])
        elif not released:
            held_routes.append(route)
        else:
            route.fulfill(json={"items": []})

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#materials", wait_until="domcontentloaded")
        loading = inspected.locator('[data-screen="materials"][data-loading]')
        loading.wait_for()
        assert loading.is_visible()
        assert loading.get_attribute("aria-busy") == "true"
        assert len(held_routes) == 1

        released = True
        held_routes.pop().fulfill(
            status=503,
            content_type="application/json",
            body='{"code":"service_unavailable"}',
        )
        inspected.get_by_text("Не удалось загрузить", exact=False).wait_for()
        assert inspected.get_by_text("Материал 9001", exact=False).count() == 0
        inspected.get_by_role("button", name="Повторить").click()
        inspected.get_by_text("Материалов пока нет", exact=False).wait_for()
    finally:
        inspected.close()


def test_retry_reloads_bootstrap_after_initial_connection_failure(page_factory, base_url: str) -> None:
    # Break caught: initial retry requests /projects/null instead of reconnecting and discovering the active project.
    inspected = page_factory()
    bootstrap_calls = 0

    def handle(route: Route) -> None:
        nonlocal bootstrap_calls
        path = "/" + route.request.url.split("/", 3)[-1]
        if path == "/api/v1/bootstrap":
            bootstrap_calls += 1
            if bootstrap_calls == 1:
                route.fulfill(status=503, json={"code": "service_unavailable"})
            else:
                route.fulfill(json=fixture_payloads()[path])
            return
        route.fulfill(json=fixture_payloads()[path])

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


@pytest.mark.parametrize(
    ("source_url", "expected_href"),
    [
        ("https://example.test/source", "https://example.test/source"),
        ("http://example.test/source", "http://example.test/source"),
        ("javascript:window.__unsafeUrl=1", None),
    ],
)
def test_package_source_url_allows_only_http_and_https(
    page_factory,
    base_url: str,
    source_url: str,
    expected_href: str | None,
) -> None:
    # Break caught: escaping quotes still leaves a javascript: URL executable in href.
    inspected = page_factory()

    def handle(route: Route) -> None:
        path = "/" + route.request.url.split("/", 3)[-1]
        if "/media/packages/" in path:
            route.fulfill(status=200, content_type="image/png", body=PIXEL_PNG)
            return
        if path in {f"{PROJECT}/packages", f"{PROJECT}/packages/9001"}:
            payload = json.loads(json.dumps(fixture_payloads()[path]))
            if "items" in payload:
                payload["items"][0]["source_url"] = source_url
            else:
                payload["source_url"] = source_url
            route.fulfill(json=payload)
            return
        route.fulfill(json=fixture_payloads()[path])

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        source = inspected.locator("#detail-content dd").filter(has_text=source_url)
        source.wait_for()
        if expected_href is None:
            assert source.locator("a").count() == 0
        else:
            assert source.locator("a").get_attribute("href") == expected_href
        assert inspected.evaluate("window.__unsafeUrl") is None
    finally:
        inspected.close()


def test_review_detail_loads_real_detail_history_analysis_and_media(
    page_factory, base_url: str
) -> None:
    # Break caught: review modal reuses summary and renders a placeholder instead of package endpoints.
    inspected = page_factory()
    requests: list[tuple[str, str]] = []
    install_api(inspected, requests)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()

        inspected.get_by_text("Полезен для продуктовой команды", exact=True).wait_for()
        assert inspected.locator(".package-history").get_by_text("generated", exact=True).is_visible()
        assert inspected.locator(".package-media").get_attribute("src") == f"{PROJECT}/media/packages/9001"
        assert ("GET", f"{PROJECT}/packages/9001") in requests
        natural_width = inspected.locator(".package-media").evaluate(
            "image => image.decode().then(() => image.naturalWidth)"
        )
        assert natural_width > 0
        assert ("GET", f"{PROJECT}/media/packages/9001") in requests
    finally:
        inspected.close()


@pytest.mark.parametrize("height", [700, 1100])
def test_desktop_package_dialog_keeps_header_and_actions_fixed_while_body_scrolls(
    page_factory, base_url: str, height: int
) -> None:
    # Break caught: a tall browser window gives the dialog a second scrollbar,
    # shifts it sideways, and sends the action buttons below the visible area.
    inspected = page_factory(viewport={"width": 1440, "height": height})

    def handle(route: Route) -> None:
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if path == f"{PROJECT}/packages/9001":
            detail = json.loads(json.dumps(fixture_payloads()[path]))
            detail["post_text"] = "\n\n".join(
                f"Абзац {index}: длинный текст пакета для проверки прокрутки."
                for index in range(1, 24)
            )
            detail["history"] = detail["history"] * 8
            route.fulfill(json=detail)
            return
        if "/media/packages/" in path:
            route.fulfill(status=200, content_type="image/png", body=PIXEL_PNG)
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        inspected.locator(".package-history").wait_for()

        geometry = inspected.evaluate(
            """() => {
                const dialog = document.querySelector('#detail-layer');
                const body = dialog.querySelector('.detail-body');
                const actions = dialog.querySelector('.detail-actions');
                const before = actions.getBoundingClientRect();
                body.scrollTop = body.scrollHeight;
                const after = actions.getBoundingClientRect();
                const box = dialog.getBoundingClientRect();
                return {
                    dialogClientHeight: dialog.clientHeight,
                    dialogScrollHeight: dialog.scrollHeight,
                    dialogLeft: box.left,
                    dialogRight: box.right,
                    dialogTop: box.top,
                    dialogBottom: box.bottom,
                    dialogOverflowY: getComputedStyle(dialog).overflowY,
                    contentDisplay: getComputedStyle(dialog.querySelector('#detail-content')).display,
                    actionsTopBefore: before.top,
                    actionsTopAfter: after.top,
                    actionsBottom: after.bottom,
                    bodyOverflowY: getComputedStyle(body).overflowY,
                };
            }"""
        )

        assert geometry["dialogScrollHeight"] == geometry["dialogClientHeight"]
        assert geometry["dialogOverflowY"] == "hidden"
        assert geometry["contentDisplay"] == "grid"
        assert geometry["dialogLeft"] == pytest.approx(
            1440 - geometry["dialogRight"], abs=1
        )
        assert geometry["dialogTop"] >= 0
        assert geometry["dialogBottom"] <= height
        assert geometry["actionsTopAfter"] == pytest.approx(
            geometry["actionsTopBefore"], abs=1
        )
        assert geometry["actionsBottom"] <= geometry["dialogBottom"]
        assert geometry["bodyOverflowY"] == "auto"
    finally:
        inspected.close()


def test_publication_detail_renders_attempt_outcomes_and_external_message_id(
    page: Page, base_url: str
) -> None:
    # Break caught: attempt_no is shown as history count while rows/message ID stay hidden.
    page.goto(f"{base_url}/#publications")
    page.locator('[data-action="open-delivery"]').click()

    detail = page.locator("#detail-content")
    assert detail.get_by_text("message ID: 42", exact=True).is_visible()
    assert detail.get_by_text("Можно повторить", exact=True).is_visible()
    assert (
        detail.locator(".package-history")
        .get_by_text("Опубликовано", exact=True)
        .is_visible()
    )


def test_empty_journal_and_failed_attempt_show_complete_operational_detail(
    page_factory, base_url: str
) -> None:
    inspected = page_factory()

    def handle(route: Route) -> None:
        path = "/" + route.request.url.split("/", 3)[-1]
        payload = fixture_payloads().get(path)
        if path == f"{PROJECT}/operations":
            payload = {
                "items": [],
                "operational": {
                    "deficit": 2,
                    "deficit_reasons": ["eligible_source_shortage"],
                    "signals": [{"code": "content_failures", "count": 3}],
                    "runtime": {"database": "available", "scheduler": "active"},
                },
            }
        elif path == f"{PROJECT}/publications":
            payload = {
                "items": [
                    {
                        **fixture_payloads()[path]["items"][0],
                        "status": "failed",
                        "attempts": [
                            {
                                "attempt_no": 1,
                                "outcome": "failed",
                                "code": "telegram_rejected",
                                "reason": "Канал запретил отправку",
                                "message_id": None,
                                "started_at": "2026-08-12T09:55:00Z",
                                "finished_at": "2026-08-12T09:56:00Z",
                            }
                        ],
                    }
                ]
            }
        route.fulfill(json=payload)

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#journal")
        inspected.locator('[data-screen="journal"]:not([data-loading])').wait_for()
        assert inspected.get_by_text("Запусков пока нет", exact=True).is_visible()
        assert inspected.get_by_text("База данных: Доступно", exact=True).is_visible()
        assert inspected.get_by_text("Планировщик: Активен", exact=True).is_visible()
        assert inspected.get_by_text("Недостаточно подходящих источников", exact=True).is_visible()
        journal = inspected.locator('[data-screen="journal"]')
        assert journal.locator('[data-action="new-run"]').is_visible()
        assert journal.locator('[data-action="publish-once"]').is_visible()

        inspected.goto(f"{base_url}/#publications")
        inspected.locator('[data-screen="publications"]:not([data-loading])').wait_for()
        inspected.locator('[data-action="open-delivery"]').click()
        detail = inspected.locator("#detail-content")
        assert detail.get_by_text("Канал отклонил публикацию", exact=True).is_visible()
        assert detail.get_by_text("Канал запретил отправку", exact=True).is_visible()
    finally:
        inspected.close()


def test_all_emitted_domain_codes_have_explicit_russian_labels(page: Page, base_url: str) -> None:
    # Break caught: a backend enum reaches the UI as an English snake_case fallback.
    expected = {
        "selected": "Выбран",
        "rejected": "Отклонён",
        "eligible_for_ai": "Подходит для анализа",
        "advertising": "Реклама",
        "out_of_scope": "Вне темы",
        "hiring": "Вакансия",
        "technical_without_use": "Технический релиз без практической пользы",
        "not_started": "Не начат",
        "processing": "Обрабатывается",
        "awaiting_review": "Ждёт проверки",
        "approved": "Одобрен",
        "failed": "Ошибка",
        "published": "Опубликовано",
        "available": "Доступно",
        "unavailable": "Недоступно",
        "deleted": "Удалено",
        "confirmed": "Подтверждён",
        "forecast": "Прогноз",
        "empty": "Свободно",
        "sending": "Отправляется",
        "retryable": "Можно повторить",
        "uncertain": "Результат не подтверждён",
        "run_once": "Поиск и подготовка",
        "publish_once": "Публикация",
        "running": "Выполняется",
        "succeeded": "Успешно",
        "completed": "Завершено",
        "cleanup_completed": "Медиа очищено",
        "cleanup_pending": "Ожидает очистки медиа",
        "run_once_failed": "Поиск завершился ошибкой",
        "publish_once_failed": "Публикация завершилась ошибкой",
        "media_unavailable": "Медиа недоступно",
        "telegram_transport_uncertain": "Ответ канала не подтверждён",
        "telegram_invalid_response": "Некорректный ответ канала",
        "telegram_retryable": "Канал временно недоступен",
        "telegram_rejected": "Канал отклонил публикацию",
        "stale_sending": "Отправка не завершена",
    }
    page.goto(f"{base_url}/#overview")
    actual = page.evaluate(
        """async codes => {
            const {label} = await import('/screens.js');
            return Object.fromEntries(codes.map(code => [code, label(code)]));
        }""",
        list(expected),
    )
    assert actual == expected


@pytest.mark.parametrize(("action", "method", "suffix", "toast"), [
    ("approve-package", "POST", "/packages/9001/approve", "Пост одобрен"),
    ("reject-package", "POST", "/packages/9001/reject", "Пост отклонён"),
])
def test_review_mutations_are_real_and_refresh_packages(page_factory, base_url: str, action: str, method: str, suffix: str, toast: str) -> None:
    # Break caught: review only mutates local UI state or fails to refresh after success.
    inspected = page_factory()
    requests: list[tuple[str, str]] = []
    install_api(inspected, requests)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        inspected.locator(f'[data-action="{action}"]').click()
        inspected.get_by_text(toast, exact=True).wait_for()
        inspected.locator('[data-screen="review"]:not([data-loading])').wait_for()
        assert (method, f"{PROJECT}{suffix}") in requests
        assert requests.count(("GET", f"{PROJECT}/packages")) >= 2
    finally:
        inspected.close()


def test_load_more_waits_for_terminal_run_and_renders_new_package_without_reload(
    page_factory, base_url: str
) -> None:
    # Break caught: accepted is treated as completed after a fixed delay and the new card never appears.
    inspected = page_factory()
    operation_reads = 0
    package_reads = 0

    def handle(route: Route) -> None:
        nonlocal operation_reads, package_reads
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}/packages/load-more":
            route.fulfill(status=202, json={"status": "accepted", "requested": 3, "operationRunId": 73})
            return
        if path == f"{PROJECT}/operations/73":
            operation_reads += 1
            route.fulfill(json={
                "run_id": 73,
                "status": "running" if operation_reads == 1 else "succeeded",
                "outcome": None if operation_reads == 1 else "completed",
                "failure_code": None,
            })
            return
        if path == f"{PROJECT}/packages":
            package_reads += 1
            first = dict(fixture_payloads()[path]["items"][0], status="approved")
            items = [first]
            if package_reads > 1:
                items.append({**first, "package_id": 9002, "post_text": "Новый пакет 9002", "status": "awaiting_review"})
            route.fulfill(json={"items": items})
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="load-more"]').click()
        inspected.get_by_role("button", name="Анализируем материалы…").wait_for()
        assert inspected.get_by_role("button", name="Анализируем материалы…").is_disabled()
        inspected.get_by_text("Новый пакет 9002", exact=True).wait_for()
        assert operation_reads >= 2
        assert package_reads >= 2
    finally:
        inspected.close()


def test_new_search_waits_for_terminal_run_before_refreshing_dashboard(
    page_factory, base_url: str
) -> None:
    # Break caught: the UI treats HTTP 202 as completion and never polls the run.
    inspected = page_factory()
    operation_reads = 0
    dashboard_reads = 0

    def handle(route: Route) -> None:
        nonlocal operation_reads, dashboard_reads
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}/operations/search":
            route.fulfill(status=202, json={"status": "accepted", "operationRunId": 75})
            return
        if path == f"{PROJECT}/operations/75":
            operation_reads += 1
            route.fulfill(json={
                "run_id": 75,
                "status": "running" if operation_reads == 1 else "succeeded",
                "outcome": None if operation_reads == 1 else "completed",
                "failure_code": None,
            })
            return
        if path == f"{PROJECT}/dashboard":
            dashboard_reads += 1
            route.fulfill(json={**fixture_payloads()[path], "candidate_total": 9000 + dashboard_reads})
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#overview")
        inspected.locator('[data-action="new-run"]').click()
        inspected.get_by_text("Поиск завершён", exact=True).wait_for()
        inspected.locator('[data-metric="candidates"]', has_text="9002").wait_for()
        assert operation_reads >= 2
        assert dashboard_reads >= 2
    finally:
        inspected.close()


def test_publish_once_waits_for_terminal_failure_instead_of_reporting_success(
    page_factory, base_url: str
) -> None:
    # Break caught: a failed Telegram operation is presented as completed after HTTP 202.
    inspected = page_factory()
    operation_reads = 0

    def handle(route: Route) -> None:
        nonlocal operation_reads
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}/operations/publish-once":
            route.fulfill(status=202, json={"status": "accepted", "operationRunId": 78})
            return
        if path == f"{PROJECT}/operations/78":
            operation_reads += 1
            route.fulfill(json={
                "run_id": 78,
                "status": "running" if operation_reads == 1 else "failed",
                "outcome": None,
                "failure_code": None if operation_reads == 1 else "publish_once_failed",
            })
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#journal")
        inspected.locator('[data-action="publish-once"]').click()
        inspected.get_by_text("Команда не выполнена. Повторите попытку.", exact=True).wait_for()
        assert inspected.get_by_text("Публикация завершена", exact=True).count() == 0
        assert operation_reads >= 2
    finally:
        inspected.close()


@pytest.mark.parametrize(
    ("action", "suffix", "toast"),
    [
        ("regenerate-post", "/packages/9001/regenerate", "Новая версия поста готова"),
        ("replace-media", "/packages/9001/media/replace", "Медиа обновлено"),
        ("publish-now", "/packages/9001/publish-now", "Публикация завершена"),
    ],
)
def test_package_background_actions_wait_for_terminal_run_and_refresh_review(
    page_factory,
    base_url: str,
    action: str,
    suffix: str,
    toast: str,
) -> None:
    # Break caught: accepted package commands close immediately and leave stale UI.
    inspected = page_factory()
    operation_reads = 0
    package_reads = 0

    def handle(route: Route) -> None:
        nonlocal operation_reads, package_reads
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}{suffix}":
            route.fulfill(status=202, json={"status": "accepted", "operationRunId": 76})
            return
        if path == f"{PROJECT}/operations/76":
            operation_reads += 1
            route.fulfill(json={
                "run_id": 76,
                "status": "running" if operation_reads == 1 else "succeeded",
                "outcome": None if operation_reads == 1 else "completed",
                "failure_code": None,
            })
            return
        if path == f"{PROJECT}/packages":
            package_reads += 1
            route.fulfill(json=fixture_payloads()[path])
            return
        if path == f"{PROJECT}/packages/9001":
            route.fulfill(json={**fixture_payloads()[path], "status": "approved"})
            return
        if "/media/packages/" in path:
            route.fulfill(status=200, content_type="image/png", body=PIXEL_PNG)
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        inspected.locator(f'[data-action="{action}"]').click()
        inspected.get_by_text(toast, exact=True).wait_for()
        assert not inspected.locator("#detail-layer").evaluate("dialog => dialog.open")
        assert operation_reads >= 2
        assert package_reads >= 2
    finally:
        inspected.close()


def test_failed_load_more_refreshes_and_keeps_partially_created_packages_visible(
    page_factory, base_url: str
) -> None:
    # Break caught: one created package is hidden behind a stale generic failure state.
    inspected = page_factory()
    package_reads = 0

    def handle(route: Route) -> None:
        nonlocal package_reads
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}/packages/load-more":
            route.fulfill(status=202, json={"status": "accepted", "requested": 3, "operationRunId": 77})
            return
        if path == f"{PROJECT}/operations/77":
            route.fulfill(json={
                "run_id": 77,
                "status": "failed",
                "outcome": None,
                "failure_code": "load_more_failed",
                "packages_created": 1,
            })
            return
        if path == f"{PROJECT}/packages":
            package_reads += 1
            first = dict(fixture_payloads()[path]["items"][0], status="approved")
            items = [first]
            if package_reads > 1:
                items.append({**first, "package_id": 9002, "post_text": "Новый пакет 9002", "status": "awaiting_review"})
            route.fulfill(json={"items": items})
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="load-more"]').click()
        inspected.get_by_text("Новый пакет 9002", exact=True).wait_for()
        inspected.get_by_text("Подбор постов завершился ошибкой.", exact=True).wait_for()
        assert package_reads >= 2
    finally:
        inspected.close()


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        (("succeeded", "empty", None), "Новых материалов нет. Запустите новый поиск."),
        (("failed", None, "load_more_failed"), "Подбор постов завершился ошибкой."),
    ],
)
def test_load_more_renders_empty_and_safe_failure_terminal_states(
    page_factory,
    base_url: str,
    terminal: tuple[str, str | None, str | None],
    expected: str,
) -> None:
    inspected = page_factory()

    def handle(route: Route) -> None:
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}/packages/load-more":
            route.fulfill(status=202, json={"status": "accepted", "requested": 3, "operationRunId": 74})
            return
        if path == f"{PROJECT}/operations/74":
            status, outcome, failure_code = terminal
            route.fulfill(json={"run_id": 74, "status": status, "outcome": outcome, "failure_code": failure_code})
            return
        if path == f"{PROJECT}/packages":
            item = dict(fixture_payloads()[path]["items"][0], status="approved")
            route.fulfill(json={"items": [item]})
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="load-more"]').click()
        inspected.get_by_text(expected, exact=True).wait_for()
        if terminal[0] == "failed":
            assert inspected.get_by_role("button", name="Повторить").is_visible()
    finally:
        inspected.close()


def test_load_more_renders_unresolved_ids_from_server_conflict(
    page_factory, base_url: str
) -> None:
    # A race after the package GET must preserve the project-scoped 409 details.
    inspected = page_factory()

    def handle(route: Route) -> None:
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}/packages/load-more":
            route.fulfill(
                status=409,
                json={
                    "code": "review_unresolved",
                    "requestId": "safe-request",
                    "unresolvedPackageIds": [9102, 9103],
                },
            )
            return
        if path == f"{PROJECT}/packages":
            item = dict(fixture_payloads()[path]["items"][0], status="approved")
            route.fulfill(json={"items": [item]})
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="load-more"]').click()

        hint = inspected.locator("#review-unresolved")
        hint.wait_for()
        assert "№ 9102" in hint.inner_text()
        assert "№ 9103" in hint.inner_text()
        assert inspected.get_by_role(
            "button", name="Подобрать ещё 3 поста"
        ).is_disabled()
        assert inspected.get_by_text(
            "Подбор постов завершился ошибкой.", exact=True
        ).count() == 0
    finally:
        inspected.close()


def test_rejection_closes_detail_only_after_success_and_sends_no_body(
    page_factory, base_url: str
) -> None:
    inspected = page_factory()
    bodies: list[str | None] = []

    def handle(route: Route) -> None:
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        if route.request.method == "POST" and path == f"{PROJECT}/packages/9001/reject":
            bodies.append(route.request.post_data)
            route.fulfill(json={"id": 9001, "status": "rejected"})
            return
        if "/media/packages/" in path:
            route.fulfill(status=200, content_type="image/png", body=PIXEL_PNG)
            return
        route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        inspected.locator('[data-action="reject-package"]').click()
        inspected.get_by_text("Пост отклонён", exact=True).wait_for()
        assert not inspected.locator("#detail-layer").evaluate("dialog => dialog.open")
        assert bodies == [None]
    finally:
        inspected.close()


@pytest.mark.parametrize(("status", "attempt_id", "action", "suffix", "toast"), [
    ("failed", 701, "retry-analysis", "/attempts/701/retry-analysis", "Анализ повторяется"),
    ("rejected", None, "return-to-analysis", "/packages/9001/return-to-analysis", "Материал возвращён в анализ"),
])
def test_manual_analysis_recovery_actions_are_real_owner_commands(
    page_factory, base_url: str, status: str, attempt_id: int | None,
    action: str, suffix: str, toast: str,
) -> None:
    # Break caught: retry/return controls only change local state or leak a raw error.
    inspected = page_factory()
    requests: list[tuple[str, str]] = []
    fixtures = fixture_payloads()
    original = fixtures[f"{PROJECT}/packages/9001"]
    detail = dict(original, status=status)
    if attempt_id is not None:
        detail["attempt_id"] = attempt_id
    fixtures[f"{PROJECT}/packages/9001"] = detail
    install_api(inspected, requests, fixtures=fixtures)
    try:
        inspected.goto(f"{base_url}/#review")
        inspected.locator('[data-action="open-package"]').click()
        inspected.locator(f'[data-action="{action}"]').click()
        inspected.get_by_text(toast, exact=True).wait_for()
        inspected.locator('[data-screen="review"]:not([data-loading])').wait_for()
        assert ("POST", f"{PROJECT}{suffix}") in requests
        assert requests.count(("GET", f"{PROJECT}/packages")) >= 2
    finally:
        inspected.close()


def test_manual_delivery_retry_is_a_project_scoped_owner_command(page_factory, base_url: str) -> None:
    inspected = page_factory()
    requests: list[tuple[str, str]] = []
    operation_reads = 0
    publication_reads = 0

    def handle(route: Route) -> None:
        nonlocal operation_reads, publication_reads
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        requests.append((route.request.method, path))
        if route.request.method == "POST" and path == f"{PROJECT}/deliveries/9001/retry":
            route.fulfill(status=202, json={"status": "accepted", "operationRunId": 81})
        elif path == f"{PROJECT}/operations/81":
            operation_reads += 1
            route.fulfill(json={"run_id": 81, "status": "running" if operation_reads == 1 else "succeeded", "outcome": None if operation_reads == 1 else "completed", "failure_code": None})
        elif path == f"{PROJECT}/publications":
            publication_reads += 1
            route.fulfill(json={"items": [dict(fixture_payloads()[path]["items"][0], status="retryable")]})
        else:
            route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#publications")
        inspected.locator('[data-action="open-delivery"]').click()
        inspected.locator('[data-action="retry-delivery"]').click()
        inspected.get_by_text("Отправка повторяется", exact=True).wait_for()
        assert ("POST", f"{PROJECT}/deliveries/9001/retry") in requests
        assert operation_reads >= 2
        assert publication_reads >= 2
    finally:
        inspected.close()


@pytest.mark.parametrize(("action", "suffix", "toast"), [
    ("new-run", "/operations/search", "Поиск завершён"),
    ("publish-once", "/operations/publish-once", "Публикация завершена"),
])
def test_operation_commands_are_real_and_refresh_journal(page_factory, base_url: str, action: str, suffix: str, toast: str) -> None:
    # Break caught: operational controls are decorative or leave stale journal data.
    inspected = page_factory()
    requests: list[tuple[str, str]] = []
    operation_reads = 0
    journal_reads = 0

    def handle(route: Route) -> None:
        nonlocal operation_reads, journal_reads
        path = "/" + route.request.url.split("/", 3)[-1].split("?", 1)[0]
        requests.append((route.request.method, path))
        if route.request.method == "POST" and path == f"{PROJECT}{suffix}":
            route.fulfill(status=202, json={"status": "accepted", "operationRunId": 82})
        elif path == f"{PROJECT}/operations/82":
            operation_reads += 1
            route.fulfill(json={"run_id": 82, "status": "running" if operation_reads == 1 else "succeeded", "outcome": None if operation_reads == 1 else "completed", "failure_code": None})
        elif path == f"{PROJECT}/operations":
            journal_reads += 1
            route.fulfill(json=fixture_payloads()[path])
        else:
            route.fulfill(json=fixture_payloads().get(path, {}))

    inspected.route("**/api/v1/**", handle)
    try:
        inspected.goto(f"{base_url}/#journal")
        inspected.locator(f'[data-action="{action}"]').first.click()
        inspected.get_by_text(toast, exact=True).wait_for()
        inspected.locator('[data-screen="journal"]:not([data-loading])').wait_for()
        assert ("POST", f"{PROJECT}{suffix}") in requests
        assert operation_reads >= 2
        assert journal_reads >= 2
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


def test_reduced_motion_removes_visible_screen_transition(page_factory, base_url: str) -> None:
    inspected = page_factory(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    install_api(inspected)
    try:
        inspected.goto(f"{base_url}/#overview")
        screen = inspected.locator('[data-screen="overview"]:not([data-loading])')
        screen.wait_for()
        duration = screen.evaluate("element => getComputedStyle(element).animationDuration")
        assert duration in {"0s", "1e-05s"}
    finally:
        inspected.close()


def test_overview_summary_and_logo_keep_approved_optical_alignment(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/#overview")
    page.locator(".studio-strip").wait_for()
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


@pytest.mark.parametrize("width", [360, 768, 1440])
def test_queue_timeline_rule_runs_through_marker_centres(
    page: Page, base_url: str, width: int
) -> None:
    # Break caught: a responsive grid offset separates the day rhythm rule from its markers.
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{base_url}/#queue")
    assert page.locator('[data-screen="queue"]').is_visible()
    assert page.locator("h1").inner_text() == "Очередь публикаций"
    geometry = page.locator(".timeline").evaluate("""element => {
        const timeline = element.getBoundingClientRect();
        const marker = element.querySelector('.timeline-marker').getBoundingClientRect();
        const rule = getComputedStyle(element, '::before');
        return {
            ruleX: timeline.x + parseFloat(rule.left) + parseFloat(rule.width) / 2,
            markerX: marker.x + marker.width / 2,
        };
    }""")
    assert geometry["ruleX"] == pytest.approx(geometry["markerX"], abs=0.5)


def test_mobile_review_keeps_thumbnail_copy_and_both_actions_visible(page: Page, base_url: str) -> None:
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{base_url}/#review")
    card = page.locator(".content-card").first
    thumbnail = card.locator(".material-thumb").bounding_box()
    copy = card.locator(".content-card-copy").bounding_box()
    assert thumbnail is not None and copy is not None
    assert thumbnail["x"] + thumbnail["width"] <= copy["x"]

    page.locator('[data-action="open-package"]').click()
    page.locator('[data-action="reject-package"]').wait_for()
    assert page.locator('[data-action="reject-package"]').is_visible()
    assert page.locator("#reject-reason").count() == 0
    assert page.locator('[data-action="approve-package"]').is_visible()


def test_journal_starts_with_operational_content_without_status_banner(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/#journal")
    assert page.locator(".system-banner").count() == 0
    assert page.locator(".journal-list").is_visible()


def test_overview_and_journal_render_runtime_and_recent_operations(
    page: Page, base_url: str
) -> None:
    # Break caught: operational fields exist in JSON but remain invisible on both screens.
    page.goto(f"{base_url}/#overview")
    recent = page.locator(".recent-operations")
    recent.wait_for()
    assert recent.get_by_text("Поиск и подготовка", exact=True).is_visible()
    assert recent.get_by_text("Успешно", exact=True).is_visible()
    heading_x = recent.locator(".panel-title").bounding_box()["x"]
    operation_x = recent.locator(".operation-summary li").first.bounding_box()["x"]
    assert operation_x == pytest.approx(heading_x, abs=1)
    assert page.get_by_text("7 / 12", exact=True).is_visible()
    assert page.get_by_text("18", exact=True).is_visible()
    assert page.get_by_text("4 / 3", exact=True).is_visible()
    assert page.get_by_text("6", exact=True).is_visible()

    page.goto(f"{base_url}/#journal")
    runtime = page.locator(".runtime-state")
    runtime.wait_for()
    assert runtime.get_by_text("База данных: Доступно", exact=True).is_visible()
    assert runtime.get_by_text("Планировщик: Активен", exact=True).is_visible()
    assert page.get_by_text("Вручную", exact=True).is_visible()
    page.locator('[data-action="open-run"]').click()
    detail = page.locator("#detail-content")
    assert detail.get_by_text("gpt-5.6-luna", exact=True).is_visible()
    assert detail.get_by_text("high", exact=True).is_visible()
    assert detail.get_by_text("3", exact=True).is_visible()
    assert detail.get_by_text("2", exact=True).is_visible()
