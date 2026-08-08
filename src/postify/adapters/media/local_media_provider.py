from __future__ import annotations
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import httpx
from postify.domain.content.models import StoredMedia


class MediaAcquireError(RuntimeError):
    def __init__(self, message="media_failed"):
        super().__init__(message)
        self.code = "media_failed"


class LocalMediaProvider:
    def __init__(
        self, client: httpx.Client, media_dir: Path, max_bytes: int, wikimedia
    ):
        self.client = client
        self.root = media_dir.resolve()
        self.max = max_bytes
        self.wiki = wikimedia

    def acquire(self, article, query):
        candidates = list(article.image_candidates)
        for typ, url in candidates:
            try:
                r = self.client.get(url)
                r.raise_for_status()
                mime = r.headers.get("content-type", "").split(";", 1)[0]
                ext = {
                    "image/jpeg": "jpg",
                    "image/png": "png",
                    "image/webp": "webp",
                }.get(mime)
                if not ext or not r.content or len(r.content) > self.max:
                    continue
                self.root.mkdir(parents=True, exist_ok=True)
                final = self.root / f"{uuid4().hex}.{ext}"
                temp = final.with_suffix(".tmp")
                temp.write_bytes(r.content)
                temp.replace(final)
                return StoredMedia(str(final), mime, typ, url)
            except (httpx.HTTPError, OSError):
                continue
        found = self.wiki.search(query)
        if found:
            typ, url = found
            try:
                r = self.client.get(url)
                r.raise_for_status()
                mime = r.headers.get("content-type", "").split(";", 1)[0]
                ext = {
                    "image/jpeg": "jpg",
                    "image/png": "png",
                    "image/webp": "webp",
                }.get(mime)
                if ext and r.content and len(r.content) <= self.max:
                    self.root.mkdir(parents=True, exist_ok=True)
                    final = self.root / f"{uuid4().hex}.{ext}"
                    temp = final.with_suffix(".tmp")
                    temp.write_bytes(r.content)
                    temp.replace(final)
                    return StoredMedia(str(final), mime, typ, url)
            except (httpx.HTTPError, OSError):
                pass
        raise MediaAcquireError()

    def delete(self, local_path):
        Path(local_path).unlink(missing_ok=True)

    def cleanup(self, *, older_than: datetime, protected_paths: set[str]):
        if not self.root.exists():
            return 0
        n = 0
        for p in self.root.iterdir():
            if (
                p.is_file()
                and str(p) not in protected_paths
                and datetime.fromtimestamp(p.stat().st_mtime, older_than.tzinfo)
                < older_than
            ):
                p.unlink()
                n += 1
        return n
