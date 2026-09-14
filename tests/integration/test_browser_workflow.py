"""Built SPA -> HTTP -> application -> PostgreSQL, with only AI substituted."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import re
import socket
from threading import Thread
from time import monotonic, sleep

from cryptography.fernet import Fernet
from PIL import Image
import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn

from postify.adapters.ai.codex_provider import CodexModelProvider
from postify.adapters.ai.mock_provider import MockModelProvider
from postify.application.auth.service import AuthService
from postify.config import Settings
from postify.domain.auth.models import TelegramIdentity
from postify.infrastructure.repositories.sqlalchemy_users import SqlAlchemyUserRepository
from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from postify.web.services import WebApplication


pytestmark = pytest.mark.integration


@pytest.fixture
def browser_application(migrated_database_url, tmp_path, monkeypatch):
    # The AI boundary is deterministic; generation, repair and validation remain real.
    calls = []

    def complete(self, prompt, **kwargs):
        calls.append(prompt)
        if "verdict" in (kwargs.get("output_schema") or {}).get("properties", {}):
            return '{"verdict":"match","detail":"The green field matches the farming post"}'
        if "claims:[" in prompt:
            return json.dumps({"claims": []})
        if '"items":' in prompt:
            rule_ids = re.findall(r"^(\d+):", prompt, re.MULTILINE)
            return json.dumps({"items": [{"rule_id": int(rule_id), "passed": True, "evidence": "Matches"} for rule_id in rule_ids]})
        if "rules:[" in prompt:
            return json.dumps({"rules": [{"text": "Use clear language", "severity": "warn"}]})
        generation_count = sum("Напиши готовый Telegram" in previous for previous in calls)
        post_text = "Green field. Practical farming advice."
        if generation_count == 1 and "999" not in prompt:
            post_text += " Yield increased by 999%."
        return json.dumps({"post_text": post_text, "media_asset_id": 1, "media_rationale": "The image shows a green field."})

    monkeypatch.setattr(CodexModelProvider, "complete", complete)
    monkeypatch.setattr(MockModelProvider, "caption_image", lambda self, path: "Green field")
    settings = Settings(
        database_url=migrated_database_url,
        content_media_dir=tmp_path / "media",
        ai_media_provider="mock",
        postify_secret_key=SecretStr(Fernet.generate_key().decode()),
    )
    engine = create_engine(migrated_database_url)
    auth = AuthService(SqlAlchemyUserRepository(sessionmaker(engine)), bot_username="browser_test_bot")
    app = create_app(WebContainer(WebApplication(settings)), auth=auth)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = monotonic() + 10
    while not server.started and monotonic() < deadline:
        sleep(0.02)
    assert server.started, "Browser application did not start"
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}", auth, calls
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        engine.dispose()
        assert not thread.is_alive(), "Browser application did not stop"


def _assert_rendered(page, screenshot):
    assert page.locator("body").inner_text().strip()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontal overflow"
    page.screenshot(path=str(screenshot), full_page=True)
    with Image.open(screenshot) as image:
        assert len(image.convert("RGB").getcolors(image.width * image.height)) > 100


def _api(page, path):
    response = page.request.get(path)
    assert response.ok, response.text()
    return response.json()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
def test_browser_telegram_login(browser_application, viewport):
    playwright = pytest.importorskip("playwright.sync_api")
    base_url, auth, _ = browser_application
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=viewport, base_url=base_url)
        context.route("https://t.me/**", lambda route: route.fulfill(status=200, body="Telegram launch page"))
        page = context.new_page()
        page.set_default_timeout(10000)
        page.goto(base_url)
        with page.expect_popup() as popup, page.expect_response("**/api/auth/login") as response:
            page.get_by_role("button", name="Войти через Telegram").click()
        login = response.value.json()
        popup.value.wait_for_url(login["telegram_url"])
        assert popup.value.evaluate("window.opener === null")
        popup.value.close()
        token = login["telegram_url"].split("start=autopost_login_", 1)[1]
        assert context.request.get("/api/me").status == 401
        auth.handle_bot_start(telegram_token=token, identity=TelegramIdentity("701", "browser_editor", "Browser Editor"))
        assert context.request.get("/api/me").status == 401
        auth.handle_bot_decision(telegram_token=token, telegram_user_id="701", approved=True)
        page.get_by_role("button", name="Создать проект", exact=True).wait_for()
        assert context.request.get("/api/me").json()["telegram_user_id"] == "701"
        browser.close()


def test_browser_editor_workflow(browser_application, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    base_url, auth, calls = browser_application
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, base_url=base_url)
        context.route("https://t.me/**", lambda route: route.fulfill(status=200, body="Telegram launch page"))
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base_url)
        with page.expect_response("**/api/auth/login") as login_response:
            page.get_by_role("button", name="Войти через Telegram").click()
        login = login_response.value.json()
        token = login["telegram_url"].split("start=autopost_login_", 1)[1]
        auth.handle_bot_start(telegram_token=token, identity=TelegramIdentity("701", "browser_editor", "Browser Editor"))
        auth.handle_bot_decision(telegram_token=token, telegram_user_id="701", approved=True)
        page.get_by_role("button", name="Создать проект", exact=True).click()
        page.get_by_role("dialog").get_by_label("Название", exact=True).fill("Browser farm")
        page.get_by_role("dialog").get_by_role("button", name="Создать проект", exact=True).click()
        page.get_by_role("button", name="Добавить слот", exact=True).wait_for()
        project_id = _api(page, "/api/projects")[0]["id"]
        assert _api(page, "/api/me")["telegram_user_id"] == "701"

        page.get_by_role("button", name="Настройки", exact=True).click()
        page.get_by_role("textbox", name="Промпт агента", exact=True).fill("Practical farming guidance")
        with page.expect_response(f"**/api/projects/{project_id}") as saved:
            page.get_by_role("button", name="Сохранить промпт", exact=True).click()
        assert saved.value.ok
        assert _api(page, f"/api/projects/{project_id}")["project_prompt"] == "Practical farming guidance"
        # Проверяем сохранение после перезагрузки и завершаем обновление формы
        # перед заполнением независимых настроек канала.
        page.reload()
        page.get_by_role("button", name="Настройки", exact=True).click()
        assert page.get_by_role("textbox", name="Промпт агента", exact=True).input_value() == "Practical farming guidance"
        page.get_by_placeholder("@channel", exact=True).fill("@browser_test_channel")
        page.locator('input[type="password"]').fill("777:browser-test-token")
        with page.expect_response(f"**/api/projects/{project_id}/channel") as channel_response:
            page.get_by_role("button", name="Сохранить канал", exact=True).click()
        assert channel_response.value.ok
        assert "browser-test-token" not in channel_response.value.text()

        page.get_by_role("button", name="Изображения", exact=True).click()
        image_path = tmp_path / "field.png"
        Image.new("RGB", (400, 240), (30, 140, 60)).save(image_path)
        page.locator('input[type="file"]').set_input_files(str(image_path))
        page.get_by_text("Изображения загружены и описаны", exact=True).wait_for()
        asset = _api(page, f"/api/projects/{project_id}/media")["items"][0]
        assert asset["caption_status"] == "ready"
        assert page.request.get(asset["url"]).ok
        _assert_rendered(page, tmp_path / "media-desktop.png")

        page.get_by_role("button", name="Контент-план", exact=True).click()
        page.get_by_role("button", name="Добавить слот", exact=True).click()
        future = datetime.now(UTC) + timedelta(days=3)
        page.get_by_label("Дата публикации", exact=True).fill(future.date().isoformat())
        page.get_by_label("Промпт поста", exact=True).fill("Green field and practical farming advice")
        page.get_by_role("dialog").get_by_role("button", name="Сохранить", exact=True).click()
        # Держим ответ поста в generating, затем отпускаем без reload страницы.
        pending_preview = {"value": True}
        def preview_response(route):
            response = route.fetch()
            body = response.json()
            if pending_preview["value"]:
                body["status"] = "generating"
            route.fulfill(response=response, json=body)
        page.route(re.compile(r"/api/projects/\d+/posts/\d+$"), preview_response)
        page.get_by_role("button", name="Сгенерировать сейчас", exact=True).click()
        page.get_by_text("Собираем пост", exact=True).wait_for()
        assert page.locator('[aria-busy="true"] .blur-sm').count() == 1
        pending_preview["value"] = False
        page.get_by_text("Собираем пост", exact=True).wait_for(state="hidden")
        page.unroute(re.compile(r"/api/projects/\d+/posts/\d+$"), preview_response)
        page.get_by_role("button", name="Править текст", exact=True).wait_for()
        assert calls
        dialog = page.get_by_role("dialog")
        assert not dialog.get_by_text("Проверки", exact=True).count()
        assert not dialog.get_by_text("Формальные правила", exact=True).count()
        assert dialog.get_by_role("heading").inner_text() == "Пост контент-плана"
        prompt = dialog.locator("details")
        assert prompt.get_attribute("open") is None
        prompt.locator("summary").click()
        assert prompt.locator("p").is_visible()
        assert prompt.locator("p").inner_text() == "Green field and practical farming advice"
        prompt.locator("summary").click()
        assert not prompt.locator("p").is_visible()
        page.get_by_role("button", name="Править текст", exact=True).click()
        page.get_by_role("dialog").get_by_role("textbox").fill("Green field. Edited practical farming advice.")
        page.get_by_role("dialog").get_by_role("button", name="Сохранить", exact=True).click()
        with page.expect_response("**/approve") as approved_response:
            page.get_by_role("button", name="Одобрить", exact=True).click()
        assert approved_response.value.ok, approved_response.value.text()
        page.get_by_role("button", name="Вернуть на доработку", exact=True).wait_for()
        posts = _api(page, f"/api/projects/{project_id}/posts")
        assert posts[0]["status"] == "approved"
        _assert_rendered(page, tmp_path / "post-desktop.png")
        page.set_viewport_size({"width": 390, "height": 844})
        _assert_rendered(page, tmp_path / "post-mobile.png")
        with page.expect_response("**/reject") as rejected_response:
            page.get_by_role("button", name="Вернуть на доработку", exact=True).click()
        assert rejected_response.value.ok, rejected_response.value.text()
        page.get_by_role("button", name="Одобрить", exact=True).wait_for()
        assert _api(page, f"/api/projects/{project_id}/posts")[0]["status"] == "needs_review"
        page.keyboard.press("Escape")
        assert not page.get_by_text("Режим", exact=True).count()

        # UI representation of a published slot; real Telegram delivery is tested separately.
        published_slots = _api(page, f"/api/projects/{project_id}/plan?from={future.date()}&to={future.date()}")
        for item in published_slots:
            item["status"] = "published"
            item["publish_at"] = datetime.now(UTC).replace(hour=12).isoformat()
            if item.get("post"):
                item["post"]["status"] = "published"

        def published_plan(route):
            route.fulfill(status=200, json=published_slots)

        page.route("**/plan?*", published_plan)
        for viewport in ({"width": 1440, "height": 1000}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            for view in ("Неделя", "Месяц", "Список"):
                page.get_by_role("button", name=view, exact=True).click()
                badge = page.locator("#root").get_by_text("Опубликовано", exact=True)
                badge.wait_for()
                assert badge.locator("svg.lucide-check").count() == 1
                _assert_rendered(page, tmp_path / f"published-{view}-{viewport['width']}.png")
        page.unroute("**/plan?*", published_plan)
        page.get_by_role("button", name="Открыть меню", exact=True).click()
        page.get_by_role("button", name="Настройки", exact=True).click()
        page.get_by_role("button", name="Аккаунт", exact=True).click()
        _assert_rendered(page, tmp_path / "account-mobile.png")
        page.get_by_role("button", name="Выйти", exact=True).click()
        page.get_by_role("button", name="Войти через Telegram", exact=True).wait_for()
        assert page.request.get("/api/me").status == 401
        assert errors == []
        context.close()
        browser.close()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
def test_browser_settings_and_media_management(browser_application, tmp_path, viewport):
    playwright = pytest.importorskip("playwright.sync_api")
    base_url, auth, _ = browser_application
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=viewport, base_url=base_url)
        context.route("https://t.me/**", lambda route: route.fulfill(status=200, body="Telegram launch page"))
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def navigate(name):
            if viewport["width"] < 768:
                page.get_by_role("button", name="Открыть меню", exact=True).click()
            page.get_by_role("button", name=name, exact=True).click()

        page.goto(base_url)
        with page.expect_response("**/api/auth/login") as response:
            page.get_by_role("button", name="Войти через Telegram").click()
        token = response.value.json()["telegram_url"].split("start=autopost_login_", 1)[1]
        auth.handle_bot_start(telegram_token=token, identity=TelegramIdentity("701", "browser_editor", "Browser Editor"))
        auth.handle_bot_decision(telegram_token=token, telegram_user_id="701", approved=True)
        page.get_by_role("button", name="Создать проект", exact=True).click()
        page.get_by_role("dialog").get_by_label("Название", exact=True).fill("Management E2E")
        page.get_by_role("dialog").get_by_role("button", name="Создать проект", exact=True).click()
        page.get_by_role("button", name="Добавить слот", exact=True).wait_for()
        project_id = _api(page, "/api/projects")[0]["id"]
        navigate("Настройки")
        fields = page.locator("section").filter(has=page.get_by_role("heading", name="Проект", exact=True)).locator("input")
        fields.nth(0).fill("Renamed E2E")
        fields.nth(1).fill("Asia/Bangkok")
        publication = page.locator("section").filter(has=page.get_by_role("heading", name="Публикация", exact=True))
        publication.get_by_role("combobox").click()
        page.get_by_role("option", name="автопубликация", exact=True).click()
        publication.locator('input[type="number"]').nth(0).fill("45")
        publication.locator('input[type="number"]').nth(1).fill("3")
        with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith(f"/api/projects/{project_id}")) as saved:
            page.get_by_role("button", name="Сохранить настройки", exact=True).click()
        assert saved.value.ok
        page.reload()
        navigate("Настройки")
        assert fields.nth(0).input_value() == "Renamed E2E"
        assert fields.nth(1).input_value() == "Asia/Bangkok"
        project = _api(page, f"/api/projects/{project_id}")
        assert (project["publication_mode"], project["generation_lead_minutes"], project["media_reuse_days"]) == ("auto", 45, 3)
        _assert_rendered(page, tmp_path / "settings.png")

        navigate("Изображения")
        image_path = tmp_path / "field.png"
        Image.new("RGB", (400, 240), (30, 140, 60)).save(image_path)
        page.locator('input[type="file"]').set_input_files(str(image_path))
        page.get_by_text("Изображения загружены и описаны", exact=True).wait_for()
        page.get_by_placeholder("Поиск по описанию").fill("nonexistent")
        page.get_by_text("Пул пуст", exact=True).wait_for()
        page.get_by_placeholder("Поиск по описанию").fill("Green")
        page.get_by_role("switch", name="Вывести картинку из подбора", exact=True).click()
        page.get_by_role("switch", name="Вернуть картинку в подбор", exact=True).wait_for()
        assert _api(page, f"/api/projects/{project_id}/media")["items"][0]["enabled"] is False
        page.get_by_role("switch", name="Показывать только доступные изображения", exact=True).click()
        page.get_by_text("Пул пуст", exact=True).wait_for()
        page.get_by_role("switch", name="Показывать только доступные изображения", exact=True).click()
        page.get_by_role("switch", name="Вернуть картинку в подбор", exact=True).click()
        page.get_by_role("switch", name="Вывести картинку из подбора", exact=True).wait_for()
        page.get_by_role("button", name="Описать заново", exact=True).click()
        page.get_by_text("Описание обновлено", exact=True).wait_for()
        _assert_rendered(page, tmp_path / "media-managed.png")
        page.get_by_role("button", name="Удалить изображение из пула", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Удалить", exact=True).click()
        page.get_by_text("Пул пуст", exact=True).wait_for()
        assert _api(page, f"/api/projects/{project_id}/media")["items"] == []

        navigate("Контент-план")
        planned_day = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
        plan_path = f"/api/projects/{project_id}/plan?from={planned_day}&to={planned_day}"
        page.get_by_role("button", name="Добавить слот", exact=True).click()
        page.get_by_label("Дата публикации", exact=True).fill(planned_day)
        page.get_by_label("Промпт поста", exact=True).fill("Green field management")
        page.get_by_role("dialog").get_by_role("button", name="Сохранить", exact=True).click()
        page.get_by_role("button", name="Изменить промпт", exact=True).click()
        page.get_by_label("Промпт поста", exact=True).fill("Green field edited")
        page.get_by_role("dialog").get_by_role("button", name="Сохранить", exact=True).click()
        page.get_by_role("dialog").locator("summary").filter(has_text="Green field edited").wait_for()
        with page.expect_response("**/skip") as skipped:
            page.get_by_role("button", name="Пропустить", exact=True).click()
        assert skipped.value.ok
        assert _api(page, plan_path)[0]["status"] == "skipped"
        page.get_by_role("button", name="Удалить слот из плана", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Удалить", exact=True).click()
        page.get_by_text("Слот удалён", exact=True).wait_for()
        assert _api(page, plan_path) == []
        for view in ("Неделя", "Месяц", "Список"):
            page.get_by_role("button", name=view, exact=True).click()
            _assert_rendered(page, tmp_path / f"plan-{view}.png")
        assert errors == []
        context.close()
        browser.close()


@pytest.mark.parametrize('viewport', [{'width': 1440, 'height': 1000}, {'width': 390, 'height': 844}])
def test_browser_restores_session_and_last_project(browser_application, tmp_path, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    base_url, auth, _ = browser_application
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=viewport, base_url=base_url)
        context.route('https://t.me/**', lambda route: route.fulfill(status=200, body='Telegram launch page'))
        page = context.new_page()
        page.set_default_timeout(15000)
        page.goto(base_url)
        with page.expect_popup() as popup, page.expect_response('**/api/auth/login') as response:
            page.get_by_role('button', name='Войти через Telegram').click()
        login = response.value.json()
        popup.value.wait_for_url(login['telegram_url'])
        popup.value.close()
        token = login['telegram_url'].split('start=autopost_login_', 1)[1]
        auth.handle_bot_start(telegram_token=token, identity=TelegramIdentity('701', 'browser_editor', 'Browser Editor'))
        auth.handle_bot_decision(telegram_token=token, telegram_user_id='701', approved=True)
        page.get_by_role('button', name='Создать проект', exact=True).click()
        page.get_by_label('Название', exact=True).fill('Empty project')
        page.get_by_role('dialog').get_by_role('button', name='Создать проект', exact=True).click()
        page.get_by_role('button', name='Добавить слот', exact=True).wait_for()
        if viewport['width'] < 768:
            page.get_by_role('button', name='Открыть меню', exact=True).click()
        page.get_by_role('button', name='EP Empty project', exact=True).click()
        page.get_by_role('menuitem', name='Создать проект').click()
        page.get_by_label('Название', exact=True).fill('My project')
        page.get_by_role('dialog').get_by_role('button', name='Создать проект', exact=True).click()
        page.get_by_role('button', name='Добавить слот', exact=True).wait_for()
        if viewport['width'] < 768:
            page.get_by_role('button', name='Открыть меню', exact=True).click()
        page.get_by_role('button', name='Изображения', exact=True).click()
        image_path = tmp_path / 'field.png'
        Image.new('RGB', (400, 240), (30, 140, 60)).save(image_path)
        page.locator('input[type="file"]').set_input_files(str(image_path))
        page.get_by_text('Изображения загружены и описаны', exact=True).wait_for()
        if viewport['width'] < 768:
            page.get_by_role('button', name='Открыть меню', exact=True).click()
        page.get_by_role('button', name='Контент-план', exact=True).click()
        page.get_by_role('button', name='Добавить слот', exact=True).click()
        page.get_by_label('Дата публикации', exact=True).fill((datetime.now(UTC) + timedelta(days=2)).date().isoformat())
        page.get_by_label('Промпт поста', exact=True).fill('Green field saved plan')
        page.get_by_role('dialog').get_by_role('button', name='Сохранить', exact=True).click()
        page.get_by_role('button', name='Сгенерировать сейчас', exact=True).wait_for()
        page.keyboard.press('Escape')
        remembered = page.evaluate("localStorage.getItem('autoposttg:last-project:1')")
        assert remembered == '2'
        page.evaluate("localStorage.removeItem('csrf')")
        page.reload()
        page.locator('#root').get_by_text('Green field saved plan', exact=True).wait_for()
        page.keyboard.press('Escape')
        assert page.get_by_role('button', name='Войти через Telegram').count() == 0
        assert page.evaluate("Boolean(localStorage.getItem('csrf'))")
        if viewport['width'] < 768:
            page.get_by_role('button', name='Открыть меню', exact=True).click()
        page.get_by_role('button', name='Изображения', exact=True).click()
        page.get_by_role('img', name='Green field', exact=True).wait_for()
        with page.expect_response('**/media/1') as updated:
            page.get_by_role('switch', name='Вывести картинку из подбора').click()
        assert updated.value.ok, updated.value.text()
        assert _api(page, '/api/projects/2/media')['items'][0]['enabled'] is False
        context.route('**/api/me', lambda route: route.fulfill(status=503, json={'error': {'code': 'unavailable', 'message': 'unavailable'}}))
        page.reload()
        page.get_by_text('Сервер временно недоступен', exact=True).wait_for()
        assert page.get_by_role('button', name='Войти через Telegram').count() == 0
        context.unroute('**/api/me')
        page.get_by_role('button', name='Повторить подключение').click()
        page.get_by_role('img', name='Green field', exact=True).wait_for()
        assert page.evaluate("localStorage.getItem('autoposttg:last-project:1')") == '2'
        browser.close()


def test_browser_closes_telegram_tab_when_login_request_fails(browser_application):
    playwright = pytest.importorskip('playwright.sync_api')
    base_url, *_ = browser_application
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(base_url=base_url)
        context.route('**/api/auth/login', lambda route: route.fulfill(status=503, json={
            'error': {'code': 'telegram_unavailable', 'message': 'Вход временно недоступен'},
        }))
        page = context.new_page()
        page.goto(base_url)
        with page.expect_popup() as popup:
            page.get_by_role('button', name='Войти через Telegram').click()
        page.get_by_text('Вход временно недоступен', exact=True).wait_for()
        assert popup.value.is_closed()
        assert len(context.pages) == 1
        browser.close()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
def test_browser_uploads_while_captioning_and_reads_full_description(
    browser_application, tmp_path, monkeypatch, viewport
):
    from threading import Event
    from playwright.sync_api import sync_playwright, expect

    started, release = Event(), Event()
    caption = "На переднем плане — река. " * 80 + "Конец полного описания."

    def slow_caption(self, path):
        started.set()
        assert release.wait(timeout=30)
        return caption

    monkeypatch.setattr(MockModelProvider, "caption_image", slow_caption)
    base_url, auth, _ = browser_application
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport=viewport, base_url=base_url)
        page.set_default_timeout(10000)
        try:
            page.goto(base_url)
            with page.expect_response("**/api/auth/login") as response:
                page.get_by_role("button", name="Войти через Telegram").click()
            token = response.value.json()["telegram_url"].split("start=autopost_login_", 1)[1]
            auth.handle_bot_start(telegram_token=token, identity=TelegramIdentity("709", "media_editor", "Media Editor"))
            auth.handle_bot_decision(telegram_token=token, telegram_user_id="709", approved=True)
            page.get_by_role("button", name="Создать проект", exact=True).click()
            page.get_by_role("dialog").get_by_label("Название", exact=True).fill("Media test")
            page.get_by_role("dialog").get_by_role("button", name="Создать проект", exact=True).click()
            page.get_by_role("button", name="Добавить слот", exact=True).wait_for()
            project_id = _api(page, "/api/projects")[0]["id"]
            page.goto(base_url + "/#/media")
            page.get_by_role("button", name="Загрузить", exact=True).wait_for()
            files = []
            for color in ("red", "blue", "green"):
                path = tmp_path / f"{color}.png"
                Image.new("RGB", (400, 240), color).save(path)
                files.append(str(path))
            for batch in (files[:2], files[2:]):
                with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith(f"/api/projects/{project_id}/media")) as response:
                    page.locator('input[type="file"]').set_input_files(batch)
                assert response.value.status == 202
                expect(page.get_by_role("button", name="Загрузить", exact=True)).to_be_enabled()
                assert started.wait(timeout=3)
            expect(page.get_by_text("описание готовится", exact=True)).to_have_count(3)
            release.set()
            expect(page.get_by_text("описано", exact=True)).to_have_count(3)
            page.get_by_role("button", name="Смотреть описание", exact=True).first.click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_text(caption, exact=True)).to_be_visible()
            page.wait_for_function("Array.from(document.getAnimations()).every(a => a.effect.getComputedTiming().iterations === Infinity || a.playState === 'finished')")
            _assert_rendered(page, tmp_path / "full-description.png")
            dialog.get_by_role("button", name="Закрыть", exact=True).click()
            expect(dialog).not_to_be_visible()
        finally:
            release.set()
            browser.close()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}])
def test_browser_missing_image_recovery(browser_application, tmp_path, viewport, monkeypatch):
    from playwright.sync_api import sync_playwright, expect

    original_complete = CodexModelProvider.complete
    def complete_text_only(self, prompt, **kwargs):
        output = original_complete(self, prompt, **kwargs)
        if "Напиши готовый Telegram" in prompt:
            data = json.loads(output)
            data.update(media_asset_id=None, media_rationale="Без изображения")
            return json.dumps(data)
        return output
    monkeypatch.setattr(CodexModelProvider, "complete", complete_text_only)
    base_url, auth, _ = browser_application
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport=viewport, base_url=base_url)
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(base_url)
            with page.expect_response("**/api/auth/login") as response:
                page.get_by_role("button", name="Войти через Telegram").click()
            token = response.value.json()["telegram_url"].split("start=autopost_login_", 1)[1]
            auth.handle_bot_start(telegram_token=token, identity=TelegramIdentity("710", "recovery_editor", "Recovery Editor"))
            auth.handle_bot_decision(telegram_token=token, telegram_user_id="710", approved=True)
            page.get_by_role("button", name="Создать проект", exact=True).click()
            page.get_by_role("dialog").get_by_label("Название", exact=True).fill("Image recovery")
            page.get_by_role("dialog").get_by_role("button", name="Создать проект", exact=True).click()
            page.get_by_role("button", name="Добавить слот", exact=True).click()
            future = datetime.now(UTC) + timedelta(days=1)
            page.get_by_label("Дата публикации", exact=True).fill(future.date().isoformat())
            page.get_by_label("Промпт поста", exact=True).fill("Green field")
            page.get_by_role("dialog").get_by_role("button", name="Сохранить", exact=True).click()
            page.get_by_role("button", name="Сгенерировать сейчас", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_text("Упс, не нашли доступное изображение", exact=True)).to_be_visible()
            expect(dialog.get_by_role("button", name="Опубликовать без изображения", exact=True)).to_be_enabled()

            expect(dialog.get_by_role("button", name="Найти в сети", exact=True)).to_have_count(0)
            expect(dialog.get_by_label("Запрос для поиска изображений")).to_have_count(0)
            _assert_rendered(page, tmp_path / "missing-image.png")

            # Real text-only backend; polling reveals the draft without a reload.
            with page.expect_response("**/regenerate") as regenerated:
                dialog.get_by_role("button", name="Опубликовать без изображения", exact=True).click()
            assert regenerated.value.request.post_data_json == {"without_image": True}
            assert regenerated.value.status == 202
            expect(dialog.get_by_role("button", name="Править текст", exact=True)).to_be_visible()
            expect(dialog.get_by_text("Собираем пост", exact=True)).to_have_count(0)
            expect(dialog.get_by_text("Упс, не нашли доступное изображение", exact=True)).to_have_count(0)
            expect(dialog.get_by_role("button", name="Одобрить", exact=True)).to_be_visible()
            assert not errors
            _assert_rendered(page, tmp_path / "text-only-draft.png")
        finally:
            browser.close()
