"""Preprocesado de imagen: valida, orienta, reduce y normaliza a JPEG."""

from io import BytesIO

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

FORMATOS_VALIDOS = {"JPEG", "PNG", "WEBP", "HEIF"}


class InvalidImage(Exception):
    """Los bytes recibidos no son una imagen soportada."""


def preprocess(data: bytes, max_side: int) -> bytes:
    """Devuelve la imagen como JPEG sin EXIF, con el lado mayor <= max_side."""
    try:
        img = Image.open(BytesIO(data))
        formato = img.format
        img.load()
    except Exception as exc:
        raise InvalidImage("no es una imagen válida") from exc
    if formato not in FORMATOS_VALIDOS:
        raise InvalidImage(f"formato no soportado: {formato}")
    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_side, max_side))
    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()
