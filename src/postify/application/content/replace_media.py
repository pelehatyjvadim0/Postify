from collections.abc import Callable
from datetime import datetime

from postify.application.ports.article_extractor import ArticleExtractor
from postify.application.ports.content_repository import ContentRepository
from postify.application.ports.media_provider import MediaProvider


class ReplacePackageMedia:
    """Reuses extraction and media services without restarting content analysis."""

    def __init__(self, repository: ContentRepository, extractor: ArticleExtractor, media: MediaProvider, *, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._extractor = extractor
        self._media = media
        self._clock = clock

    def execute(self, package_id: int) -> None:
        package = self._repository.get_package(package_id)
        article = self._extractor.extract(package.source_url)
        media = self._media.acquire(
            article,
            article.title,
            excluded_urls={package.media_source_url} if package.media_source_url else set(),
            excluded_paths={package.media_path} if package.media_path else set(),
        )
        self._repository.replace_media(package_id, media=media, now=self._clock())
