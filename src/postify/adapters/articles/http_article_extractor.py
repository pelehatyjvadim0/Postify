from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urljoin
import httpx
from postify.domain.content.models import ExtractedArticle


class ArticleExtractionError(RuntimeError):
    def __init__(self, message="article_unavailable"):
        super().__init__(message)
        self.code = "article_unavailable"


class _Parser(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base = base
        self.stack = []
        self.parts = []
        self.images = []
        self.title = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.stack.append(tag)
        if (
            tag == "meta"
            and d.get("content")
            and (d.get("property") == "og:image" or d.get("name") == "twitter:image")
        ):
            self.images.append(
                (
                    "og" if d.get("property") == "og:image" else "twitter",
                    urljoin(self.base, d["content"]),
                )
            )
        elif tag == "img" and d.get("src") and not d["src"].startswith("data:"):
            self.images.append(("article", urljoin(self.base, d["src"])))

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if any(x in self.stack for x in ("script", "style", "nav", "form")):
            return
        if any(x in self.stack for x in ("article", "main", "p")):
            self.parts.append(data.strip())


class HttpArticleExtractor:
    def __init__(
        self, *, client: httpx.Client, max_bytes: int, min_text_chars: int = 200
    ):
        self.client = client
        self.max_bytes = max_bytes
        self.min = min_text_chars

    def extract(self, url):
        try:
            r = self.client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ArticleExtractionError() from e
        if (
            "text/html" not in r.headers.get("content-type", "")
            or len(r.content) > self.max_bytes
        ):
            raise ArticleExtractionError()
        p = _Parser(url)
        p.feed(r.text)
        text = " ".join(x for x in p.parts if x)
        if len(text) < self.min:
            raise ArticleExtractionError()
        return ExtractedArticle(url, p.title, text, tuple(p.images))
