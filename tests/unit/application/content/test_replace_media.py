from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace


NOW = datetime(2026, 8, 17, 16, tzinfo=UTC)


def _api():
    from postify.application.content.replace_media import ReplacePackageMedia
    from postify.domain.content.models import ExtractedArticle, StoredMedia

    return ReplacePackageMedia, ExtractedArticle, StoredMedia


def test_replace_media_excludes_the_current_url_and_file() -> None:
    # Поломка Wave 10: action заново выбирает текущее OG-медиа как успешную замену.
    ReplacePackageMedia, ExtractedArticle, StoredMedia = _api()

    class Repository:
        def get_package(self, package_id: int):
            assert package_id == 17
            return SimpleNamespace(
                source_url="https://article.test/post",
                media_source_url="https://cdn.test/current.png",
                media_path="/media/current.png",
            )

        def replace_media(self, package_id: int, *, media, now: datetime) -> None:
            assert package_id == 17
            assert media.local_path == "/media/replacement.png"
            assert now == NOW

    class Extractor:
        def extract(self, source_url: str):
            assert source_url == "https://article.test/post"
            return ExtractedArticle(
                source_url=source_url,
                title="Article",
                text="Полный текст статьи для замены изображения.",
                image_candidates=(("og", "https://cdn.test/current.png"),),
            )

    class Media:
        excluded_urls: set[str] | None = None
        excluded_paths: set[str] | None = None

        def acquire(self, article, query: str, *, excluded_urls=None, excluded_paths=None):
            self.excluded_urls = excluded_urls
            self.excluded_paths = excluded_paths
            return StoredMedia(
                "/media/replacement.png",
                "image/png",
                "wikimedia",
                "https://wiki.test/replacement.png",
            )

    media = Media()
    ReplacePackageMedia(Repository(), Extractor(), media, clock=lambda: NOW).execute(17)

    assert media.excluded_urls == {"https://cdn.test/current.png"}
    assert media.excluded_paths == {"/media/current.png"}
