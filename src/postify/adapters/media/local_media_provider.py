from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import stat

from postify.application.ports.media_provider import MediaCleanupError


class LocalMediaProvider:
    def __init__(self, media_dir: Path) -> None:
        self.root = media_dir.resolve()

    def delete(self, local_path: str) -> None:
        path = Path(os.path.abspath(local_path))
        descriptors: list[int] = []
        try:
            if not path.is_relative_to(self.root):
                raise ValueError
            components = path.relative_to(self.root).parts
            if not components:
                raise ValueError
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            for component in components[:-1]:
                descriptor = os.open(component, flags, dir_fd=descriptor)
                descriptors.append(descriptor)
            target = os.stat(components[-1], dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(target.st_mode):
                raise ValueError
            os.unlink(components[-1], dir_fd=descriptor)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            raise MediaCleanupError("media_cleanup_failed") from None
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
                    and datetime.fromtimestamp(path.stat().st_mtime, older_than.tzinfo) < older_than
                ):
                    path.unlink()
                    removed += 1
            return removed
        except OSError:
            raise MediaCleanupError("media_cleanup_failed") from None
