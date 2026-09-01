"""Парсинг и проверка размеров квартиры и комнат."""
from __future__ import annotations

import re
from typing import Any


def parse_area_value(text: str) -> float | None:
    """Число м² или ширина×длина → площадь."""
    text = (text or "").strip().lower().replace(",", ".")
    if not text:
        return None
    text = re.sub(r"\s*м²?\s*$", "", text)
    text = re.sub(r"\s*m2\s*$", "", text)
    dim = re.match(
        r"^\s*(\d+(?:\.\d+)?)\s*[xх×*]\s*(\d+(?:\.\d+)?)\s*$",
        text,
    )
    if dim:
        return round(float(dim.group(1)) * float(dim.group(2)), 2)
    num = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", text)
    if num:
        return round(float(num.group(1)), 2)
    return None


def parse_room_size(text: str) -> tuple[float | None, float | None, float | None]:
    """'3.2x4.5' → (w, l, area); '14' → (None, None, 14)."""
    text = (text or "").strip().lower().replace(",", ".")
    dim = re.match(
        r"^\s*(\d+(?:\.\d+)?)\s*[xх×*]\s*(\d+(?:\.\d+)?)\s*(?:м²?|m2)?\s*$",
        text,
    )
    if dim:
        w, l = float(dim.group(1)), float(dim.group(2))
        return w, l, round(w * l, 2)
    area = parse_area_value(text)
    if area is not None:
        return None, None, area
    return None, None, None


def room_area_m2(room: dict[str, Any]) -> float | None:
    w, l = room.get("width_m"), room.get("length_m")
    if w and l:
        try:
            return round(float(w) * float(l), 2)
        except (TypeError, ValueError):
            pass
    area = room.get("area_m2")
    if area is not None:
        try:
            return round(float(area), 2)
        except (TypeError, ValueError):
            pass
    return None


def sum_room_areas(rooms: list[dict[str, Any]]) -> float:
    total = 0.0
    for room in rooms:
        a = room_area_m2(room)
        if a:
            total += a
    return round(total, 2)


def validate_areas(total_area: float | None, rooms: list[dict[str, Any]], *, tolerance: float = 0.15) -> tuple[bool, str]:
    """Проверка: сумма комнат ≈ площади квартиры."""
    if not total_area or not rooms:
        return True, ""
    room_sum = sum_room_areas(rooms)
    if room_sum <= 0:
        return True, ""
    diff = abs(room_sum - float(total_area))
    limit = max(3.0, float(total_area) * tolerance)
    if diff <= limit:
        return True, ""
    return (
        False,
        f"Сумма комнат ({room_sum:.1f} м²) не совпадает с площадью объекта "
        f"({float(total_area):.1f} м²). Разница: {diff:.1f} м².\n"
        "Исправьте площадь или размеры комнат.",
    )


def apply_room_sizes_text(rooms: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Парсит строки вида «Спальня 3.2x4.5» или «Кухня 12»."""
    out = [dict(r) for r in rooms]
    by_name = {r.get("name", "").lower(): i for i, r in enumerate(out)}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(
            r"^(.+?)\s+(\d+(?:\.\d+)?(?:\s*[xх×*]\s*\d+(?:\.\d+)?)?)\s*(?:м²?|m2)?\s*$",
            line,
            re.I,
        )
        if not m:
            continue
        name_part, size_part = m.group(1).strip(), m.group(2)
        w, l, area = parse_room_size(size_part)
        idx = by_name.get(name_part.lower())
        if idx is None:
            for i, r in enumerate(out):
                if name_part.lower() in (r.get("name") or "").lower():
                    idx = i
                    break
        if idx is None:
            continue
        if w and l:
            out[idx]["width_m"] = w
            out[idx]["length_m"] = l
            out[idx]["area_m2"] = area
        elif area:
            out[idx]["area_m2"] = area
    return out
