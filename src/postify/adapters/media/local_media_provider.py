from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx

from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy, UnsafePublicUrlError
from postify.domain.content.models import StoredMedia


class MediaAcquireError(RuntimeError):
    def __init__(self, message: str = "media_failed") -> None:
        super().__init__(message)
        self.code = "media_failed"


class LocalMediaProvider:
    _EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

    def __init__(
        self,
        client: httpx.Client,
        media_dir: Path,
        max_bytes: int,
        wikimedia,
        *,
        url_policy: PublicHttpUrlPolicy | None = None,
    ) -> None:
        self.client = client
        self.root = media_dir.resolve()
        self.max = max_bytes
        self.wiki = wikimedia
        self.url_policy = url_policy

    def acquire(self, article, query: str) -> StoredMedia:
        for source_type, url in article.image_candidates:
            media = self._download(source_type, url)
            if media:
                return media
        fallback = self.wiki.search(query)
        if fallback:
            media = self._download(*fallback)
            if media:
                return media
        raise MediaAcquireError()

    def _download(self, source_type: str, url: str) -> StoredMedia | None:
        temp: Path | None = None
        try:
            validated_url = self.url_policy.validate(url) if self.url_policy else url
            with self.client.stream("GET", validated_url, follow_redirects=False) as response:
                response.raise_for_status()
                mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
                extension = self._EXTENSIONS.get(mime)
                length = response.headers.get("content-length")
                if not extension or (length is not None and (not length.isdigit() or int(length) > self.max)):
                    return None
                self.root.mkdir(parents=True, exist_ok=True)
                final = self.root / f"{uuid4().hex}.{extension}"
                temp = self.root / f".{final.name}.tmp"
                total = 0
                with temp.open("xb") as output:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.max:
                            raise ValueError
                        output.write(chunk)
                if total == 0:
                    return None
                temp.replace(final)
                return StoredMedia(str(final), mime, source_type, validated_url)
        except (UnsafePublicUrlError, httpx.HTTPError, OSError, ValueError):
            return None
        finally:
            if temp is not None and temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

    def delete(self, local_path: str) -> None:
        path = Path(local_path)
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError
            path.unlink(missing_ok=True)
        except (OSError, ValueError) as error:
            raise MediaAcquireError() from error

    def cleanup(self, *, older_than: datetime, protected_paths: set[str]) -> int:
        if not self.root.exists():
            return 0
        removed = 0
        for path in self.root.iterdir():
            if path.is_symlink():
                continue
            if (
                path.is_file()
                and str(path) not in protected_paths
                and datetime.fromtimestamp(path.stat().st_mtime, older_than.tzinfo) < older_than
            ):
                path.unlink()
                removed += 1
        return removed
