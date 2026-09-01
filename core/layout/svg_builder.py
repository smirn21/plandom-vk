"""Генерация SVG-плана из JSON (MVP, без AI)."""
from __future__ import annotations

from typing import Any


def layout_json_to_svg(layout: dict[str, Any], width: int = 800, height: int = 600) -> str:
    """
    layout: { "rooms": [ { "name", "x", "y", "w", "h" }, ... ] }
    Координаты в условных единицах 0..100.
    """
    rooms = layout.get("rooms") or []
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 100 100">',
        '<rect width="100" height="100" fill="#f8f6f2"/>',
    ]
    for room in rooms:
        x, y, w, h = room.get("x", 0), room.get("y", 0), room.get("w", 20), room.get("h", 20)
        name = (room.get("name") or "Комната").replace("&", "&amp;").replace("<", "")
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'fill="#e8efe8" stroke="#4a7c59" stroke-width="0.4"/>'
        )
        parts.append(
            f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
            f'font-family="Arial,sans-serif" font-size="3" fill="#2d4a35">{name}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
