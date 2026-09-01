"""Обработчики VK-бота ПланДом."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from vkbottle import GroupEventType
from vkbottle.bot import Message, MessageEvent

from core.image_gen import render_room_card
from core.models import ProjectType, RoomSpec, RoomType
from core.planner import brief_from_wizard, build_layout
from core.render import add_watermark, build_pdf, layout_to_png, png_bytes
from grok_client import GrokClient
from storage import Storage
from vk import keyboards
from vk.media import upload_doc_to_messages, upload_photo_to_messages
from vk.admin import (
    handle_admin_callback,
    handle_admin_text_command,
    handle_admin_waiting_input,
    is_vk_admin,
)
from vk.payments import PRICES, create_plandom_payment, pay_link_keyboard

LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = REPO_ROOT / "output"

WELCOME = (
    "🏠 **ПланДом** — AI-планировка и обстановка квартир и домов.\n\n"
    "Бесплатно: схема + 1 комната в HD.\n"
    "Полный проект: все комнаты + PDF.\n\n"
    "Нажмите «🏠 Новый проект» или выберите тип ниже."
)

ROOM_NAMES = {k: v for k, v in keyboards.ROOM_PRESETS}


async def _send(api, peer_id: int, text: str, keyboard: str | None = None) -> None:
    """Raw messages.send — обходит баг vkbottle+pydantic (MessagesSendPeerIdsResponse)."""
    params: dict = {
        "peer_id": int(peer_id),
        "message": text,
        "random_id": random.randint(1, 2_000_000_000),
    }
    if keyboard:
        params["keyboard"] = keyboard
    try:
        await api.request("messages.send", params)
    except Exception as exc:
        err = str(exc).lower()
        if keyboard and ("912" in err or "chat bot feature" in err):
            LOGGER.warning("Клавиатура недоступна (912), отправляю текст без кнопок")
            params.pop("keyboard", None)
            await api.request("messages.send", params)
            return
        raise


def _resolve_tier(storage: Storage, user_id: str, project_type: str) -> str:
    if storage.is_pro(user_id) and storage.pro_projects_remaining(user_id) > 0:
        return "pro"
    paid = storage.get_unused_project_payment(user_id)
    if paid:
        if paid == "project_house" and project_type != "house":
            pass
        else:
            return "full"
    user = storage.get_user(user_id)
    if not user.get("free_trial_used"):
        return "free"
    return "preview"


def _summary(data: dict) -> str:
    ptype = data.get("project_type", "apartment")
    labels = {"apartment": "Квартира", "house": "Дом", "single_room": "Одна комната"}
    rooms = data.get("rooms") or []
    room_list = ", ".join(r.get("name", "?") for r in rooms) or "—"
    area = data.get("total_area_m2")
    area_s = f"{area} м²" if area else "не указана"
    return (
        f"📋 Проверьте данные:\n\n"
        f"Тип: {labels.get(ptype, ptype)}\n"
        f"Площадь: {area_s}\n"
        f"Комнаты: {room_list}\n"
        f"Стиль: {data.get('style', 'scandinavian')}\n"
        f"Бюджет: {data.get('budget_tier', 'medium')}"
    )


async def _run_generation(
    api,
    storage: Storage,
    grok: GrokClient,
    cfg: dict,
    user_id: str,
    peer_id: int,
    data: dict,
) -> None:
    group_id = int(cfg["vk_group_id"])
    brief = brief_from_wizard(data)
    if not brief.rooms:
        if brief.project_type == ProjectType.SINGLE_ROOM:
            brief.rooms = [RoomSpec(name="Комната", room_type=RoomType.OTHER)]
        else:
            await _send(api, peer_id, "Добавьте хотя бы одну комнату.", keyboards.rooms_keyboard(set()))
            return

    tier = _resolve_tier(storage, user_id, brief.project_type.value)
    project_id = str(uuid.uuid4())[:12]
    out_dir = OUTPUT_ROOT / user_id / project_id
    out_dir.mkdir(parents=True, exist_ok=True)
    storage.create_project(project_id, user_id, brief.to_dict(), tier=tier, output_dir=str(out_dir))

    await _send(api, peer_id, "⏳ Строю планировку и обставляю комнаты…")

    layout = await build_layout(brief, grok)
    storage.update_project(project_id, layout=layout)

    plan_path = layout_to_png(layout, out_dir / "plan.png")
    attachments: list[str] = []
    plan_att = await upload_photo_to_messages(api, peer_id, png_bytes(plan_path), group_id=group_id)
    if plan_att:
        attachments.append(plan_att)

    is_full = tier in ("pro", "full")
    room_items_pdf: list[tuple[str, Path, str]] = []
    free_hd_left = 1 if tier == "free" else 999

    for i, room in enumerate(layout.get("rooms") or []):
        name = room.get("name") or f"Комната {i + 1}"
        desc = await grok.describe_room(room, brief.to_dict())
        card_path = out_dir / f"room_{i + 1}.png"
        render_room_card(name, desc, brief.style, card_path)
        hd = is_full or free_hd_left > 0
        if not hd:
            add_watermark(card_path)
        else:
            free_hd_left -= 1
        room_items_pdf.append((name, card_path, desc))
        att = await upload_photo_to_messages(api, peer_id, png_bytes(card_path), group_id=group_id)
        if att:
            attachments.append(att)
        await asyncio.sleep(0.4)

    pdf_path = out_dir / "project.pdf"
    include_pdf = tier in ("pro", "full") or is_full
    msg_lines = ["✅ Проект готов!\n"]

    if tier == "full":
        storage.consume_project_payment(user_id, project_id)
    elif tier == "free":
        storage.mark_free_trial_used(user_id)
        msg_lines.append("🎁 Бесплатный пробный: 1 комната в HD, остальные с watermark.")
        msg_lines.append("Для полного проекта и PDF — оплатите тариф ниже.")
    elif tier == "pro":
        storage.increment_pro_project(user_id)
        include_pdf = True
        msg_lines.append("⭐ PRO: полный проект без ограничений.")
    elif tier == "preview":
        msg_lines.append("Пробный период использован. Полный результат — по тарифу.")
    else:
        include_pdf = True

    if include_pdf and room_items_pdf:
        build_pdf(plan_path, room_items_pdf, pdf_path, title=f"ПланДом — {brief.project_type.value}")
        pdf_att = await upload_doc_to_messages(
            api, peer_id, pdf_path.read_bytes(), "plandom-project.pdf", group_id=group_id
        )
        if pdf_att:
            attachments.append(pdf_att)
            msg_lines.append("📄 PDF прикреплён к сообщению.")
    elif not include_pdf:
        msg_lines.append("📄 PDF доступен после оплаты полного проекта.")

    storage.update_project(project_id, status="done", tier=tier)
    storage.clear_wizard(user_id)

    params: dict = {
        "peer_id": peer_id,
        "message": "\n".join(msg_lines),
        "random_id": random.randint(1, 2_000_000_000),
    }
    if attachments:
        params["attachment"] = ",".join(attachments)
    if tier in ("free", "preview"):
        pay_type = (
            "project_house" if brief.project_type == ProjectType.HOUSE else "project_apartment"
        )
        params["keyboard"] = keyboards.pay_keyboard(project_id, pay_type)
    await api.request("messages.send", params)


def setup_handlers(bot, storage: Storage, grok: GrokClient, cfg: dict) -> None:
    api = bot.api
    group_id = int(cfg["vk_group_id"])
    yookassa = cfg.get("yookassa_client")
    payments_ok = yookassa is not None
    admin_ids = list(cfg.get("admin_ids") or [])

    async def admin_send(peer_id: int, text: str, keyboard: str | None = None) -> None:
        await _send(api, peer_id, text, keyboard)

    @bot.on.message()
    async def on_message(message: Message) -> None:
        user_id = str(message.from_id)
        peer_id = message.peer_id
        text = (message.text or "").strip()
        storage.ensure_user(user_id)

        async def send(text_msg: str, keyboard: str | None = None) -> None:
            await admin_send(peer_id, text_msg, keyboard)

        if await handle_admin_text_command(storage, admin_ids, user_id, text, send, api):
            return
        if await handle_admin_waiting_input(storage, admin_ids, user_id, text, send, api):
            return

        if text.lower() in {"/start", "начать", "старт", "привет"}:
            storage.set_wizard(user_id, "type", {})
            await send(
                WELCOME.replace("**", ""),
                keyboard=keyboards.main_keyboard(is_admin=is_vk_admin(user_id, admin_ids)),
            )
            await send("Выберите тип объекта:", keyboard=keyboards.type_keyboard())
            return

        if text == "🏠 Новый проект":
            storage.set_wizard(user_id, "type", {})
            await send("Выберите тип объекта:", keyboard=keyboards.type_keyboard())
            return

        if text == "📊 Мой статус":
            user = storage.get_user(user_id)
            pro = storage.is_pro(user_id)
            remaining = storage.pro_projects_remaining(user_id) if pro else 0
            free_used = bool(user.get("free_trial_used"))
            exp = user.get("subscription_expires_at")
            exp_s = ""
            if pro and exp:
                try:
                    exp_s = datetime.fromisoformat(exp).strftime("%d.%m.%Y")
                except ValueError:
                    pass
            lines = [
                "📊 Ваш статус\n",
                f"Подписка: {'PRO до ' + exp_s if pro else 'Free'}",
                f"PRO-проектов в месяц: {remaining}/3" if pro else "",
                f"Бесплатный пробный: {'использован' if free_used else 'доступен'}",
            ]
            await send(
                "\n".join(x for x in lines if x),
                keyboard=keyboards.status_keyboard(pro, payments_ok),
            )
            return

        if text == "💳 Тарифы":
            lines = [
                "💳 Тарифы ПланДом\n",
                f"• Квартира (полный проект): {PRICES['project_apartment']:.0f} ₽",
                f"• Дом: {PRICES['project_house']:.0f} ₽",
                f"• PRO: {PRICES['subscription']:.0f} ₽/мес (3 проекта)",
                f"• Доп. стиль/комната: {PRICES['addon_style']:.0f} ₽",
            ]
            await send("\n".join(lines), keyboard=keyboards.tariffs_keyboard(payments_ok))
            return

        if text == "🔧 Админ панель":
            async def send_adm(t: str, kb: str | None = None) -> None:
                await admin_send(peer_id, t, kb)

            from vk.admin import show_admin_menu

            await show_admin_menu(send_adm, admin_user_id=user_id)
            return

        if text == "❓ Помощь":
            await send(
                "ПланДом помогает спланировать квартиру или дом и показать обстановку по комнатам.\n\n"
                "1. «Новый проект» → wizard\n"
                "2. Получите PNG в чат\n"
                "3. PDF — в полном тарифе или PRO\n\n"
                "Вопросы: напишите администратору сообщества.",
                keyboard=keyboards.main_keyboard(is_admin=is_vk_admin(user_id, admin_ids)),
            )
            return

        step, data = storage.get_wizard(user_id)
        if step == "area_input":
            try:
                data["total_area_m2"] = float(text.replace(",", "."))
            except ValueError:
                await send("Введите число, например 65")
                return
            storage.set_wizard(user_id, "rooms", data)
            await send(
                "Отметьте комнаты (можно несколько):",
                keyboard=keyboards.rooms_keyboard(set()),
            )
            return

        if step == "single_room_name":
            data.setdefault("rooms", [])
            data["rooms"] = [{"name": text[:40], "room_type": "other"}]
            storage.set_wizard(user_id, "style", data)
            await send("Выберите стиль:", keyboard=keyboards.style_keyboard())
            return

        await send("Используйте меню 👇", keyboard=keyboards.main_keyboard(is_admin=is_vk_admin(user_id, admin_ids)))

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, dataclass=MessageEvent)
    async def on_callback(event: MessageEvent) -> None:
        payload_raw = event.object.payload
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                payload = {}
        else:
            payload = payload_raw or {}
        cmd = payload.get("cmd")
        user_id = str(event.object.user_id)
        peer_id = event.peer_id
        storage.ensure_user(user_id)

        async def ack():
            try:
                await bot.api.request(
                    "messages.sendMessageEventAnswer",
                    {
                        "event_id": event.object.event_id,
                        "user_id": event.object.user_id,
                        "peer_id": peer_id,
                    },
                )
            except Exception:
                pass

        step, data = storage.get_wizard(user_id)

        async def send_cb(text_msg: str, keyboard: str | None = None) -> None:
            await _send(api, peer_id, text_msg, keyboard)

        if is_vk_admin(user_id, admin_ids) and cmd and (
            cmd == "admin" or str(cmd).startswith("admin_")
        ):
            await ack()
            await handle_admin_callback(storage, admin_ids, user_id, payload, send_cb, api)
            return

        if cmd == "menu":
            await ack()
            await _send(
                api,
                peer_id,
                "Главное меню:",
                keyboards.main_keyboard(is_admin=is_vk_admin(user_id, admin_ids)),
            )
            return

        if cmd == "new_project":
            await ack()
            storage.set_wizard(user_id, "type", {})
            await _send(api, peer_id, "Выберите тип объекта:", keyboards.type_keyboard())
            return

        if cmd == "type":
            await ack()
            ptype = payload.get("value", "apartment")
            data["project_type"] = ptype
            if ptype == "single_room":
                data["rooms"] = [{"name": "Комната", "room_type": "other"}]
                storage.set_wizard(user_id, "single_room_name", data)
                await _send(api, peer_id, "Как называется комната? (напишите текстом)")
            elif ptype == "house":
                data["floors"] = 2
                storage.set_wizard(user_id, "area", data)
                await _send(api, peer_id, "Примерная площадь дома:", keyboards.area_keyboard())
            else:
                storage.set_wizard(user_id, "area", data)
                await _send(api, peer_id, "Примерная площадь квартиры:", keyboards.area_keyboard())
            return

        if cmd == "area":
            await ack()
            val = payload.get("value")
            if val != "skip":
                try:
                    data["total_area_m2"] = float(val)
                except (TypeError, ValueError):
                    pass
            storage.set_wizard(user_id, "rooms", data)
            await _send(api, peer_id, "Отметьте комнаты:", keyboards.rooms_keyboard(set()))
            return

        if cmd == "room_toggle":
            await ack()
            key = payload.get("value", "")
            selected = set(data.get("selected_rooms") or [])
            if key in selected:
                selected.remove(key)
            else:
                selected.add(key)
            data["selected_rooms"] = list(selected)
            storage.set_wizard(user_id, "rooms", data)
            await _send(api, peer_id, "Отметьте комнаты:", keyboards.rooms_keyboard(selected))
            return

        if cmd == "rooms_done":
            await ack()
            selected = data.get("selected_rooms") or []
            if not selected:
                await _send(api, peer_id, "Выберите хотя бы одну комнату.", keyboards.rooms_keyboard(set()))
                return
            data["rooms"] = [
                {"name": ROOM_NAMES.get(k, k), "room_type": k} for k in selected
            ]
            storage.set_wizard(user_id, "style", data)
            await _send(api, peer_id, "Выберите стиль:", keyboards.style_keyboard())
            return

        if cmd == "style":
            await ack()
            data["style"] = payload.get("value", "scandinavian")
            storage.set_wizard(user_id, "budget", data)
            await _send(api, peer_id, "Бюджет на обстановку:", keyboards.budget_keyboard())
            return

        if cmd == "budget":
            await ack()
            data["budget_tier"] = payload.get("value", "medium")
            storage.set_wizard(user_id, "confirm", data)
            await _send(api, peer_id, _summary(data), keyboards.confirm_keyboard())
            return

        if cmd == "restart":
            await ack()
            storage.set_wizard(user_id, "type", {})
            await _send(api, peer_id, "Выберите тип:", keyboards.type_keyboard())
            return

        if cmd == "generate":
            await ack()
            await _run_generation(api, storage, grok, cfg, user_id, peer_id, data)
            return

        if cmd == "pay":
            await ack()
            if not yookassa:
                await _send(api, peer_id, "Оплата временно недоступна.")
                return
            kind = payload.get("kind", "project_apartment")
            project_id = payload.get("project_id")
            try:
                payment = await create_plandom_payment(
                    yookassa_client=yookassa,
                    storage=storage,
                    user_id=user_id,
                    group_id=group_id,
                    payment_kind=kind if kind != "subscription_year" else "subscription_year",
                    project_id=project_id,
                )
            except Exception as exc:
                LOGGER.exception("Payment create failed: %s", exc)
                await _send(api, peer_id, "Не удалось создать платёж. Попробуйте позже.")
                return
            if not payment:
                await _send(api, peer_id, "Оплата недоступна.")
                return
            url = (payment.get("confirmation") or {}).get("confirmation_url", "")
            amount = PRICES.get(kind, 0)
            await _send(
                api,
                peer_id,
                f"💳 Сумма: {amount:.0f} ₽\nПосле оплаты результат обновится автоматически.",
                pay_link_keyboard(url),
            )
            return

        await ack()
