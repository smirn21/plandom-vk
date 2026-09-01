"""Админ-панель ПланДом: подписки и пользователи."""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from storage import Storage, PRO_PROJECTS_PER_MONTH

LOGGER = logging.getLogger(__name__)

SendFn = Callable[[str, str | None], Awaitable[None]]


def is_vk_admin(user_id: str, admin_ids: list[str]) -> bool:
    return str(user_id) in {str(a) for a in admin_ids}


def _fmt_created(value: Any) -> str:
    if not value:
        return "—"
    try:
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y %H:%M")
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


async def fetch_vk_name(api: Any, user_id: str) -> str | None:
    if not api or not user_id:
        return None
    try:
        resp = await api.request("users.get", {"user_ids": str(user_id)})
        users = resp if isinstance(resp, list) else (resp.get("response") if isinstance(resp, dict) else None)
        if users and isinstance(users, list):
            u = users[0]
            parts = [u.get("first_name"), u.get("last_name")]
            name = " ".join(p for p in parts if p).strip()
            return name or None
    except Exception as exc:
        LOGGER.debug("users.get failed: %s", exc)
    return None


async def fetch_vk_names(api: Any, user_ids: list[str]) -> dict[str, str]:
    if not api or not user_ids:
        return {}
    try:
        resp = await api.request("users.get", {"user_ids": ",".join(user_ids[:100])})
        users = resp if isinstance(resp, list) else (resp.get("response") if isinstance(resp, dict) else None)
        out: dict[str, str] = {}
        if isinstance(users, list):
            for u in users:
                uid = str(u.get("id", ""))
                parts = [u.get("first_name"), u.get("last_name")]
                name = " ".join(p for p in parts if p).strip()
                if uid and name:
                    out[uid] = name
        return out
    except Exception as exc:
        LOGGER.debug("users.get batch failed: %s", exc)
        return {}


def _cb(label: str, payload: dict[str, Any], color: str | None = None) -> dict[str, Any]:
    btn: dict[str, Any] = {
        "action": {
            "type": "callback",
            "label": label,
            "payload": json.dumps(payload, ensure_ascii=False),
        }
    }
    if color in ("primary", "secondary", "positive", "negative"):
        btn["color"] = color
    return btn


def admin_menu_keyboard() -> str:
    buttons = [
        [
            _cb("✅ PRO 30 дн.", {"cmd": "admin_activate_sub"}, "positive"),
            _cb("❌ Снять PRO", {"cmd": "admin_remove_sub"}, "negative"),
        ],
        [
            _cb("🔍 Найти по ID", {"cmd": "admin_find_user"}, "primary"),
            _cb("👥 Список", {"cmd": "admin_list_users"}),
        ],
        [_cb("📊 Статистика", {"cmd": "admin_stats"}, "primary")],
        [_cb("◀️ В меню", {"cmd": "menu"})],
    ]
    return json.dumps({"inline": True, "buttons": buttons}, ensure_ascii=False)


def userinfo_keyboard(target_user_id: str) -> str:
    return json.dumps(
        {
            "inline": True,
            "buttons": [
                [
                    _cb("✅ PRO 30 дн.", {"cmd": "admin_sub_days", "id": target_user_id, "days": 30}, "positive"),
                    _cb("✅ PRO 365 дн.", {"cmd": "admin_sub_days", "id": target_user_id, "days": 365}, "positive"),
                ],
                [_cb("❌ Снять PRO", {"cmd": "admin_unsub_id", "id": target_user_id}, "negative")],
                [_cb("🔄 Сброс free trial", {"cmd": "admin_reset_free", "id": target_user_id})],
                [_cb("◀️ Админ-меню", {"cmd": "admin"})],
            ],
        },
        ensure_ascii=False,
    )


def format_userinfo(storage: Storage, target_user_id: str, display_name: str | None = None) -> str:
    user = storage.get_user(target_user_id)
    pro = storage.is_pro(target_user_id)
    remaining = storage.pro_projects_remaining(target_user_id) if pro else 0
    name_line = f"Имя: {display_name}\n" if display_name else ""
    created = _fmt_created(user.get("created_at"))
    free_used = "да" if user.get("free_trial_used") else "нет"
    if pro:
        exp = user.get("subscription_expires_at")
        exp_s = _fmt_created(exp) if exp else "—"
        return (
            f"VK ID: {target_user_id}\n"
            f"{name_line}"
            f"Регистрация: {created}\n"
            f"Статус: PRO\n"
            f"До: {exp_s}\n"
            f"PRO-проектов осталось: {remaining}/{PRO_PROJECTS_PER_MONTH}\n"
            f"Free trial использован: {free_used}"
        )
    return (
        f"VK ID: {target_user_id}\n"
        f"{name_line}"
        f"Регистрация: {created}\n"
        f"Статус: free\n"
        f"Free trial использован: {free_used}"
    )


def format_stats(storage: Storage) -> str:
    with storage._connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pro = conn.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE subscription = 'pro'
              AND subscription_expires_at IS NOT NULL
              AND subscription_expires_at > ?
            """,
            (datetime.now().isoformat(),),
        ).fetchone()[0]
        projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        paid = conn.execute("SELECT COUNT(*) FROM projects WHERE is_paid = 1").fetchone()[0]
    return (
        "📊 Статистика ПланДом\n\n"
        f"Пользователей: {total}\n"
        f"PRO: {pro}\n"
        f"Free: {total - pro}\n"
        f"Проектов: {projects}\n"
        f"Оплаченных: {paid}"
    )


async def format_users_list(storage: Storage, api: Any = None, limit: int = 20) -> str:
    rows = storage.list_recent_users(limit=limit)
    if not rows:
        return "Пользователей пока нет."
    names = await fetch_vk_names(api, [str(r["user_id"]) for r in rows])
    lines = ["Последние пользователи:\n"]
    for row in rows:
        uid = str(row["user_id"])
        name = names.get(uid) or "—"
        sub = row.get("subscription") or "free"
        created = _fmt_created(row.get("created_at"))
        icon = "⭐" if sub == "pro" else "·"
        lines.append(f"{icon} {name} | {created}\n   id {uid}")
    return "\n".join(lines)


async def show_admin_menu(send: SendFn, admin_user_id: str | None = None) -> None:
    own = f"\nВаш VK ID: {admin_user_id}" if admin_user_id else ""
    await send(
        "🔧 Админ-панель ПланДом"
        + own
        + "\n\n"
        "Команды:\n"
        "• /sub <id> [дней] — выдать PRO\n"
        "• /unsub <id> — снять PRO\n"
        "• /userinfo <id> — карточка пользователя\n"
        "• /admin — это меню",
        admin_menu_keyboard(),
    )


async def handle_admin_callback(
    storage: Storage,
    admin_ids: list[str],
    user_id: str,
    payload: dict[str, Any],
    send: SendFn,
    api: Any = None,
) -> bool:
    if not is_vk_admin(user_id, admin_ids):
        return False
    cmd = payload.get("cmd")
    if cmd == "admin":
        storage.set_admin_state(user_id, None)
        await show_admin_menu(send, admin_user_id=user_id)
        return True
    if cmd == "admin_stats":
        await send(format_stats(storage), admin_menu_keyboard())
        return True
    if cmd == "admin_list_users":
        await send(await format_users_list(storage, api=api), admin_menu_keyboard())
        return True
    if cmd == "admin_find_user":
        storage.set_admin_state(user_id, "find_user")
        await send("Введите VK ID пользователя (цифры).\nОтмена: /admin", None)
        return True
    if cmd == "admin_activate_sub":
        storage.set_admin_state(user_id, "activate_sub")
        await send("VK ID для PRO на 30 дней.\nОтмена: /admin", None)
        return True
    if cmd == "admin_remove_sub":
        storage.set_admin_state(user_id, "remove_sub")
        await send("VK ID для снятия PRO.\nОтмена: /admin", None)
        return True
    if cmd == "admin_sub_days":
        target = str(payload.get("id") or "")
        days = int(payload.get("days") or 30)
        if target:
            expires = (datetime.now() + timedelta(days=days)).isoformat()
            sub_type = "year" if days >= 300 else "month"
            storage.set_subscription(target, "pro", expires, sub_type)
            await send(
                f"✅ PRO для {target} до {_fmt_created(expires)} ({days} дн.)",
                admin_menu_keyboard(),
            )
        return True
    if cmd == "admin_unsub_id":
        target = str(payload.get("id") or "")
        if target:
            storage.clear_subscription(target)
            await send(f"❌ PRO снят для {target}", admin_menu_keyboard())
        return True
    if cmd == "admin_reset_free":
        target = str(payload.get("id") or "")
        if target:
            storage.reset_free_trial(target)
            await send(f"🔄 Free trial сброшен для {target}", userinfo_keyboard(target))
        return True
    return False


async def handle_admin_text_command(
    storage: Storage,
    admin_ids: list[str],
    user_id: str,
    text: str,
    send: SendFn,
    api: Any = None,
) -> bool:
    if not is_vk_admin(user_id, admin_ids):
        return False
    raw = (text or "").strip()
    lower = raw.lower()

    if lower in {"/admin", "админ", "🔧 админ панель", "🔧 админ-панель"}:
        storage.set_admin_state(user_id, None)
        await show_admin_menu(send, admin_user_id=user_id)
        return True

    if lower.startswith("/sub"):
        parts = raw.split()
        if len(parts) < 2:
            await send("Использование: /sub <vk_id> [дней]", None)
            return True
        target = parts[1]
        days = int(parts[2]) if len(parts) > 2 else 30
        expires = (datetime.now() + timedelta(days=days)).isoformat()
        sub_type = "year" if days >= 300 else "month"
        storage.set_subscription(target, "pro", expires, sub_type)
        await send(f"✅ PRO для {target} до {_fmt_created(expires)}", admin_menu_keyboard())
        return True

    if lower.startswith("/unsub"):
        parts = raw.split()
        if len(parts) < 2:
            await send("Использование: /unsub <vk_id>", None)
            return True
        storage.clear_subscription(parts[1])
        await send(f"❌ PRO снят для {parts[1]}", admin_menu_keyboard())
        return True

    if lower.startswith("/userinfo"):
        parts = raw.split()
        if len(parts) < 2:
            await send("Использование: /userinfo <vk_id>", None)
            return True
        target = parts[1]
        name = await fetch_vk_name(api, target)
        await send(format_userinfo(storage, target, display_name=name), userinfo_keyboard(target))
        return True

    return False


async def handle_admin_waiting_input(
    storage: Storage,
    admin_ids: list[str],
    user_id: str,
    text: str,
    send: SendFn,
    api: Any = None,
) -> bool:
    if not is_vk_admin(user_id, admin_ids):
        return False
    action = storage.get_admin_state(user_id)
    if not action:
        return False

    raw = (text or "").strip()
    lower = raw.lower()
    if lower in {"/admin", "отмена", "cancel"}:
        storage.set_admin_state(user_id, None)
        await show_admin_menu(send, admin_user_id=user_id)
        return True

    target = raw.split()[0] if raw else ""
    if not target.isdigit():
        await send("Нужен числовой VK ID. Отмена: /admin", None)
        return True

    storage.set_admin_state(user_id, None)
    storage.ensure_user(target)

    if action == "find_user":
        name = await fetch_vk_name(api, target)
        await send(format_userinfo(storage, target, display_name=name), userinfo_keyboard(target))
        return True
    if action == "remove_sub":
        storage.clear_subscription(target)
        await send(f"❌ PRO снят для {target}.", admin_menu_keyboard())
        return True
    if action == "activate_sub":
        expires = (datetime.now() + timedelta(days=30)).isoformat()
        storage.set_subscription(target, "pro", expires, "month")
        await send(f"✅ PRO 30 дн. для {target} до {_fmt_created(expires)}.", admin_menu_keyboard())
        return True

    await show_admin_menu(send, admin_user_id=user_id)
    return True
