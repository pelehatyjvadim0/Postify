import asyncio

import httpx

from tests.unit.web.test_api import ApiStub


def test_password_protects_ui_and_api_and_sets_remembered_cookie() -> None:
    from postify.web.app import create_app
    from postify.web.dependencies import WebContainer

    app = create_app(WebContainer(api=ApiStub()), access_password="small-secret")

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return (
                await client.get("/"),
                await client.get("/api/v1/bootstrap"),
                await client.post("/login", data={"password": "wrong"}),
                await client.post("/login", data={"password": "small-secret"}),
                await client.get("/"),
            )

    redirected, api_denied, rejected, accepted, remembered = asyncio.run(exercise())

    assert redirected.status_code == 303
    assert redirected.headers["location"] == "/login"
    assert api_denied.status_code == 401
    assert api_denied.json()["code"] == "authentication_required"
    assert rejected.status_code == 401
    assert "Неверный пароль" in rejected.text
    assert accepted.status_code == 303
    assert "postify_access=" in accepted.headers["set-cookie"]
    assert "Max-Age=31536000" in accepted.headers["set-cookie"]
    assert "HttpOnly" in accepted.headers["set-cookie"]
    assert remembered.status_code == 200
