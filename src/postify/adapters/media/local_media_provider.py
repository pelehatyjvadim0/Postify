from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import stat
from uuid import uuid4

import httpx

from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy, UnsafePublicUrlError
from postify.domain.content.models import StoredMedia
from postify.application.ports.media_provider import MediaCleanupError


class MediaAcquireError(MediaCleanupError):
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
        url_policy: PublicHttpUrlPolicy,
    ) -> None:
        if url_policy is None:
            raise TypeError("url_policy is required")
        self.client = client
        self.root = media_dir.resolve()
        self.max = max_bytes
        self.wiki = wikimedia
        self.url_policy = url_policy

    def acquire(self, article, query: str) -> StoredMedia:
        priority = {"og": 0, "twitter": 1, "article": 2}
        candidates = sorted(
            article.image_candidates,
            key=lambda candidate: priority.get(candidate[0], len(priority)),
        )
        for source_type, url in candidates:
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
            validated_url = self.url_policy.validate(url)
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
        path = Path(os.path.abspath(local_path))
        descriptors: list[int] = []
        try:
            if not path.is_relative_to(self.root):
                raise ValueError
            components = path.relative_to(self.root).parts
            if not components:
                raise ValueError
            descriptor = os.open(
                self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            descriptors.append(descriptor)
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            for component in components[:-1]:
                descriptor = os.open(component, directory_flags, dir_fd=descriptor)
                descriptors.append(descriptor)
            target = os.stat(components[-1], dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(target.st_mode):
                raise ValueError
            os.unlink(components[-1], dir_fd=descriptor)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            raise MediaAcquireError() from None
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def cleanup(self, *, older_than: datetime, protected_paths: set[str]) -> int:
        try:
            if not self.root.exists():
                return 0
            removed = 0
            for path in self.root.iterdir():
                if path.is_symlink():
                    continue
                if (
                    path.is_file()
                    and str(path) not in protected_paths
                    and datetime.fromtimestamp(path.stat().st_mtime, older_than.tzinfo)
                    < older_than
                ):
                    path.unlink()
                    removed += 1
            return removed
        except OSError:
            raise MediaAcquireError() from None
