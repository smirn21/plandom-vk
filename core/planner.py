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
                "room_type": room.room_type.value,
                "x": round(2 + col * cell_w, 1),
                "y": round(2 + row * cell_h, 1),
                "w": round(cell_w - 2, 1),
                "h": round(cell_h - 2, 1),
                "width_m": room.width_m,
                "length_m": room.length_m,
                "area_m2": room.area_m2,
                "doors": list(room.doors),
                "windows": list(room.windows),
            }
        )
    return {"rooms": layout_rooms}


def _merge_layout(brief: ProjectBrief, grok_rooms: list[dict[str, Any]]) -> dict[str, Any]:
    """Grok может вернуть меньше комнат — дополняем из brief и grid."""
    fallback = grid_layout(brief)
    fb_rooms = fallback["rooms"]
    merged: list[dict[str, Any]] = []
    for i, spec in enumerate(brief.rooms or []):
        base = dict(fb_rooms[i]) if i < len(fb_rooms) else {
            "name": spec.name,
            "room_type": spec.room_type.value,
            "x": 2,
            "y": 2,
            "w": 30,
            "h": 30,
        }
        if i < len(grok_rooms):
            gr = grok_rooms[i]
            for key in ("x", "y", "w", "h", "doors", "windows"):
                if key in gr:
                    base[key] = gr[key]
        base["name"] = spec.name
        base["room_type"] = spec.room_type.value
        if spec.width_m is not None:
            base["width_m"] = spec.width_m
        if spec.length_m is not None:
            base["length_m"] = spec.length_m
        if spec.area_m2 is not None:
            base["area_m2"] = spec.area_m2
        merged.append(base)
    return {"rooms": merged}


async def build_layout(brief: ProjectBrief, grok: GrokClient | None) -> dict[str, Any]:
    data = brief.to_dict()
    if grok and grok.available:
        layout = await grok.generate_layout(data)
        grok_rooms = layout.get("rooms") or []
        if grok_rooms and brief.rooms:
            return _merge_layout(brief, grok_rooms)
    return grid_layout(brief)


def brief_from_wizard(data: dict[str, Any]) -> ProjectBrief:
    rooms_raw = data.get("rooms") or []
    rooms: list[RoomSpec] = []
    for r in rooms_raw:
        try:
            rt = RoomType(r.get("room_type", "other"))
        except ValueError:
            rt = RoomType.OTHER
        w, l, a = r.get("width_m"), r.get("length_m"), r.get("area_m2")
        rooms.append(
            RoomSpec(
                name=r.get("name") or "Комната",
                room_type=rt,
                width_m=float(w) if w is not None else None,
                length_m=float(l) if l is not None else None,
                area_m2=float(a) if a is not None else None,
                doors=list(r.get("doors") or []),
                windows=list(r.get("windows") or []),
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
    ceiling = data.get("ceiling_height_m")
    if isinstance(ceiling, str):
        try:
            ceiling = float(ceiling.replace(",", "."))
        except ValueError:
            ceiling = None
    return ProjectBrief(
        project_type=ptype,
        total_area_m2=area,
        rooms=rooms,
        style=data.get("style") or "scandinavian",
        style_notes=data.get("style_notes") or "",
        budget_tier=data.get("budget_tier") or "medium",
        floors=int(data.get("floors") or 1),
        notes=data.get("notes") or "",
        ceiling_height_m=ceiling,
        openings_notes=data.get("openings_notes") or "",
        wet_zones=data.get("wet_zones") or "",
        furniture_wishes=data.get("furniture_wishes") or "",
        blueprint_estimated=bool(data.get("blueprint_estimated")),
        input_mode=data.get("input_mode") or "manual",
    )
