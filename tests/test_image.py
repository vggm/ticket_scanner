from io import BytesIO

import pytest
from PIL import Image
from pillow_heif import register_heif_opener

from ticket_scanner.image import InvalidImage, preprocess

register_heif_opener()


def make(fmt: str, size: tuple[int, int], exif_orientation: int | None = None) -> bytes:
    img = Image.new("RGB", size, "white")
    buf = BytesIO()
    kwargs = {}
    if exif_orientation is not None:
        exif = img.getexif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def test_resizes_long_side_and_returns_jpeg():
    out = Image.open(BytesIO(preprocess(make("PNG", (3000, 4000)), 2048)))
    assert out.format == "JPEG" and max(out.size) == 2048 and out.size == (1536, 2048)


def test_never_upscales():
    assert Image.open(BytesIO(preprocess(make("JPEG", (800, 600)), 2048))).size == (800, 600)


def test_exif_orientation_applied_and_stripped():
    out = Image.open(BytesIO(preprocess(make("JPEG", (400, 200), exif_orientation=6), 2048)))
    assert out.size == (200, 400) and not out.getexif()


def test_accepts_webp_and_heic():
    for fmt in ("WEBP", "HEIF"):
        assert Image.open(BytesIO(preprocess(make(fmt, (100, 100)), 2048))).format == "JPEG"


def test_rejects_non_image():
    with pytest.raises(InvalidImage):
        preprocess(b"no soy una imagen", 2048)


def test_rejects_empty():
    with pytest.raises(InvalidImage):
        preprocess(b"", 2048)


def test_rejects_unsupported_format():
    with pytest.raises(InvalidImage):
        preprocess(make("GIF", (10, 10)), 2048)


def test_accepts_mpo():
    img = Image.new("RGB", (100, 100), "white")
    buf = BytesIO()
    img.save(buf, format="MPO", save_all=True, append_images=[Image.new("RGB", (50, 50))])
    assert Image.open(BytesIO(preprocess(buf.getvalue(), 2048))).format == "JPEG"
