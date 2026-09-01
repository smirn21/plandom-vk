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
    """2 ракурса для HD/PRO; 1 ракурс для preview-комнат."""
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
    """Генерирует изображения; второй ракурс с опорой на первый через Vision."""
    out_dir.mkdir(parents=True, exist_ok=True)
    name = room.get("name") or f"Комната {room_index}"
    results: list[tuple[Path, str]] = []
    total = len(views)
    locked_layout = ""
    LOGGER.info(
        "render_room_images: %s index=%d views=%s palette=%d chars",
        name,
        room_index,
        views,
        len(design_palette),
    )

    for vi, view in enumerate(views, start=1):
        view_label = VIEW_LABELS_RU.get(view, view)
        caption = (
            f"🖼 {name} — ракурс {vi}/{total}: {view_label}\n"
            f"Одна комната, та же расстановка мебели."
        )
        out_path = out_dir / f"room_{room_index}_{view}.jpg"
        LOGGER.info(
            "render_room_images: %s view %d/%d (%s) locked=%s",
            name,
            vi,
            total,
            view,
            bool(locked_layout),
        )
        image_bytes = await grok.generate_interior_image(
            room,
            brief,
            description,
            view=view,
            quality="medium",
            view_index=vi,
            views_total=total,
            design_palette=design_palette,
            locked_layout=locked_layout,
        )
        if image_bytes:
            normalized = normalize_image_bytes(image_bytes)
            out_path.write_bytes(normalized)
            LOGGER.info(
                "render_room_images: %s view %s saved %d bytes → %s",
                name,
                view,
                len(normalized),
                out_path.name,
            )
            results.append((out_path, caption))
            if vi == 1 and total > 1:
                LOGGER.info("render_room_images: vision lock for %s", name)
                locked_layout = await grok.lock_design_from_image(normalized, name)
                if locked_layout:
                    LOGGER.info("Design locked for room %s (%d chars)", name, len(locked_layout))
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
