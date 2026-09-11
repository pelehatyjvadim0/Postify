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


def test_browser_editor_workflow(browser_application, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    base_url, auth, calls = browser_application
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, base_url=base_url)
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base_url)
        with page.expect_response("**/api/auth/login") as login_response:
            page.get_by_role("button", name="Войти через Telegram").click()
        login = login_response.value.json()
        token = login["telegram_url"].split("start=login_", 1)[1]
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
        page.get_by_role("button", name="Сгенерировать сейчас", exact=True).click()
        page.get_by_role("button", name="Править текст", exact=True).wait_for()
        assert calls
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
