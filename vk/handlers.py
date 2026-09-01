"""Обработчики VK-бота ПланДом."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from vk.http_fix import patch_vkbottle_pydantic

patch_vkbottle_pydantic()

from vkbottle import GroupEventType
from vkbottle.bot import Message, MessageEvent

from core.image_gen import render_room_card
from core.models import ProjectType, RoomSpec, RoomType
from core.planner import brief_from_wizard, build_layout
from core.room_render import render_room_images, views_for_tier
from core.render import add_watermark, build_pdf, layout_to_png, png_bytes
from core.image_normalize import normalize_image_bytes
from core.dimensions import parse_area_value
from core.blueprint_service import recognize_blueprint_files
from grok_client import GrokClient
from storage import Storage
from vk import keyboards
from vk.attachments import save_message_attachments
from vk.media import upload_doc_to_messages, upload_image_to_messages
from vk.progress import GenerationProgress
from vk.wizard_flow import (
    apply_blueprint_to_wizard,
    blueprint_review_summary,
    check_area_mismatch,
    parse_room_sizes_step,
    wizard_summary,
)
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
WIZARD_UPLOAD_ROOT = OUTPUT_ROOT / "wizard"

WELCOME = (
    "🏠 **ПланДом** — AI-планировка и фотореалистичный дизайн комнат.\n\n"
    "Бесплатно: план + 1 комната в HD (2 ракурса).\n"
    "Можно загрузить чертёж или ввести размеры вручную.\n\n"
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
    return wizard_summary(data)


async def _parse_blueprints(
    grok: GrokClient,
    user_id: str,
    data: dict,
) -> dict:
    pending = data.get("blueprint_pending_files") or []
    paths = [Path(p) for p in pending if Path(p).is_file()]
    if not paths:
        upload_dir = WIZARD_UPLOAD_ROOT / user_id
        paths = sorted(upload_dir.glob("*")) if upload_dir.is_dir() else []
    parsed = await recognize_blueprint_files(grok, paths)
    parsed["blueprint_files"] = [str(p) for p in paths]
    return apply_blueprint_to_wizard(data, parsed)


async def _send_attachment(
    api,
    peer_id: int,
    text: str,
    attachment: str,
    *,
    keyboard: str | None = None,
) -> None:
    params: dict = {
        "peer_id": int(peer_id),
        "message": text,
        "attachment": attachment,
        "random_id": random.randint(1, 2_000_000_000),
    }
    if keyboard:
        params["keyboard"] = keyboard
    await api.request("messages.send", params)


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

    progress = GenerationProgress(api, peer_id, group_id)
    await progress.start("⏳ Строю планировку", activity="typing")
    upload_warnings: list[str] = []
    pdf_att: str | None = None
    pdf_path = out_dir / "project.pdf"

    try:
        layout = await build_layout(brief, grok)
        if brief.total_area_m2:
            layout["total_area_m2"] = brief.total_area_m2
        storage.update_project(project_id, layout=layout)

        plan_path = layout_to_png(
            layout,
            out_dir / "plan.png",
            estimated=bool(data.get("blueprint_estimated")),
        )

        await progress.set_phase("📤 Загружаю план", activity="upload")
        plan_att = await upload_image_to_messages(
            api,
            peer_id,
            normalize_image_bytes(png_bytes(plan_path)),
            group_id=group_id,
            doc_title="plan.jpg",
        )
        if plan_att:
            await _send_attachment(api, peer_id, "📐 Планировка квартиры", plan_att)
        else:
            upload_warnings.append("⚠️ Не удалось загрузить план в VK")

        is_full = tier in ("pro", "full")
        room_items_pdf: list[tuple[str, Path, str]] = []
        brief_dict = brief.to_dict()
        design_palette = f"{brief.style} {brief.style_notes or ''}, budget {brief.budget_tier}".strip()
        rooms = layout.get("rooms") or []
        total_rooms = len(rooms)

        await progress.set_phase("✍️ Описываю комнаты", activity="typing")
        descriptions = list(
            await asyncio.gather(*[grok.describe_room(room, brief_dict) for room in rooms])
        )

        for i, room in enumerate(rooms):
            name = room.get("name") or f"Комната {i + 1}"
            desc = descriptions[i] if i < len(descriptions) else ""
            hd_room = tier in ("pro", "full") or (tier == "free" and i == 0)
            room_views = views_for_tier(tier, room_index=i, is_hd=hd_room)

            await progress.set_phase(
                f"🎨 {name} ({i + 1}/{total_rooms}): генерирую интерьер",
                activity="image",
            )
            await _send(
                api,
                peer_id,
                f"📍 {name} ({i + 1}/{total_rooms}) — {len(room_views)} "
                f"{'ракурс' if len(room_views) == 1 else 'ракурса'} одного интерьера",
            )

            labeled_images = await render_room_images(
                grok,
                room,
                brief_dict,
                desc,
                out_dir,
                i + 1,
                views=room_views,
                design_palette=design_palette,
            )
            room_uploaded = 0
            for card_path, caption in labeled_images:
                if not hd_room:
                    add_watermark(card_path)
                await progress.set_phase(
                    f"📤 {name}: загружаю фото ({room_uploaded + 1}/{len(labeled_images)})",
                    activity="upload",
                )
                att = await upload_image_to_messages(
                    api,
                    peer_id,
                    png_bytes(card_path),
                    group_id=group_id,
                    doc_title=card_path.name,
                )
                if att:
                    await _send_attachment(api, peer_id, caption, att)
                    room_uploaded += 1
                else:
                    LOGGER.warning("VK upload failed: room=%s file=%s", name, card_path.name)
                await asyncio.sleep(0.8)
            if labeled_images:
                room_items_pdf.append((name, labeled_images[0][0], desc))
            if labeled_images and room_uploaded == 0:
                upload_warnings.append(f"⚠️ Не удалось загрузить фото: {name}")

        include_pdf = tier in ("pro", "full") or is_full
        msg_lines = ["✅ Проект готов!\n"]
        room_names = [
            r.get("name") or f"Комната {j + 1}"
            for j, r in enumerate(rooms)
        ]
        if room_names:
            msg_lines.append("Комнаты: " + ", ".join(room_names))
        msg_lines.append(
            "К каждому фото — подпись с названием комнаты и номером ракурса."
        )
        msg_lines.extend(upload_warnings)

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
            await asyncio.sleep(2)
            build_pdf(plan_path, room_items_pdf, pdf_path, title=f"ПланДом — {brief.project_type.value}")
            pdf_att = await upload_doc_to_messages(
                api, peer_id, pdf_path.read_bytes(), "plandom-project.pdf", group_id=group_id
            )
            if pdf_att:
                msg_lines.append("📄 PDF прикреплён к сообщению.")
            else:
                upload_warnings.append("⚠️ Не удалось загрузить PDF в VK")
        elif not include_pdf:
            msg_lines.append("📄 PDF доступен после оплаты полного проекта.")

        storage.update_project(project_id, status="done", tier=tier)
        storage.clear_wizard(user_id)

        params: dict = {
            "peer_id": peer_id,
            "message": "\n".join(msg_lines),
            "random_id": random.randint(1, 2_000_000_000),
        }
        if pdf_att:
            params["attachment"] = pdf_att
        if tier in ("free", "preview"):
            pay_type = (
                "project_house" if brief.project_type == ProjectType.HOUSE else "project_apartment"
            )
            params["keyboard"] = keyboards.pay_keyboard(project_id, pay_type)
        await api.request("messages.send", params)
    finally:
        await progress.stop()


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
                "ПланДом: планировка + фотореалистичный дизайн комнат.\n\n"
                "1. «Новый проект» → чертёж или размеры вручную\n"
                "2. Укажите комнаты, стиль, пожелания\n"
                "3. Получите план с размерами и 2 ракурса на комнату\n"
                "4. PDF — в полном тарифе или PRO (3 варианта)\n\n"
                "Вопросы: напишите администратору сообщества.",
                keyboard=keyboards.main_keyboard(is_admin=is_vk_admin(user_id, admin_ids)),
            )
            return

        step, data = storage.get_wizard(user_id)

        if step == "blueprint_upload":
            upload_dir = WIZARD_UPLOAD_ROOT / user_id
            saved = await save_message_attachments(message, upload_dir)
            if saved:
                pending = list(data.get("blueprint_pending_files") or [])
                pending.extend(str(p) for p in saved)
                data["blueprint_pending_files"] = pending
                storage.set_wizard(user_id, "blueprint_upload", data)
                await send(
                    f"📎 Файлов: {len(pending)}. Можно прислать ещё (другой этаж) "
                    "или нажмите «Готово, распознать».",
                    keyboard=keyboards.blueprint_upload_keyboard(),
                )
                return
            if text:
                await send(
                    "Пришлите фото/PDF/SVG/DXF чертежа или нажмите «Готово».",
                    keyboard=keyboards.blueprint_upload_keyboard(),
                )
                return

        if step == "area_input":
            val = parse_area_value(text)
            if val is None:
                await send("Введите площадь, например 65 или 8.5×12")
                return
            data["total_area_m2"] = val
            storage.set_wizard(user_id, "rooms", data)
            await send("Отметьте комнаты:", keyboard=keyboards.rooms_keyboard(set()))
            return

        if step == "area_dims_input":
            val = parse_area_value(text)
            if val is None:
                await send("Введите ширину×длину, например 8.5×12")
                return
            data["total_area_m2"] = val
            storage.set_wizard(user_id, "rooms", data)
            await send("Отметьте комнаты:", keyboard=keyboards.rooms_keyboard(set()))
            return

        if step == "room_dims":
            data = parse_room_sizes_step(data, text)
            storage.set_wizard(user_id, "details", data)
            await send(
                "Дополнительно (одним сообщением или «пропустить»):\n"
                "• высота потолка (м)\n"
                "• окна и двери (где)\n"
                "• мокрые зоны\n"
                "Пример: потолок 2.7; окно в гостиной на юг; стояк в ванной",
                keyboard=keyboards.skip_keyboard("skip_details"),
            )
            return

        if step == "details":
            if text.lower() not in {"пропустить", "skip", "-"}:
                parts = text.split(";")
                for part in parts:
                    p = part.strip().lower()
                    if "потол" in p:
                        num = parse_area_value(part.split()[-1]) or parse_area_value(part)
                        if num and num < 10:
                            data["ceiling_height_m"] = num
                    elif "мокр" in p or "стояк" in p or "ванн" in p:
                        data["wet_zones"] = part.strip()
                    elif "окн" in p or "двер" in p:
                        data["openings_notes"] = (data.get("openings_notes", "") + "; " + part.strip()).strip("; ")
            storage.set_wizard(user_id, "style", data)
            await send("Выберите стиль:", keyboard=keyboards.style_keyboard())
            return

        if step == "style_notes":
            if text.lower() not in {"пропустить", "skip", "-"}:
                data["style_notes"] = text[:300]
            storage.set_wizard(user_id, "budget", data)
            await send("Бюджет на обстановку:", keyboard=keyboards.budget_keyboard())
            return

        if step == "furniture":
            if text.lower() not in {"пропустить", "skip", "-"}:
                data["furniture_wishes"] = text[:500]
            ok, msg = check_area_mismatch(data)
            if not ok:
                storage.set_wizard(user_id, "area_fix", data)
                await send(msg, keyboard=keyboards.area_fix_keyboard())
                return
            storage.set_wizard(user_id, "confirm", data)
            await send(_summary(data), keyboard=keyboards.confirm_keyboard())
            return

        if step == "area_fix_total":
            val = parse_area_value(text)
            if val is None:
                await send("Введите площадь, например 67.4")
                return
            data["total_area_m2"] = val
            ok, msg = check_area_mismatch(data)
            if not ok:
                storage.set_wizard(user_id, "area_fix", data)
                await send(msg, keyboard=keyboards.area_fix_keyboard())
                return
            storage.set_wizard(user_id, "confirm", data)
            await send(_summary(data), keyboard=keyboards.confirm_keyboard())
            return

        if step == "area_fix_rooms":
            data = parse_room_sizes_step(data, text)
            ok, msg = check_area_mismatch(data)
            if not ok:
                storage.set_wizard(user_id, "area_fix", data)
                await send(msg, keyboard=keyboards.area_fix_keyboard())
                return
            storage.set_wizard(user_id, "confirm", data)
            await send(_summary(data), keyboard=keyboards.confirm_keyboard())
            return

        if step == "bp_edit_area":
            val = parse_area_value(text)
            if val is None:
                await send("Введите площадь в м²")
                return
            data["total_area_m2"] = val
            storage.set_wizard(user_id, "blueprint_review", data)
            await send(blueprint_review_summary(data), keyboard=keyboards.blueprint_review_keyboard())
            return

        if step == "bp_edit_rooms":
            data = parse_room_sizes_step(data, text)
            storage.set_wizard(user_id, "blueprint_review", data)
            await send(blueprint_review_summary(data), keyboard=keyboards.blueprint_review_keyboard())
            return

        if step == "bp_edit_details":
            if text.lower() not in {"пропустить", "skip"}:
                data["openings_notes"] = text[:300]
            storage.set_wizard(user_id, "blueprint_review", data)
            await send(blueprint_review_summary(data), keyboard=keyboards.blueprint_review_keyboard())
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
            else:
                if ptype == "house":
                    data["floors"] = 2
                storage.set_wizard(user_id, "input_source", data)
                await _send(
                    api,
                    peer_id,
                    "Есть чертёж квартиры/дома или введёте размеры вручную?",
                    keyboards.input_source_keyboard(),
                )
            return

        if cmd == "input_source":
            await ack()
            mode = payload.get("value", "manual")
            if mode == "blueprint":
                data["input_mode"] = "blueprint"
                data["blueprint_pending_files"] = []
                upload_dir = WIZARD_UPLOAD_ROOT / user_id
                if upload_dir.is_dir():
                    for f in upload_dir.iterdir():
                        f.unlink(missing_ok=True)
                storage.set_wizard(user_id, "blueprint_upload", data)
                await _send(
                    api,
                    peer_id,
                    "📎 Пришлите чертёж: фото, PDF, PNG, SVG, DXF и др.\n"
                    "Можно несколько файлов (по этажам). Затем «Готово, распознать».",
                    keyboards.blueprint_upload_keyboard(),
                )
            else:
                data["input_mode"] = "manual"
                storage.set_wizard(user_id, "area", data)
                label = "дома" if data.get("project_type") == "house" else "квартиры"
                await _send(api, peer_id, f"Площадь {label}:", keyboards.area_keyboard())
            return

        if cmd == "blueprint_more":
            await ack()
            await _send(
                api,
                peer_id,
                "Пришлите следующий файл (этаж) в чат.",
                keyboards.blueprint_upload_keyboard(),
            )
            return

        if cmd == "blueprint_parse":
            await ack()
            await _send(api, peer_id, "⏳ Распознаю чертёж…")
            try:
                data = await _parse_blueprints(grok, user_id, data)
            except Exception as exc:
                LOGGER.exception("Blueprint parse: %s", exc)
                await _send(api, peer_id, f"Не удалось распознать: {exc}")
                return
            if not data.get("rooms"):
                await _send(
                    api,
                    peer_id,
                    "Комнаты не найдены. Пришлите более чёткий чертёж или введите вручную.",
                    keyboards.input_source_keyboard(),
                )
                return
            storage.set_wizard(user_id, "blueprint_review", data)
            await _send(api, peer_id, blueprint_review_summary(data), keyboards.blueprint_review_keyboard())
            return

        if cmd == "blueprint_confirm":
            await ack()
            storage.set_wizard(user_id, "style", data)
            await _send(api, peer_id, "Выберите стиль интерьера:", keyboards.style_keyboard())
            return

        if cmd == "bp_edit":
            await ack()
            field = payload.get("field", "area")
            if field == "area":
                storage.set_wizard(user_id, "bp_edit_area", data)
                await _send(api, peer_id, "Введите площадь в м² (число или Ш×Д):")
            elif field == "rooms":
                storage.set_wizard(user_id, "bp_edit_rooms", data)
                rooms = ", ".join(r.get("name", "?") for r in data.get("rooms") or [])
                await _send(
                    api,
                    peer_id,
                    f"Укажите размеры комнат (по строке):\n{rooms}\n"
                    "Пример:\nСпальня 3.2x4.5\nКухня 12",
                )
            else:
                storage.set_wizard(user_id, "bp_edit_details", data)
                await _send(api, peer_id, "Опишите потолок, окна, двери, мокрые зоны:")
            return

        if cmd == "area_mode":
            await ack()
            mode = payload.get("value", "custom")
            if mode == "dims":
                storage.set_wizard(user_id, "area_dims_input", data)
                await _send(api, peer_id, "Введите ширину×длину в метрах, например 8.5×12")
            else:
                storage.set_wizard(user_id, "area_input", data)
                await _send(api, peer_id, "Введите площадь в м², например 67.4")
            return

        if cmd == "skip_details":
            await ack()
            storage.set_wizard(user_id, "style", data)
            await _send(api, peer_id, "Выберите стиль:", keyboards.style_keyboard())
            return

        if cmd == "skip_step":
            await ack()
            storage.set_wizard(user_id, "confirm", data)
            await _send(api, peer_id, _summary(data), keyboards.confirm_keyboard())
            return

        if cmd == "style_custom":
            await ack()
            storage.set_wizard(user_id, "style_notes", data)
            await _send(api, peer_id, "Опишите желаемый стиль своими словами (или «пропустить»):")
            return

        if cmd == "area_fix":
            await ack()
            target = payload.get("target", "total")
            if target == "rooms":
                storage.set_wizard(user_id, "area_fix_rooms", data)
                await _send(
                    api,
                    peer_id,
                    "Укажите размеры комнат построчно, например:\nСпальня 3.2x4.5\nКухня 12",
                )
            else:
                storage.set_wizard(user_id, "area_fix_total", data)
                await _send(api, peer_id, "Введите правильную общую площадь в м²:")
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
            storage.set_wizard(user_id, "room_dims", data)
            rooms = ", ".join(r["name"] for r in data["rooms"])
            await _send(
                api,
                peer_id,
                f"Размеры комнат (необязательно).\n{rooms}\n"
                "Построчно: «Спальня 3.2x4.5» или «Кухня 12 м²».\n"
                "Или нажмите «Пропустить».",
                keyboards.skip_keyboard("skip_room_dims"),
            )
            return

        if cmd == "skip_room_dims":
            await ack()
            storage.set_wizard(user_id, "details", data)
            await _send(
                api,
                peer_id,
                "Дополнительно (потолок, окна, двери, мокрые зоны) — текстом или «пропустить»:",
                keyboards.skip_keyboard("skip_details"),
            )
            return

        if cmd == "style":
            await ack()
            data["style"] = payload.get("value", "scandinavian")
            storage.set_wizard(user_id, "style_notes", data)
            await _send(
                api,
                peer_id,
                "Уточните стиль текстом (необязательно) или «пропустить»:",
                keyboards.skip_keyboard("skip_style_notes"),
            )
            return

        if cmd == "skip_style_notes":
            await ack()
            storage.set_wizard(user_id, "budget", data)
            await _send(api, peer_id, "Бюджет на обстановку:", keyboards.budget_keyboard())
            return

        if cmd == "budget":
            await ack()
            data["budget_tier"] = payload.get("value", "medium")
            storage.set_wizard(user_id, "furniture", data)
            await _send(
                api,
                peer_id,
                "Пожелания по мебели и расстановке (необязательно):\n"
                "Например: «кровать у окна, без ТВ».\n"
                "Или «пропустить».",
                keyboards.skip_keyboard("skip_furniture"),
            )
            return

        if cmd == "skip_furniture":
            await ack()
            ok, msg = check_area_mismatch(data)
            if not ok:
                storage.set_wizard(user_id, "area_fix", data)
                await _send(api, peer_id, msg, keyboards.area_fix_keyboard())
                return
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

            async def _safe_gen() -> None:
                try:
                    await _run_generation(api, storage, grok, cfg, user_id, peer_id, data)
                except Exception as exc:
                    LOGGER.exception("Generation failed: %s", exc)
                    await _send(api, peer_id, f"❌ Ошибка генерации: {exc}")

            asyncio.create_task(_safe_gen())
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
