from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy, UnsafePublicUrlError
from postify.domain.content.models import ExtractedArticle


class ArticleExtractionError(RuntimeError):
    def __init__(self, message: str = "article_unavailable") -> None:
        super().__init__(message)
        self.code = "article_unavailable"


class _Parser(HTMLParser):
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
    _EXCLUDED_TAGS = {"script", "style", "nav", "form"}

    def __init__(self, base: str) -> None:
        super().__init__()
        self.base = base
        self.stack: list[str] = []
        self.article_parts: list[str] = []
        self.main_parts: list[str] = []
        self.paragraph_parts: list[str] = []
        self.images: dict[str, list[str]] = {"og": [], "twitter": [], "article": []}
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta" and values.get("content"):
            kind = "og" if values.get("property") == "og:image" else "twitter" if values.get("name") == "twitter:image" else None
            if kind:
                self.images[kind].append(urljoin(self.base, values["content"]))
        elif tag == "img" and values.get("src") and not values["src"].startswith("data:"):
            self.images["article"].append(urljoin(self.base, values["src"]))
        if tag not in self._VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value or any(tag in self._EXCLUDED_TAGS for tag in self.stack):
            return
        if "title" in self.stack:
            self.title = f"{self.title} {value}".strip()
        if "article" in self.stack:
            self.article_parts.append(value)
        elif "main" in self.stack:
            self.main_parts.append(value)
        elif "p" in self.stack:
            self.paragraph_parts.append(value)

    def text(self) -> str:
        for parts in (self.article_parts, self.main_parts, self.paragraph_parts):
            text = " ".join(parts)
            if text:
                return text
        return ""

    def image_candidates(self) -> tuple[tuple[str, str], ...]:
        return tuple((kind, url) for kind in ("og", "twitter", "article") for url in self.images[kind])


class HttpArticleExtractor:
    def __init__(
        self,
        *,
        client: httpx.Client,
        max_bytes: int,
        min_text_chars: int = 200,
        url_policy: PublicHttpUrlPolicy | None = None,
    ) -> None:
        self.client = client
        self.max_bytes = max_bytes
        self.min = min_text_chars
        self.url_policy = url_policy

    def extract(self, url: str) -> ExtractedArticle:
        try:
            validated_url = self.url_policy.validate(url) if self.url_policy else url
            with self.client.stream("GET", validated_url, follow_redirects=False) as response:
                response.raise_for_status()
                if "text/html" not in response.headers.get("content-type", "").lower():
                    raise ValueError
                length = response.headers.get("content-length")
                if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
                    raise ValueError
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ValueError
                    chunks.append(chunk)
        except (UnsafePublicUrlError, httpx.HTTPError, ValueError, UnicodeDecodeError) as error:
            raise ArticleExtractionError() from error

        parser = _Parser(validated_url)
        try:
            parser.feed(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ArticleExtractionError() from error
        text = parser.text()
        if len(text) < self.min:
            raise ArticleExtractionError()
        return ExtractedArticle(validated_url, parser.title, text, parser.image_candidates())
