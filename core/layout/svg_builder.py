"""Генерация SVG-плана с размерами, дверями и окнами."""
from __future__ import annotations

import html
from typing import Any


def _esc(text: str) -> str:
    return html.escape(str(text))


def _room_area_label(room: dict[str, Any]) -> str:
    w, l = room.get("width_m"), room.get("length_m")
    if w and l:
        try:
            area = round(float(w) * float(l), 1)
            return f"{float(w):g}×{float(l):g} м · {area:g} м²"
        except (TypeError, ValueError):
            pass
    if room.get("area_m2"):
        return f"{room['area_m2']} м²"
    return ""


def _draw_opening(
    parts: list[str],
    *,
    wall: str,
    x: float,
    y: float,
    w: float,
    h: float,
    offset: float,
    opening_w: float,
    kind: str,
) -> None:
    """offset и opening_w — доли стены 0..1."""
    t = max(0.05, min(0.95, float(offset or 0.5)))
    ow = max(0.08, min(0.45, float(opening_w or 0.15)))
    wall = (wall or "south").lower()
    if wall in ("north", "top"):
        ox = x + w * (t - ow / 2)
        oy = y
        if kind == "door":
            parts.append(
                f'<path d="M {ox:.2f} {oy:.2f} A {ow * w / 2:.2f} {ow * w / 2:.2f} 0 0 1 '
                f'{ox + ow * w:.2f} {oy:.2f}" fill="none" stroke="#6b4c3b" stroke-width="0.25"/>'
            )
        else:
            parts.append(
                f'<rect x="{ox:.2f}" y="{oy:.2f}" width="{ow * w:.2f}" height="0.35" '
                f'fill="#9ec5e8" stroke="#4a7c9e" stroke-width="0.15"/>'
            )
    elif wall in ("south", "bottom"):
        ox = x + w * (t - ow / 2)
        oy = y + h
        if kind == "door":
            parts.append(
                f'<path d="M {ox:.2f} {oy:.2f} A {ow * w / 2:.2f} {ow * w / 2:.2f} 0 0 0 '
                f'{ox + ow * w:.2f} {oy:.2f}" fill="none" stroke="#6b4c3b" stroke-width="0.25"/>'
            )
        else:
            parts.append(
                f'<rect x="{ox:.2f}" y="{oy - 0.35:.2f}" width="{ow * w:.2f}" height="0.35" '
                f'fill="#9ec5e8" stroke="#4a7c9e" stroke-width="0.15"/>'
            )
    elif wall in ("west", "left"):
        ox = x
        oy = y + h * (t - ow / 2)
        parts.append(
            f'<rect x="{ox:.2f}" y="{oy:.2f}" width="0.35" height="{ow * h:.2f}" '
            f'fill="#9ec5e8" stroke="#4a7c9e" stroke-width="0.15"/>'
        )
    else:
        ox = x + w
        oy = y + h * (t - ow / 2)
        parts.append(
            f'<rect x="{ox - 0.35:.2f}" y="{oy:.2f}" width="0.35" height="{ow * h:.2f}" '
            f'fill="#9ec5e8" stroke="#4a7c9e" stroke-width="0.15"/>'
        )


def layout_json_to_svg(
    layout: dict[str, Any],
    *,
    width: int = 1000,
    height: int = 750,
    title: str = "ПланДом — планировка",
    estimated: bool = False,
) -> str:
    rooms = layout.get("rooms") or []
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 100 78">',
        '<rect width="100" height="78" fill="#faf8f4"/>',
        f'<text x="3" y="4.5" font-family="Arial,sans-serif" font-size="2.8" fill="#2d4a35" font-weight="bold">{_esc(title)}</text>',
    ]
    if estimated:
        parts.append(
            '<text x="3" y="7.2" font-family="Arial,sans-serif" font-size="1.8" fill="#a66b00">'
            "⚠ Оценочный план — уточните размеры</text>"
        )
    parts.append('<rect x="2" y="9" width="96" height="67" fill="#ffffff" stroke="#d8d2c8" stroke-width="0.2"/>')

    for room in rooms:
        x, y, w, h = (
            float(room.get("x", 0)),
            float(room.get("y", 0)),
            float(room.get("w", 20)),
            float(room.get("h", 20)),
        )
        x = 2 + x / 100 * 96
        y = 9 + y / 100 * 67
        w = max(4, w / 100 * 96)
        h = max(4, h / 100 * 67)
        name = _esc(room.get("name") or "Комната")
        dim = _esc(_room_area_label(room))
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="#eef4ee" stroke="#2d4a35" stroke-width="0.45"/>'
        )
        parts.append(
            f'<text x="{x + w / 2:.2f}" y="{y + h / 2 - 0.8:.2f}" text-anchor="middle" '
            f'font-family="Arial,sans-serif" font-size="2.2" fill="#2d4a35">{name}</text>'
        )
        if dim:
            parts.append(
                f'<text x="{x + w / 2:.2f}" y="{y + h / 2 + 1.4:.2f}" text-anchor="middle" '
                f'font-family="Arial,sans-serif" font-size="1.7" fill="#5a6b5c">{dim}</text>'
            )
        for door in room.get("doors") or []:
            _draw_opening(
                parts,
                wall=door.get("wall", "south"),
                x=x,
                y=y,
                w=w,
                h=h,
                offset=door.get("offset", 0.5),
                opening_w=door.get("width_m", 0.9) / max(float(room.get("width_m") or 3), 1) * 0.3,
                kind="door",
            )
        for window in room.get("windows") or []:
            _draw_opening(
                parts,
                wall=window.get("wall", "north"),
                x=x,
                y=y,
                w=w,
                h=h,
                offset=window.get("offset", 0.5),
                opening_w=window.get("width_m", 1.2) / max(float(room.get("width_m") or 3), 1) * 0.35,
                kind="window",
            )

    total = layout.get("total_area_m2")
    if total:
        parts.append(
            f'<text x="98" y="76.5" text-anchor="end" font-family="Arial,sans-serif" '
            f'font-size="2" fill="#2d4a35">Σ {total} м²</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
