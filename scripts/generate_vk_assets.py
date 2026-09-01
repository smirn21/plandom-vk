"""Генерация лого, обложки и картинок постов для VK ПланДом."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets" / "vk"
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def _font(size: int):
    return ImageFont.truetype(FONT, size)


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(248 * (1 - t) + 74 * t)
        g = int(246 * (1 - t) + 124 * t)
        b = int(242 * (1 - t) + 89 * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def make_logo(path: Path) -> None:
    size = 512
    img = _gradient(size, size)
    draw = ImageDraw.Draw(img)
    draw.ellipse([40, 40, size - 40, size - 40], fill=(255, 255, 255, 180), outline="#4a7c59", width=8)
    draw.text((size // 2 - 120, size // 2 - 70), "План", fill="#2d4a35", font=_font(72))
    draw.text((size // 2 - 60, size // 2 + 10), "Дом", fill="#4a7c59", font=_font(72))
    draw.text((size // 2 - 130, size - 90), "AI-планировка", fill="#555555", font=_font(28))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


def make_cover(path: Path) -> None:
    w, h = 1590, 400
    img = _gradient(w, h)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, h], outline="#ffffff55", width=2)
    draw.text((60, 80), "ПланДом", fill="#ffffff", font=_font(96))
    draw.text((60, 210), "AI-планировка и обстановка квартир и домов", fill="#f0f0f0", font=_font(36))
    draw.text((60, 280), "Бесплатный пробник · PDF · PRO 399 ₽/мес", fill="#e8efe8", font=_font(28))
    img.save(path, "PNG", optimize=True)


def make_post(path: Path, title: str, lines: list[str], accent: str = "#4a7c59") -> None:
    w, h = 1200, 900
    img = _gradient(w, h)
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 50, w - 50, h - 50], outline=accent, width=4)
    draw.text((80, 80), title, fill="#2d4a35", font=_font(52))
    y = 180
    for line in lines:
        draw.text((80, y), line, fill="#333333", font=_font(30))
        y += 48
    img.save(path, "JPEG", quality=88, optimize=True)


POSTS = [
    {
        "id": "welcome",
        "file": "post-01-welcome.jpg",
        "text": (
            "🏠 Добро пожаловать в ПланДом!\n\n"
            "AI помогает спланировать квартиру или дом и показать обстановку по комнатам.\n\n"
            "Напишите боту «Начать» или нажмите «Написать сообщение».\n"
            "Бесплатно: схема + 1 комната в HD."
        ),
        "title": "Добро пожаловать!",
        "lines": [
            "• Планировка за минуты",
            "• Обстановка по комнатам",
            "• PNG в чат, PDF в PRO",
        ],
    },
    {
        "id": "howto",
        "file": "post-02-howto.jpg",
        "text": (
            "📋 Как это работает\n\n"
            "1. Выберите тип: квартира, дом или одна комната\n"
            "2. Укажите комнаты, стиль и бюджет\n"
            "3. Получите план и визуализации в сообщениях\n\n"
            "Полный проект — от 399 ₽, PRO — 399 ₽/мес."
        ),
        "title": "Как пользоваться",
        "lines": ["1. Wizard в боте", "2. AI-план + комнаты", "3. Оплата при необходимости"],
    },
    {
        "id": "pricing",
        "file": "post-03-pricing.jpg",
        "text": (
            "💳 Тарифы ПланДом\n\n"
            "Free — схема + 1 комната\n"
            "Квартира — 399 ₽ (все комнаты + PDF)\n"
            "Дом — 799 ₽\n"
            "PRO — 399 ₽/мес (3 проекта)\n\n"
            "Оплата картой и СБП через ЮKassa."
        ),
        "title": "Тарифы",
        "lines": ["399 ₽ квартира", "799 ₽ дом", "PRO 399 ₽/мес"],
    },
]


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_logo(ASSETS / "logo.png")
    make_cover(ASSETS / "cover.png")
    meta = []
    for p in POSTS:
        fp = ASSETS / p["file"]
        make_post(fp, p["title"], p["lines"])
        meta.append({"id": p["id"], "file": p["file"], "text": p["text"]})
    (ASSETS / "posts.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Assets OK:", ASSETS)


if __name__ == "__main__":
    main()
