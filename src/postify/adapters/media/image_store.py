"""Файлы пула изображений на локальном диске.

Подход к путям тот же, что у ``LocalMediaProvider``: путь обязан лежать внутри
каталога медиа, спуск идёт по дескрипторам каталогов с ``O_NOFOLLOW``, так что
подменённая симлинком директория или файл не выводят запись за корень.

Имя файла из запроса недоверенное и в путь на диске не превращается никогда:
имя строится из SHA-256 содержимого, расширение — из формата, который распознал
Pillow, а не из того, что прислал клиент.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
import stat

from PIL import Image


# Контракт, раздел 10: принимаются только эти три формата.
ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}

# Превью для сетки пула: считается один раз при загрузке и лежит рядом.
THUMB_BOX = (480, 480)


class UnsupportedImage(ValueError):
    """Файл не является изображением поддерживаемого формата."""


class ImageStoreError(RuntimeError):
    """Файл не удалось записать или прочитать."""


@dataclass(frozen=True, slots=True)
class StoredImage:
    """Что легло на диск и что об этом надо записать в базу."""

    content_hash: str
    file_path: str
    thumb_path: str | None
    mime: str
    bytes: int
    width: int
    height: int


class ImageStore:
    """Каталог изображений проекта внутри корня медиа."""

    def __init__(self, media_dir: Path) -> None:
        self.root = Path(media_dir).resolve()

    # --- запись ----------------------------------------------------------

    def save(self, data: bytes, *, project_id: int) -> StoredImage:
        """Кладёт изображение и его превью, возвращает метаданные для базы.

        Повторная загрузка того же содержимого попадает в тот же файл: имя
        детерминировано хешем, а существующий файл считается уже записанным.
        """
        image_format, width, height = _inspect(data)
        mime, extension = ALLOWED_FORMATS[image_format]
        content_hash = hashlib.sha256(data).hexdigest()
        directory = ("pool", str(project_id))
        name = f"{content_hash}.{extension}"
        self._write(directory, name, data)
        thumb = self._write_thumb(directory, content_hash, data)
        return StoredImage(
            content_hash=content_hash,
            file_path=str(self.root.joinpath(*directory, name)),
            thumb_path=thumb,
            mime=mime,
            bytes=len(data),
            width=width,
            height=height,
        )

    # --- чтение и удаление ------------------------------------------------

    def read(self, stored_path: str) -> bytes:
        """Содержимое файла пула. Путь вне корня и симлинк — ошибка."""
        components = self._components(stored_path)
        descriptors: list[int] = []
        try:
            descriptor = self._descend(components[:-1], descriptors, create=False)
            # O_NOFOLLOW сам отказывается открывать симлинк последним звеном.
            handle = os.open(
                components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            with os.fdopen(handle, "rb") as stream:
                return stream.read()
        except FileNotFoundError:
            raise LookupError(stored_path) from None
        except (OSError, ValueError):
            raise ImageStoreError("media_unreadable") from None
        finally:
            _close(descriptors)

    def delete(self, stored_path: str | None) -> None:
        """Удаляет файл пула. Отсутствующий файл — не ошибка."""
        if not stored_path:
            return
        descriptors: list[int] = []
        try:
            components = self._components(stored_path)
            descriptor = self._descend(components[:-1], descriptors, create=False)
            target = os.stat(components[-1], dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(target.st_mode):
                raise ValueError
            os.unlink(components[-1], dir_fd=descriptor)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            raise ImageStoreError("media_cleanup_failed") from None
        finally:
            _close(descriptors)

    # --- внутреннее -------------------------------------------------------

    def _components(self, stored_path: str) -> tuple[str, ...]:
        path = Path(os.path.abspath(stored_path))
        if not path.is_relative_to(self.root):
            raise ValueError("Путь вне каталога медиа")
        components = path.relative_to(self.root).parts
        if not components:
            raise ValueError("Пустой путь")
        return components

    def _descend(
        self, parts: tuple[str, ...], descriptors: list[int], *, create: bool
    ) -> int:
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            descriptor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            descriptors.append(descriptor)
        return descriptor

    def _write(self, directory: tuple[str, ...], name: str, payload: bytes) -> None:
        descriptors: list[int] = []
        try:
            descriptor = self._descend(directory, descriptors, create=True)
            try:
                handle = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=descriptor,
                )
            except FileExistsError:
                # То же содержимое уже лежит: имя детерминировано его хешем.
                return
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
        except (OSError, ValueError):
            raise ImageStoreError("media_write_failed") from None
        finally:
            _close(descriptors)

    def _write_thumb(
        self, directory: tuple[str, ...], content_hash: str, data: bytes
    ) -> str | None:
        """Превью в JPEG одним путём для всех форматов.

        Не получилось (битый кадр, слишком большая картинка) — не повод терять
        загрузку: тогда превью нет и ``size=thumb`` отдаёт оригинал.
        """
        try:
            with Image.open(BytesIO(data)) as image:
                preview = image.convert("RGB")
                preview.thumbnail(THUMB_BOX)
                buffer = BytesIO()
                preview.save(buffer, format="JPEG", quality=85)
        except Exception:
            return None
        name = f"{content_hash}_thumb.jpg"
        try:
            self._write(directory, name, buffer.getvalue())
        except ImageStoreError:
            return None
        return str(self.root.joinpath(*directory, name))


def _inspect(data: bytes) -> tuple[str, int, int]:
    """Формат и размеры из заголовка. Клиентскому content-type веры нет."""
    try:
        with Image.open(BytesIO(data)) as image:
            image_format = image.format
            width, height = image.size
    except Exception:
        raise UnsupportedImage("Файл не распознан как изображение") from None
    if image_format not in ALLOWED_FORMATS:
        raise UnsupportedImage("Поддерживаются JPEG, PNG и WebP")
    if width <= 0 or height <= 0:
        raise UnsupportedImage("Изображение без размеров")
    return image_format, width, height


def _close(descriptors: list[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass
