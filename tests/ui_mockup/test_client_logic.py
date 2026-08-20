from __future__ import annotations

from playwright.sync_api import Page

from tests.ui_mockup.browser_support import install_api


def test_api_client_uses_csrf_only_for_mutations_and_sanitizes_errors(page_factory, base_url: str) -> None:
    page = page_factory(viewport={"width": 1280, "height": 900})
    install_api(page)
    page.goto(base_url)
    result = page.evaluate("""async () => {
      const calls = [];
      window.fetch = async (url, options = {}) => {
        calls.push({url, method: options.method || 'GET', headers: [...new Headers(options.headers || {}).entries()], body: options.body ?? null});
        if (url.endsWith('/bootstrap')) return new Response(JSON.stringify({csrfToken: 'browser-fixture-capability'}));
        if (url.endsWith('/delete')) return new Response(null, {status: 204});
        if (url.endsWith('/json-error')) return new Response(JSON.stringify({code: 'blocked', unresolvedPackageIds: [1, -1, '2', ...Array.from({length: 60}, (_, i) => i + 3)]}), {status: 409});
        return new Response('private upstream response', {status: 502});
      };
      const api = await import('/api.js');
      await api.getBootstrap();
      const deleted = await api.request('/delete', {method: 'DELETE'});
      const errors = [];
      for (const path of ['/json-error', '/text-error']) try { await api.request(path); } catch (error) { errors.push({status: error.status, code: error.code, ids: error.unresolvedPackageIds, message: error.message}); }
      return {calls, deleted, errors};
    }""")
    assert result["deleted"] is None
    delete = next(call for call in result["calls"] if call["method"] == "DELETE")
    assert ["x-postify-csrf", "browser-fixture-capability"] in delete["headers"]
    assert delete["body"] is None
    assert result["errors"][0]["ids"] == [1, *range(3, 52)]
    assert result["errors"][1] == {"status": 502, "code": "request_failed", "ids": [], "message": "request_failed"}


def test_settings_serializer_and_validator_cover_typed_schedule_and_error_reset(page_factory, base_url: str) -> None:
    page: Page = page_factory()
    install_api(page)
    page.goto(base_url)
    result = page.evaluate("""async () => {
      const {serializeSettingsSection, validateSettingsSection} = await import('/settings.js');
      const host = document.createElement('div');
      host.innerHTML = `<form data-settings-form="schedule" novalidate><p data-settings-error></p><input data-source-schedule-id="7" value=" 0 8 * * * "><fieldset data-route-schedule-id="9"><input name="autopublish" type="checkbox" checked><input name="slots" value="09:00"><input name="slots" value="14:00"><input name="slots" value="19:00"></fieldset></form>`;
      const schedule = host.querySelector('form');
      const payload = serializeSettingsSection(schedule);
      const valid = validateSettingsSection(schedule, payload);
      schedule.querySelectorAll('input[name="slots"]')[2].value = '29:00';
      const invalid = validateSettingsSection(schedule, serializeSettingsSection(schedule));
      const errorId = schedule.querySelector('[data-settings-error]').id;
      const described = schedule.getAttribute('aria-describedby');
      schedule.querySelectorAll('input[name="slots"]')[2].value = '19:00';
      const repaired = validateSettingsSection(schedule, serializeSettingsSection(schedule));
      const main = document.createElement('form'); main.dataset.settingsForm = 'main'; main.innerHTML = '<p data-settings-error></p><input name="timezone" value="Mars/Olympus">';
      const timezone = validateSettingsSection(main, {timezone: 'Mars/Olympus'});
      const generation = document.createElement('form'); generation.dataset.settingsForm = 'generation'; generation.innerHTML = '<p data-settings-error></p><input name="daily_package_limit"><input name="daily_analysis_limit">';
      const limit = validateSettingsSection(generation, {fresh_share_percent: 50, reserve_share_percent: 50, daily_package_limit: 3, daily_analysis_limit: 2});
      return {payload, valid, invalid, errorId, described, repaired, after: schedule.getAttribute('aria-describedby'), timezone, timezoneError: main.querySelector('[data-settings-error]').textContent, limit, limitError: generation.querySelector('[data-settings-error]').textContent};
    }""")
    assert result["payload"] == {"sources": [{"id": 7, "schedule": "0 8 * * *"}], "routes": [{"id": 9, "autopublish": True, "slots": ["09:00", "14:00", "19:00"]}]}
    assert result["valid"] is True
    assert result["invalid"] is False
    assert result["described"] == result["errorId"]
    assert result["repaired"] is True and result["after"] is None
    assert result["timezone"] is False and "часовой пояс" in result["timezoneError"]
    assert result["limit"] is False and "пакетов" in result["limitError"]


def test_provider_markup_is_escaped_and_switches_field_shape(page_factory, base_url: str) -> None:
    page = page_factory()
    install_api(page)
    page.goto(base_url)
    markup = page.evaluate("""async () => {
      const {renderProviderConfiguration} = await import('/settings.js');
      const providers = {sources: [{code: 'first', fields: [{name: 'label', label: '<img>', type: 'text', required: true}]}, {code: 'second', fields: [{name: 'limit', label: 'Limit', type: 'number', min: 1, max: 2}]}]};
      return [renderProviderConfiguration(providers, 'sources', 'first', {}), renderProviderConfiguration(providers, 'sources', 'second', {}), renderProviderConfiguration(providers, 'sources', 'missing', {})];
    }""")
    assert "&lt;img&gt;" in markup[0] and 'name="configuration.label"' in markup[0]
    assert 'type="number"' in markup[1] and 'name="configuration.limit"' in markup[1]
    assert markup[2] == ""


def test_settings_native_required_custom_cta_slot_count_and_omit_empty(page_factory, base_url: str) -> None:
    page = page_factory()
    install_api(page)
    page.goto(base_url)
    result = page.evaluate("""async () => {
      const {serializeSettingsSection, validateSettingsSection} = await import('/settings.js');
      const host = document.createElement('div');
      host.innerHTML = `<form data-settings-form="main" novalidate><p data-settings-error></p><input name="name" required value=""></form>`;
      const required = host.firstElementChild;
      const nativeInvalid = validateSettingsSection(required, {name: ''});
      const requiredError = required.querySelector('[data-settings-error]');
      const cta = document.createElement('form'); cta.dataset.settingsForm = 'cta'; cta.innerHTML = '<p data-settings-error></p><input name="custom_url">';
      const url = cta.elements.custom_url; url.value = 'ftp://example.test';
      const badCta = validateSettingsSection(cta, {link_mode: 'custom', custom_url: url.value});
      const ctaError = cta.querySelector('[data-settings-error]'); const ctaText = ctaError.textContent; const ctaLink = cta.elements.custom_url.getAttribute('aria-describedby'); url.value = 'https://example.test';
      const goodCta = validateSettingsSection(cta, {link_mode: 'custom', custom_url: url.value});
      const schedule = document.createElement('form'); schedule.dataset.settingsForm = 'schedule'; schedule.innerHTML = '<p data-settings-error></p><fieldset data-route-schedule-id="1"><input name="autopublish" type="checkbox"><input name="slots" value="09:00"><input name="slots" value="14:00"></fieldset>';
      const badSlots = validateSettingsSection(schedule, serializeSettingsSection(schedule));
      const slotsError = schedule.querySelector('[data-settings-error]'); const slotsText = slotsError.textContent; const slotsLink = schedule.querySelector('input[name="slots"]').getAttribute('aria-describedby');
      schedule.querySelector('fieldset').insertAdjacentHTML('beforeend', '<input name="slots" value="19:00">');
      const goodSlots = validateSettingsSection(schedule, serializeSettingsSection(schedule));
      const omit = document.createElement('form'); omit.dataset.settingsForm = 'main'; omit.innerHTML = '<input name="blank" data-omit-empty value="   "><input name="present" data-omit-empty value=" x ">';
      return {nativeInvalid, requiredText: requiredError.textContent, requiredLink: [required.getAttribute('aria-describedby'), required.elements.name.getAttribute('aria-describedby'), requiredError.id], badCta, ctaText, ctaLink, goodCta, ctaCleared: cta.getAttribute('aria-describedby'), badSlots, slotsText, slotsLink, goodSlots, slotsCleared: schedule.getAttribute('aria-describedby'), omit: serializeSettingsSection(omit)};
    }""")
    assert result["nativeInvalid"] is False and "обязатель" in result["requiredText"].casefold()
    assert result["requiredLink"][0] == result["requiredLink"][1] == result["requiredLink"][2]
    assert result["badCta"] is False and "HTTP(S)" in result["ctaText"] and result["ctaLink"]
    assert result["goodCta"] is True and result["ctaCleared"] is None
    assert result["badSlots"] is False and "три" in result["slotsText"].casefold() and result["slotsLink"]
    assert result["goodSlots"] is True and result["slotsCleared"] is None
    assert result["omit"] == {"present": "x"}
