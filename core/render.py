"""Рендер плана, watermark, PDF."""
from __future__ import annotations

import io
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from core.layout.svg_builder import layout_json_to_svg


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def layout_to_png(layout: dict[str, Any], out_path: Path, size: int = 900) -> Path:
    rooms = layout.get("rooms") or []
    img = Image.new("RGB", (size, int(size * 0.75)), "#f8f6f2")
    draw = ImageDraw.Draw(img)
    font = _font(18)
    title_font = _font(22)
    draw.text((20, 12), "ПланДом — планировка", fill="#2d4a35", font=title_font)
    ox, oy = 20, 50
    pw, ph = size - 40, int(size * 0.75) - 70
    for room in rooms:
        x = ox + int(room.get("x", 0) / 100 * pw)
        y = oy + int(room.get("y", 0) / 100 * ph)
        w = max(20, int(room.get("w", 20) / 100 * pw))
        h = max(20, int(room.get("h", 20) / 100 * ph))
        draw.rectangle([x, y, x + w, y + h], fill="#e8efe8", outline="#4a7c59", width=2)
        name = (room.get("name") or "Комната")[:20]
        draw.text((x + 6, y + h // 2 - 8), name, fill="#2d4a35", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG", optimize=True)
    layout_json_to_svg(layout)  # keep svg_builder used; SVG saved optionally
    svg_path = out_path.with_suffix(".svg")
    svg_path.write_text(layout_json_to_svg(layout), encoding="utf-8")
    return out_path


def add_watermark(image_path: Path, label: str = "ПланДом — превью") -> Path:
    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(max(16, img.width // 28))
    text = label
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img.width - tw) // 2
    y = (img.height - th) // 2
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0, 90), font=font)
    draw.text((x, y), text, fill=(255, 255, 255, 170), font=font)
    draw.line([(0, img.height), (img.width, 0)], fill=(255, 255, 255, 80), width=3)
    out = Image.alpha_composite(img, overlay).convert("RGB")
    out.save(image_path, format="PNG", optimize=True)
    return image_path


def build_pdf(
    plan_path: Path,
    room_items: list[tuple[str, Path, str]],
    out_path: Path,
    title: str = "ПланДом — проект",
) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 18)
    c.drawString(2 * cm, h - 2 * cm, title)
    c.setFont("Helvetica", 11)
    c.drawString(2 * cm, h - 2.8 * cm, "Сгенерировано ботом ПланДом")

    if plan_path.is_file():
        c.drawImage(str(plan_path), 2 * cm, h - 16 * cm, width=16 * cm, height=12 * cm, preserveAspectRatio=True)
    c.showPage()

    for room_name, img_path, description in room_items:
        c.setFont("Helvetica-Bold", 16)
        c.drawString(2 * cm, h - 2 * cm, room_name)
        if img_path.is_file():
            c.drawImage(str(img_path), 2 * cm, h - 12 * cm, width=14 * cm, height=9 * cm, preserveAspectRatio=True)
        c.setFont("Helvetica", 10)
        y = h - 13.5 * cm
        for line in textwrap.wrap(description or "", width=90):
            c.drawString(2 * cm, y, line)
            y -= 0.45 * cm
        c.showPage()

    c.save()
    return out_path


def png_bytes(path: Path) -> bytes:
    return path.read_bytes()
