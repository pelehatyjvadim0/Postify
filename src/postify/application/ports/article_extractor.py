from __future__ import annotations

from typing import Protocol

from postify.domain.content.models import ExtractedArticle


class ArticleExtractor(Protocol):
    def extract(self, url: str) -> ExtractedArticle: ...
