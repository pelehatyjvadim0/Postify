"""Маршруты пула изображений — раздел 10 контракта API.

Фасад подменён заглушкой: здесь проверяется ровно то, за что отвечает
веб-слой — разбор запроса, вызов нужного действия, форма ответа и коды.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import Mock

from fastapi import UploadFile
from PIL import Image
import pytest

from postify.web.dependencies import WebContainer
from postify.web.errors import ApiError
from postify.web.routes.media import _payloads
from tests.unit.web.test_api import ApiClient, AuthStub


NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)
PROJECT = 1
MAX_BYTES = 10_000


def png(size=(8, 8)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (10, 120, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def _asset(asset_id: int = 42, caption_model: str | None = "mock") -> dict[str, object]:
    base = f"/api/projects/{PROJECT}/media/{asset_id}/file"
    return {
        "id": asset_id,
        "url": base,
        "thumb_url": f"{base}?size=thumb",
        "mime": "image/jpeg",
        "caption": "Зернохранилище, металлические силосы, закат",
        "caption_status": "ready",
        "caption_model": caption_model,
        "width": 1600,
        "height": 900,
        "bytes": 482113,
        "enabled": True,
        "use_count": 0,
        "uploaded_at": NOW,
        "last_used_at": None,
        "available": True,
    }


class MediaStub:
    """Фасад без базы и диска."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.error: BaseException | None = None

    def scheduler_tick(self):
        return ()

    def close(self) -> None:
        pass

    def _record(self, name: str, *values: object) -> None:
        self.calls.append((name, values))
        if self.error is not None:
            raise self.error

    def media_upload_limit(self) -> int:
        return MAX_BYTES

    def media_assets(self, project_id, *, available=None, query=None, limit=60, cursor=None):
        self._record("media_assets", project_id, available, query, limit, cursor)
        return {"items": [_asset()], "next_cursor": "42"}

    def upload_media(self, project_id, payloads):
        self._record("upload_media", project_id, tuple(len(item) for item in payloads))
        return {"operation_id": 1841, "status": "running"}

    def media_file(self, project_id, asset_id, *, size="full"):
        self._record("media_file", project_id, asset_id, size)
        return b"bytes", "image/jpeg"

    def update_media(self, project_id, asset_id, *, caption=None, enabled=None):
        self._record("update_media", project_id, asset_id, caption, enabled)
        return _asset(asset_id)

    def delete_media(self, project_id, asset_id) -> None:
        self._record("delete_media", project_id, asset_id)

    def recaption_media(self, project_id, asset_id):
        self._record("recaption_media", project_id, asset_id)
        return {"operation_id": 1842, "status": "running"}

    def post_media(self, project_id, post_id):
        self._record("post_media", project_id, post_id)
        return b"post-bytes", "image/png"


def client_for(stub: MediaStub) -> ApiClient:
    from postify.web.app import create_app

    return ApiClient(create_app(WebContainer(api=stub), auth=AuthStub()))


def test_pool_is_listed_with_filters_and_a_cursor() -> None:
    stub = MediaStub()

    response = client_for(stub).get(
        f"/api/projects/{PROJECT}/media?available=true&q=силос&limit=30&cursor=90"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] == "42"
    assert body["items"][0]["id"] == 42
    # Подпись заглушки доезжает до UI: он обязан показать это честно.
    assert body["items"][0]["caption_model"] == "mock"
    assert stub.calls == [("media_assets", (PROJECT, True, "силос", 30, "90"))]


def test_upload_answers_202_with_an_operation_to_poll() -> None:
    stub = MediaStub()
    payload = png()

    response = client_for(stub).post(
        f"/api/projects/{PROJECT}/media",
        files=[
            ("files", ("first.png", payload, "image/png")),
            ("files", ("second.png", payload, "image/png")),
        ],
    )

    assert response.status_code == 202
    assert response.json() == {"operation_id": 1841, "status": "running"}
    assert stub.calls == [("upload_media", (PROJECT, (len(payload), len(payload))))]


def test_file_too_large_is_refused_with_413() -> None:
    stub = MediaStub()

    response = client_for(stub).post(
        f"/api/projects/{PROJECT}/media",
        files=[("files", ("big.png", b"x" * (MAX_BYTES + 1), "image/png"))],
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "media_too_large"
    # Слишком большой файл не доехал до фасада и не попал в память целиком.
    assert stub.calls == []


def test_too_many_files_are_rejected_before_reading_any_payload() -> None:
    files = [UploadFile(file=Mock(), size=1) for _ in range(21)]

    with pytest.raises(ApiError) as caught:
        _payloads(WebContainer(api=MediaStub()), files)

    assert caught.value.status_code == 400
    assert caught.value.code == "media_too_many_files"
    for item in files:
        item.file.read.assert_not_called()


def test_upload_route_rejects_more_than_twenty_files() -> None:
    stub = MediaStub()

    response = client_for(stub).post(
        f"/api/projects/{PROJECT}/media",
        files=[("files", (f"{index}.png", b"x", "image/png")) for index in range(21)],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "media_too_many_files"
    assert stub.calls == []


def test_missing_size_metadata_still_uses_a_bounded_read() -> None:
    stream = BytesIO(b"x" * (MAX_BYTES + 10))

    with pytest.raises(ApiError) as caught:
        _payloads(WebContainer(api=MediaStub()), [UploadFile(file=stream)])

    assert caught.value.status_code == 413
    assert stream.tell() == MAX_BYTES + 1


def test_busy_upload_is_a_conflict_not_a_crash() -> None:
    stub = MediaStub()
    stub.error = RuntimeError("operation_busy")

    response = client_for(stub).post(
        f"/api/projects/{PROJECT}/media",
        files=[("files", ("first.png", png(), "image/png"))],
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "operation_busy"


@pytest.mark.parametrize("size,expected", (("thumb", "thumb"), ("full", "full")))
def test_file_is_served_in_the_requested_size(size: str, expected: str) -> None:
    stub = MediaStub()

    response = client_for(stub).get(
        f"/api/projects/{PROJECT}/media/42/file?size={size}"
    )

    assert response.status_code == 200
    assert response.content == b"bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert stub.calls == [("media_file", (PROJECT, 42, expected))]


def test_unknown_size_does_not_reach_the_facade() -> None:
    stub = MediaStub()

    response = client_for(stub).get(
        f"/api/projects/{PROJECT}/media/42/file?size=original"
    )

    assert response.status_code == 422
    assert stub.calls == []


def test_caption_and_enabled_are_patched() -> None:
    stub = MediaStub()

    response = client_for(stub).patch(
        f"/api/projects/{PROJECT}/media/42", json={"caption": "Силосы", "enabled": False}
    )

    assert response.status_code == 200
    assert response.json()["id"] == 42
    assert stub.calls == [("update_media", (PROJECT, 42, "Силосы", False))]


def test_empty_patch_is_rejected() -> None:
    stub = MediaStub()

    response = client_for(stub).patch(f"/api/projects/{PROJECT}/media/42", json={})

    assert response.status_code == 422
    assert stub.calls == []


def test_asset_is_deleted() -> None:
    stub = MediaStub()

    response = client_for(stub).delete(f"/api/projects/{PROJECT}/media/42")

    assert response.status_code == 204
    assert stub.calls == [("delete_media", (PROJECT, 42))]


def test_recaption_answers_202() -> None:
    stub = MediaStub()

    response = client_for(stub).post(f"/api/projects/{PROJECT}/media/42/recaption")

    assert response.status_code == 202
    assert response.json() == {"operation_id": 1842, "status": "running"}
    assert stub.calls == [("recaption_media", (PROJECT, 42))]


def test_missing_asset_is_404() -> None:
    stub = MediaStub()
    stub.error = LookupError(42)

    response = client_for(stub).get(f"/api/projects/{PROJECT}/media/42/file")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_foreign_project_media_is_404_and_does_not_reach_the_facade() -> None:
    # Изоляция данных: чужой проект не раскрывается даже отсутствием объекта.
    stub = MediaStub()
    client = ApiClient(_app_with_owned(stub, owned=(PROJECT,)))

    response = client.get("/api/projects/2/media")

    assert response.status_code == 404
    assert stub.calls == []


def test_post_media_route_survived_the_pool() -> None:
    # Пока пост хранит медиа у себя, карточке ревью нужен именно этот маршрут.
    stub = MediaStub()

    response = client_for(stub).get(f"/api/projects/{PROJECT}/posts/77/media")

    assert response.status_code == 200
    assert response.content == b"post-bytes"


def test_api_error_from_the_facade_keeps_its_code() -> None:
    stub = MediaStub()
    stub.error = ApiError(400, "media_too_many_files", "Слишком много файлов")

    response = client_for(stub).post(
        f"/api/projects/{PROJECT}/media",
        files=[("files", ("first.png", png(), "image/png"))],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "media_too_many_files"


def _app_with_owned(stub: MediaStub, *, owned: tuple[int, ...]):
    from postify.web.app import create_app

    return create_app(WebContainer(api=stub), auth=AuthStub(owned=owned))
