"""Превью комнат (Pillow MVP)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            from PIL import ImageFont as IF

            return IF.truetype(path, size)
        except OSError:
            continue
    from PIL import ImageFont as IF

    return IF.load_default()


STYLE_COLORS = {
    "scandinavian": ("#f5f0e8", "#8fa88a", "#d4c4a8"),
    "modern": ("#ececec", "#555555", "#0099cc"),
    "loft": ("#3d3d3d", "#c4a574", "#888888"),
    "classic": ("#f0e6d2", "#6b4c3b", "#b8860b"),
    "minimal": ("#ffffff", "#222222", "#cccccc"),
}


def render_room_card(
    room_name: str,
    description: str,
    style: str = "scandinavian",
    out_path: Path | None = None,
    *,
    width: int = 800,
    height: int = 600,
) -> Path:
    bg, accent, secondary = STYLE_COLORS.get(style, STYLE_COLORS["scandinavian"])
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    title_font = _font(28)
    body_font = _font(16)

    draw.rectangle([30, 30, width - 30, height - 30], outline=accent, width=3)
    draw.rectangle([50, 50, width - 50, int(height * 0.45)], fill=secondary)
    draw.text((60, 60), room_name, fill=accent, font=title_font)

    # Простая «мебель»
    draw.rectangle([70, 120, 220, 200], fill=accent)
    draw.rectangle([250, 140, 380, 190], fill=accent)
    draw.ellipse([420, 130, 500, 210], fill=accent)

    y = int(height * 0.52)
    for line in textwrap.wrap(description, width=48):
        draw.text((60, y), line, fill="#333333", font=body_font)
        y += 22
        if y > height - 60:
            break

    if out_path is None:
        out_path = Path("room.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)
    return out_path
