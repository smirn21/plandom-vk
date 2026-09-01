"""Клавиатуры VK для ПланДом."""
from __future__ import annotations

import json
from typing import Any


def _text(label: str, color: str | None = None) -> dict[str, Any]:
    btn: dict[str, Any] = {"action": {"type": "text", "label": label}}
    if color:
        btn["color"] = color
    return btn


def _cb(label: str, payload: dict[str, Any], color: str | None = None) -> dict[str, Any]:
    btn: dict[str, Any] = {
        "action": {
            "type": "callback",
            "label": label,
            "payload": json.dumps(payload, ensure_ascii=False),
        }
    }
    if color:
        btn["color"] = color
    return btn


def main_keyboard(is_admin: bool = False) -> str:
    buttons = [
        [_text("🏠 Новый проект", "primary"), _text("📊 Мой статус")],
        [_text("💳 Тарифы"), _text("❓ Помощь")],
    ]
    if is_admin:
        buttons.append([_text("🔧 Админ панель", "positive")])
    return json.dumps({"one_time": False, "buttons": buttons}, ensure_ascii=False)


def type_keyboard() -> str:
    return json.dumps(
        {
            "inline": True,
            "buttons": [
                [_cb("Квартира", {"cmd": "type", "value": "apartment"}, "primary")],
                [_cb("Дом", {"cmd": "type", "value": "house"})],
                [_cb("Одна комната", {"cmd": "type", "value": "single_room"})],
            ],
        },
        ensure_ascii=False,
    )


def area_keyboard() -> str:
    return json.dumps(
        {
            "inline": True,
            "buttons": [
                [
                    _cb("до 45 м²", {"cmd": "area", "value": "40"}),
                    _cb("45–70", {"cmd": "area", "value": "55"}),
                ],
                [
                    _cb("70–100", {"cmd": "area", "value": "85"}),
                    _cb("100+", {"cmd": "area", "value": "120"}),
                ],
                [_cb("Пропустить", {"cmd": "area", "value": "skip"})],
            ],
        },
        ensure_ascii=False,
    )


ROOM_PRESETS = [
    ("living", "Гостиная"),
    ("bedroom", "Спальня"),
    ("kitchen", "Кухня"),
    ("bath", "Санузел"),
    ("hall", "Прихожая"),
    ("office", "Кабинет"),
    ("kids", "Детская"),
]


def rooms_keyboard(selected: set[str]) -> str:
    rows = []
    row: list[dict[str, Any]] = []
    for key, label in ROOM_PRESETS:
        mark = "✓ " if key in selected else ""
        row.append(_cb(f"{mark}{label}", {"cmd": "room_toggle", "value": key}))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([_cb("Готово → стиль", {"cmd": "rooms_done"}, "primary")])
    return json.dumps({"inline": True, "buttons": rows}, ensure_ascii=False)


def style_keyboard() -> str:
    styles = [
        ("scandinavian", "Сканди"),
        ("modern", "Современный"),
        ("loft", "Лофт"),
        ("classic", "Классика"),
        ("minimal", "Минимализм"),
    ]
    rows = []
    row: list[dict[str, Any]] = []
    for val, label in styles:
        row.append(_cb(label, {"cmd": "style", "value": val}))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return json.dumps({"inline": True, "buttons": rows}, ensure_ascii=False)


def budget_keyboard() -> str:
    return json.dumps(
        {
            "inline": True,
            "buttons": [
                [
                    _cb("Эконом", {"cmd": "budget", "value": "economy"}),
                    _cb("Средний", {"cmd": "budget", "value": "medium"}, "primary"),
                    _cb("Премиум", {"cmd": "budget", "value": "premium"}),
                ]
            ],
        },
        ensure_ascii=False,
    )


def confirm_keyboard() -> str:
    return json.dumps(
        {
            "inline": True,
            "buttons": [
                [_cb("✅ Сгенерировать", {"cmd": "generate"}, "positive")],
                [_cb("✏️ Изменить тип", {"cmd": "restart"})],
            ],
        },
        ensure_ascii=False,
    )


def pay_keyboard(project_id: str, project_type: str) -> str:
    return json.dumps(
        {
            "inline": True,
            "buttons": [
                [
                    _cb(
                        "💳 Полный проект",
                        {"cmd": "pay", "kind": project_type, "project_id": project_id},
                        "primary",
                    )
                ],
                [_cb("⭐ PRO 399 ₽/мес", {"cmd": "pay", "kind": "subscription"})],
            ],
        },
        ensure_ascii=False,
    )


def tariffs_keyboard(payments_ok: bool) -> str:
    if not payments_ok:
        return json.dumps({"inline": True, "buttons": [[_cb("◀️ Назад", {"cmd": "menu"})]]}, ensure_ascii=False)
    return json.dumps(
        {
            "inline": True,
            "buttons": [
                [_cb("Квартира 399 ₽", {"cmd": "pay", "kind": "project_apartment"}, "primary")],
                [_cb("Дом 799 ₽", {"cmd": "pay", "kind": "project_house"})],
                [_cb("PRO 399 ₽/мес", {"cmd": "pay", "kind": "subscription"})],
                [_cb("◀️ Назад", {"cmd": "menu"})],
            ],
        },
        ensure_ascii=False,
    )


def status_keyboard(is_pro: bool, payments_ok: bool) -> str:
    buttons: list[list[dict[str, Any]]] = []
    if payments_ok and not is_pro:
        buttons.append([_cb("⭐ Оформить PRO", {"cmd": "pay", "kind": "subscription"}, "primary")])
    buttons.append([_cb("🏠 Новый проект", {"cmd": "new_project"})])
    buttons.append([_cb("◀️ Меню", {"cmd": "menu"})])
    return json.dumps({"inline": True, "buttons": buttons}, ensure_ascii=False)
