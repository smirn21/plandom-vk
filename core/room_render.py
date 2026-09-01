"""Фотореалистичный рендер комнат через Grok Imagine."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.image_gen import render_room_card
from core.image_normalize import normalize_image_bytes
from grok_client import GrokClient

LOGGER = logging.getLogger(__name__)

VIEWS = ("entrance", "window")
PRO_EXTRA_VIEWS = ("corner",)


async def render_room_images(
    grok: GrokClient,
    room: dict[str, Any],
    brief: dict[str, Any],
    description: str,
    out_dir: Path,
    room_index: int,
    *,
    pro_variants: bool = False,
) -> list[Path]:
    """2 ракурса для всех; +1 вариант для PRO."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    views = list(VIEWS)
    if pro_variants:
        views.append("corner")

    for vi, view in enumerate(views):
        out_path = out_dir / f"room_{room_index}_{view}.jpg"
        image_bytes = await grok.generate_interior_image(
            room, brief, description, view=view, quality="medium"
        )
        if image_bytes:
            out_path.write_bytes(normalize_image_bytes(image_bytes))
            paths.append(out_path)
        else:
            LOGGER.warning("Fallback placeholder for room %s view %s", room_index, view)
            render_room_card(
                room.get("name") or f"Комната {room_index}",
                description,
                brief.get("style", "scandinavian"),
                out_path,
            )
            paths.append(out_path)
    return paths
