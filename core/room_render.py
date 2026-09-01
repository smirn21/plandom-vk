"""Фотореалистичный рендер комнат через Grok Imagine."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.image_gen import render_room_card
from core.image_normalize import normalize_image_bytes
from grok_client import GrokClient

LOGGER = logging.getLogger(__name__)

VIEW_LABELS_RU = {
    "entrance": "от входа",
    "window": "к окну",
    "corner": "угловой ракурс",
}


def views_for_tier(tier: str, *, room_index: int, is_hd: bool) -> tuple[str, ...]:
    """Меньше ракурсов = быстрее; free HD-комната — 2 ракурса."""
    if tier == "pro":
        return ("window", "entrance")
    if tier in ("free", "full") and is_hd:
        return ("window", "entrance")
    return ("window",)


async def render_room_images(
    grok: GrokClient,
    room: dict[str, Any],
    brief: dict[str, Any],
    description: str,
    out_dir: Path,
    room_index: int,
    *,
    views: tuple[str, ...],
    design_palette: str = "",
) -> list[tuple[Path, str]]:
    """Генерирует изображения; возвращает (path, подпись для VK)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    name = room.get("name") or f"Комната {room_index}"
    results: list[tuple[Path, str]] = []
    total = len(views)

    for vi, view in enumerate(views, start=1):
        view_label = VIEW_LABELS_RU.get(view, view)
        caption = (
            f"🖼 {name} — ракурс {vi}/{total}: {view_label}\n"
            f"Одна комната, разные точки съёмки."
        )
        out_path = out_dir / f"room_{room_index}_{view}.jpg"
        image_bytes = await grok.generate_interior_image(
            room,
            brief,
            description,
            view=view,
            quality="medium",
            view_index=vi,
            views_total=total,
            design_palette=design_palette,
        )
        if image_bytes:
            out_path.write_bytes(normalize_image_bytes(image_bytes))
            results.append((out_path, caption))
        else:
            LOGGER.warning("Fallback placeholder for room %s view %s", room_index, view)
            render_room_card(
                name,
                description,
                brief.get("style", "scandinavian"),
                out_path,
            )
            results.append((out_path, caption + "\n(превью-заглушка)"))
    return results
