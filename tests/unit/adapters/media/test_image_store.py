from io import BytesIO
import struct
import zlib

from PIL import Image
import pytest

from postify.adapters.media.image_store import ImageStore, UnsupportedImage
from postify.adapters.media import image_store


def png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_oversized_dimensions_are_rejected_before_decode_or_disk_write(tmp_path, monkeypatch):
    payload = png()
    # Replace IHDR dimensions without allocating a large decoded image.
    header = struct.pack(">II", 5000, 4001) + payload[24:29]
    crc = struct.pack(">I", zlib.crc32(b"IHDR" + header))
    payload = payload[:16] + header + crc + payload[33:]

    def no_decode(*args, **kwargs):
        pytest.fail("oversized image was decoded")

    monkeypatch.setattr(Image.Image, "load", no_decode)

    with pytest.raises(UnsupportedImage, match="20000000"):
        ImageStore(tmp_path).save(payload, project_id=1)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("pillow_limit", [40, 20])
def test_pillow_bomb_warning_and_error_are_controlled_rejections(tmp_path, monkeypatch, pillow_limit):
    payload = png()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", pillow_limit)

    with pytest.raises(UnsupportedImage, match="слишком большого разрешения"):
        ImageStore(tmp_path).save(payload, project_id=1)

    assert list(tmp_path.iterdir()) == []


def test_image_at_pixel_limit_still_saves_original_and_thumbnail(tmp_path, monkeypatch):
    payload = png()
    store = ImageStore(tmp_path)
    monkeypatch.setattr(image_store, "MAX_IMAGE_PIXELS", 64)

    saved = store.save(payload, project_id=1)

    assert saved.width == saved.height == 8
    assert store.read(saved.file_path) == payload
    assert saved.thumb_path is not None
    with Image.open(BytesIO(store.read(saved.thumb_path))) as thumbnail:
        assert thumbnail.format == "JPEG"
