"""Помощники wizard: сводка, валидация, переходы."""
from __future__ import annotations

from typing import Any

from core.dimensions import apply_room_sizes_text, validate_areas


def wizard_summary(data: dict[str, Any]) -> str:
    ptype = data.get("project_type", "apartment")
    labels = {"apartment": "Квартира", "house": "Дом", "single_room": "Одна комната"}
    rooms = data.get("rooms") or []
    room_lines = []
    for r in rooms:
        line = r.get("name", "?")
        if r.get("width_m") and r.get("length_m"):
            line += f" ({r['width_m']}×{r['length_m']} м)"
        elif r.get("area_m2"):
            line += f" ({r['area_m2']} м²)"
        room_lines.append(line)
    room_list = ", ".join(room_lines) or "—"
    area = data.get("total_area_m2")
    area_s = f"{area} м²" if area else "не указана"
    est = " ⚠ оценочно" if data.get("blueprint_estimated") else ""
    lines = [
        "📋 Проверьте данные:\n",
        f"Тип: {labels.get(ptype, ptype)}",
        f"Площадь: {area_s}{est}",
        f"Комнаты: {room_list}",
    ]
    if data.get("ceiling_height_m"):
        lines.append(f"Потолок: {data['ceiling_height_m']} м")
    if data.get("openings_notes"):
        lines.append(f"Окна/двери: {data['openings_notes'][:80]}")
    if data.get("wet_zones"):
        lines.append(f"Мокрые зоны: {data['wet_zones'][:80]}")
    lines.append(f"Стиль: {data.get('style', 'scandinavian')}")
    if data.get("style_notes"):
        lines.append(f"Уточнение стиля: {data['style_notes'][:80]}")
    lines.append(f"Бюджет: {data.get('budget_tier', 'medium')}")
    if data.get("furniture_wishes"):
        lines.append(f"Пожелания: {data['furniture_wishes'][:80]}")
    if data.get("input_mode") == "blueprint":
        files = data.get("blueprint_files") or []
        if files:
            lines.append(f"Чертежи: {len(files)} файл(ов)")
    return "\n".join(lines)


def blueprint_review_summary(data: dict[str, Any]) -> str:
    lines = ["📐 Распознанный план:\n"]
    if data.get("blueprint_estimated"):
        lines.append("⚠ План оценочный — проверьте размеры.\n")
    if data.get("notes"):
        lines.append(f"Примечание: {data['notes']}\n")
    lines.append(wizard_summary(data))
    lines.append("\nИсправьте кнопками или подтвердите.")
    return "\n".join(lines)


def check_area_mismatch(data: dict[str, Any]) -> tuple[bool, str]:
    total = data.get("total_area_m2")
    rooms = data.get("rooms") or []
    if total is None:
        return True, ""
    try:
        total_f = float(total)
    except (TypeError, ValueError):
        return True, ""
    ok, msg = validate_areas(total_f, rooms)
    return ok, msg


def apply_blueprint_to_wizard(data: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    out["input_mode"] = "blueprint"
    out["blueprint_estimated"] = bool(parsed.get("estimated"))
    if parsed.get("total_area_m2"):
        out["total_area_m2"] = parsed["total_area_m2"]
    if parsed.get("ceiling_height_m"):
        out["ceiling_height_m"] = parsed["ceiling_height_m"]
    if parsed.get("notes"):
        out["notes"] = parsed.get("notes", "")
    if parsed.get("rooms"):
        out["rooms"] = parsed["rooms"]
        out["selected_rooms"] = [r.get("room_type", "other") for r in parsed["rooms"]]
    if parsed.get("blueprint_files"):
        out["blueprint_files"] = parsed["blueprint_files"]
    return out


def parse_room_sizes_step(data: dict[str, Any], text: str) -> dict[str, Any]:
    out = dict(data)
    rooms = out.get("rooms") or []
    if text.strip().lower() in {"пропустить", "skip", "-"}:
        return out
    out["rooms"] = apply_room_sizes_text(rooms, text)
    return out
