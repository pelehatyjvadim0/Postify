from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path

import pytest


NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _provider(media_dir: Path):
    from postify.adapters.media.local_media_provider import LocalMediaProvider

    return LocalMediaProvider(media_dir)


def _cleanup_error():
    from postify.application.ports.media_provider import MediaCleanupError

    return MediaCleanupError


def test_cleanup_removes_only_expired_unprotected_files(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    expired = media_dir / "expired.jpg"
    protected = media_dir / "protected.jpg"
    young = media_dir / "young.jpg"
    for path in (expired, protected, young):
        path.write_bytes(b"x")
    old_timestamp = (NOW - timedelta(hours=49)).timestamp()
    os.utime(expired, (old_timestamp, old_timestamp))
    os.utime(protected, (old_timestamp, old_timestamp))

    removed = _provider(media_dir).cleanup(
        older_than=NOW - timedelta(hours=48), protected_paths={str(protected)}
    )

    assert removed == 1
    assert not expired.exists()
    assert protected.exists()
    assert young.exists()


def test_delete_rejects_path_outside_media_root(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    with pytest.raises(_cleanup_error()):
        _provider(media_dir).delete(str(outside))

    assert outside.read_text(encoding="utf-8") == "keep"


def test_delete_rejects_symlink_even_when_link_is_inside_media_root(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    link = media_dir / "linked.jpg"
    link.symlink_to(outside)

    with pytest.raises(_cleanup_error()):
        _provider(media_dir).delete(str(link))

    assert link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "keep"


def test_delete_rejects_intermediate_symlink(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    real_directory = media_dir / "real"
    real_directory.mkdir(parents=True)
    stored = real_directory / "stored.jpg"
    stored.write_bytes(b"keep")
    linked_directory = media_dir / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(_cleanup_error()):
        _provider(media_dir).delete(str(linked_directory / stored.name))

    assert stored.read_bytes() == b"keep"


def test_delete_keeps_open_parent_binding_when_directory_is_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_dir = tmp_path / "media"
    checked = media_dir / "checked"
    checked.mkdir(parents=True)
    stored = checked / "stored.jpg"
    stored.write_bytes(b"delete-this-file")
    renamed = media_dir / "checked-before-race"
    other = tmp_path / "other"
    other.mkdir()
    other_file = other / stored.name
    other_file.write_bytes(b"must-stay-unchanged")
    original_unlink = os.unlink

    def racing_unlink(path, *, dir_fd=None) -> None:
        if Path(os.fsdecode(path)).name == stored.name:
            checked.rename(renamed)
            checked.symlink_to(other, target_is_directory=True)
        original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", racing_unlink)
    _provider(media_dir).delete(str(stored))

    assert other_file.read_bytes() == b"must-stay-unchanged"
    assert not (renamed / stored.name).exists()


def test_cleanup_hides_filesystem_path_in_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_dir = tmp_path / "operator-secret"
    media_dir.mkdir()
    expired = media_dir / "expired.jpg"
    expired.write_bytes(b"recoverable")
    old_timestamp = (NOW - timedelta(hours=49)).timestamp()
    os.utime(expired, (old_timestamp, old_timestamp))

    def failing_unlink(path: Path, *args: object, **kwargs: object) -> None:
        raise OSError(f"filesystem failure at {path}")

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(_cleanup_error()) as caught:
        _provider(media_dir).cleanup(older_than=NOW - timedelta(hours=48), protected_paths=set())

    assert str(expired) not in str(caught.value)
