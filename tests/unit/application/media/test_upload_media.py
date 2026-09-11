"""Загрузка изображений в пул: подпись, отказ провайдера, дедупликация."""

from __future__ import annotations

from postify.adapters.media.image_store import ImageStore
from postify.application.media.captioning import CaptionMedia
from postify.application.media.upload import UploadMedia

from .fakes import CAPTION, NOW, FakeGateway, FakeMediaRepository, png


PROJECT_ID = 3


def _upload(tmp_path, gateway: FakeGateway, repository: FakeMediaRepository):
    return UploadMedia(
        repository,
        ImageStore(tmp_path),
        CaptionMedia(
            repository, gateway, project_id=PROJECT_ID, clock=lambda: NOW
        ),
        project_id=PROJECT_ID,
        clock=lambda: NOW,
    )


def test_upload_stores_the_file_and_captions_it_through_the_gateway(tmp_path) -> None:
    repository = FakeMediaRepository()
    gateway = FakeGateway()

    report = _upload(tmp_path, gateway, repository).execute([png()])

    assert report.created == 1
    assert report.captioned == 1
    assert report.errors == ()
    asset = repository.assets[report.asset_ids[0]]
    assert asset["caption"] == CAPTION
    # Имя модели обязано доехать до базы: по нему ищут, что перевыпустить.
    assert asset["caption_model"] == "mock"
    assert asset["caption_status"] == "ready"
    assert asset["width"] == 64 and asset["height"] == 48
    assert asset["mime"] == "image/png"
    # Файл и превью действительно легли на диск.
    assert (tmp_path / "pool" / str(PROJECT_ID)).is_dir()
    assert len(list((tmp_path / "pool" / str(PROJECT_ID)).iterdir())) == 2


def test_unavailable_provider_keeps_the_image_without_caption(tmp_path) -> None:
    # Трейс, раздел 5: потерять загруженный файл из-за молчащего провайдера
    # нельзя, но и притворяться, что подпись есть, тоже.
    repository = FakeMediaRepository()
    gateway = FakeGateway(fails=frozenset({"caption"}))

    report = _upload(tmp_path, gateway, repository).execute([png()])

    asset = repository.assets[report.asset_ids[0]]
    assert report.created == 1
    assert report.captioned == 0
    assert asset["caption"] is None
    assert asset["caption_status"] == "failed"
    assert report.errors[0]["code"] == "provider_not_configured"


def test_caption_without_embedding_is_kept_but_not_offered(tmp_path) -> None:
    repository = FakeMediaRepository()
    gateway = FakeGateway(fails=frozenset({"embed"}))

    report = _upload(tmp_path, gateway, repository).execute([png()])

    asset = repository.assets[report.asset_ids[0]]
    assert asset["caption"] == CAPTION
    assert asset["embedding"] is None
    assert asset["caption_status"] == "failed"
    assert report.captioned == 0


def test_same_file_uploaded_twice_does_not_duplicate_the_asset(tmp_path) -> None:
    repository = FakeMediaRepository()
    gateway = FakeGateway()
    upload = _upload(tmp_path, gateway, repository)
    payload = png()

    first = upload.execute([payload])
    second = upload.execute([payload, png(color=(200, 10, 10))])

    assert first.asset_ids[0] == second.asset_ids[0]
    assert second.duplicates == 1
    assert second.created == 1
    assert len(repository.assets) == 2
    # Повторная загрузка не зовёт модель второй раз за ту же картинку.
    assert gateway.calls.count(("caption", "caption")) == 2


def test_not_an_image_is_reported_and_does_not_stop_the_batch(tmp_path) -> None:
    repository = FakeMediaRepository()

    report = _upload(tmp_path, FakeGateway(), repository).execute(
        [b"<html>not a picture</html>", png()]
    )

    assert report.created == 1
    assert report.failed == 1
    assert len(repository.assets) == 1
