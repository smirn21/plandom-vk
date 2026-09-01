"""Нормализация изображений для VK upload."""
from __future__ import annotations

import io

from PIL import Image

MAX_VK_SIDE = 1280


def normalize_image_bytes(image_bytes: bytes, *, quality: int = 82) -> bytes:
    """Приводит Grok/PNG к baseline JPEG, совместимому с VK upload."""
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    img = img.convert("RGB")
    if max(img.width, img.height) > MAX_VK_SIDE:
        scale = MAX_VK_SIDE / max(img.width, img.height)
        img = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=quality,
        optimize=False,
        progressive=False,
        subsampling=2,
    )
    return buf.getvalue()
