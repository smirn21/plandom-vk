"""Планировка: Grok + grid fallback."""
from __future__ import annotations

import math
from typing import Any

from core.models import ProjectBrief, ProjectType, RoomSpec, RoomType
from grok_client import GrokClient


def grid_layout(brief: ProjectBrief) -> dict[str, Any]:
    rooms = brief.rooms or [RoomSpec(name="Комната", room_type=RoomType.OTHER)]
    n = len(rooms)
    cols = max(1, math.ceil(math.sqrt(n)))
    rows = max(1, math.ceil(n / cols))
    cell_w = 96 / cols
    cell_h = 96 / rows
    layout_rooms: list[dict[str, Any]] = []
    for i, room in enumerate(rooms):
        col = i % cols
        row = i // cols
        layout_rooms.append(
            {
                "name": room.name,
                "x": round(2 + col * cell_w, 1),
                "y": round(2 + row * cell_h, 1),
                "w": round(cell_w - 2, 1),
                "h": round(cell_h - 2, 1),
            }
        )
    return {"rooms": layout_rooms}


async def build_layout(brief: ProjectBrief, grok: GrokClient | None) -> dict[str, Any]:
    data = brief.to_dict()
    if grok and grok.available:
        layout = await grok.generate_layout(data)
        if layout.get("rooms"):
            names = [r.name for r in brief.rooms]
            for i, room in enumerate(layout["rooms"]):
                if i < len(names):
                    room["name"] = names[i]
            return layout
    return grid_layout(brief)


def brief_from_wizard(data: dict[str, Any]) -> ProjectBrief:
    rooms_raw = data.get("rooms") or []
    rooms: list[RoomSpec] = []
    for r in rooms_raw:
        try:
            rt = RoomType(r.get("room_type", "other"))
        except ValueError:
            rt = RoomType.OTHER
        rooms.append(
            RoomSpec(
                name=r.get("name") or "Комната",
                room_type=rt,
                width_m=r.get("width_m"),
                length_m=r.get("length_m"),
            )
        )
    try:
        ptype = ProjectType(data.get("project_type", "apartment"))
    except ValueError:
        ptype = ProjectType.APARTMENT
    area = data.get("total_area_m2")
    if isinstance(area, str):
        try:
            area = float(area.replace(",", "."))
        except ValueError:
            area = None
    return ProjectBrief(
        project_type=ptype,
        total_area_m2=area,
        rooms=rooms,
        style=data.get("style") or "scandinavian",
        budget_tier=data.get("budget_tier") or "medium",
        floors=int(data.get("floors") or 1),
        notes=data.get("notes") or "",
    )
