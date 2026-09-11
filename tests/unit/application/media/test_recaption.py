"""Перевыпуск подписей: точка перехода с заглушки на настоящего провайдера."""

from __future__ import annotations

from postify.adapters.media.image_store import ImageStore
from postify.application.media.captioning import CaptionMedia, RecaptionAssets
from postify.application.media.upload import UploadMedia

from .fakes import NOW, FakeGateway, FakeMediaRepository, png


PROJECT_ID = 3


def _seed(tmp_path, gateway: FakeGateway, repository: FakeMediaRepository, count: int):
    UploadMedia(
        repository,
        ImageStore(tmp_path),
        CaptionMedia(repository, gateway, project_id=PROJECT_ID, clock=lambda: NOW),
        project_id=PROJECT_ID,
        clock=lambda: NOW,
    ).execute([png(color=(index * 20, 10, 10)) for index in range(count)])


def _recaption(repository: FakeMediaRepository, gateway: FakeGateway) -> RecaptionAssets:
    return RecaptionAssets(
        repository,
        CaptionMedia(repository, gateway, project_id=PROJECT_ID, clock=lambda: NOW),
        project_id=PROJECT_ID,
    )


def test_everything_captioned_by_the_mock_is_found_and_reissued(tmp_path) -> None:
    repository = FakeMediaRepository()
    _seed(tmp_path, FakeGateway(model="mock"), repository, 2)
    # Одну подпись поправил человек: перевыпуск не должен её затирать.
    repository.assets[1]["caption_model"] = "manual"

    real = FakeGateway(caption="Силосы с высоты", model="google/gemini-3.1-flash-lite")
    recaption = _recaption(repository, real)
    stale = recaption.captioned_by("mock")
    report = recaption.execute(stale)

    assert stale == (2,)
    assert report.captioned == 1 and report.failed == 0
    assert repository.assets[2]["caption_model"] == "google/gemini-3.1-flash-lite"
    assert repository.assets[2]["caption"] == "Силосы с высоты"
    assert repository.assets[1]["caption_model"] == "manual"


def test_failed_reissue_is_counted_and_leaves_the_asset_marked(tmp_path) -> None:
    repository = FakeMediaRepository()
    _seed(tmp_path, FakeGateway(model="mock"), repository, 1)

    report = _recaption(
        repository, FakeGateway(fails=frozenset({"caption"}))
    ).execute((1,))

    assert report.requested == 1
    assert report.captioned == 0
    assert report.failed == 1
    assert repository.assets[1]["caption_status"] == "failed"
