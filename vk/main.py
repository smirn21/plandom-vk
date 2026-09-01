"""
Точка входа VK-бота «ПланДом».

    ./vk/run.sh
"""
from __future__ import annotations

import asyncio
import logging
import random
import ssl
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

from vk.http_fix import patch_vkbottle_pydantic  # noqa: E402

patch_vkbottle_pydantic()


async def _build_api(token: str):
    import aiohttp
    import certifi
    from vkbottle import API
    from vkbottle.http import AiohttpClient

    from vk.http_fix import LimitedRequestRescheduler

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    timeout = aiohttp.ClientTimeout(total=25, connect=10, sock_read=20)
    connector = aiohttp.TCPConnector(ssl=ssl_ctx, limit=20)
    session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    api = API(
        token,
        http_client=AiohttpClient(session=session),
        request_rescheduler=LimitedRequestRescheduler(delay=1.5, max_attempts=3),
    )
    return api, session


async def _notify_vk(api, user_id: str, text: str) -> bool:
    try:
        peer_id = int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        await api.request(
            "messages.send",
            {
                "peer_id": peer_id,
                "message": text,
                "random_id": random.randint(1, 2_000_000_000),
            },
        )
        return True
    except Exception as exc:
        logger.warning("Notify failed %s: %s", user_id, exc)
        return False


async def _check_pending_payments(api, storage, yookassa_client) -> None:
    while True:
        try:
            if yookassa_client:
                for payment_id, user_id in storage.get_pending_payments(limit=50):
                    try:
                        info = await yookassa_client.get_payment(payment_id)
                        status = info.get("status")
                        row = storage.get_payment_by_id(payment_id)
                        if not row or row["status"] == status:
                            continue
                        if status != "succeeded":
                            storage.update_payment_status(payment_id, status)
                            continue
                        storage.update_payment_status(payment_id, "succeeded", datetime.now().isoformat())
                        ptype = row["payment_type"]
                        project_id = row.get("project_id")

                        if ptype == "subscription":
                            sub_type = row.get("subscription_type") or "month"
                            days = 365 if sub_type == "year" else 30
                            expires = (datetime.now() + timedelta(days=days)).isoformat()
                            storage.set_subscription(user_id, "pro", expires, sub_type)
                            exp_str = datetime.fromisoformat(expires).strftime("%d.%m.%Y")
                            await _notify_vk(
                                api,
                                user_id,
                                f"✅ PRO активирован до {exp_str}.\n"
                                f"3 полных проекта в месяц + PDF без watermark.",
                            )
                        elif ptype in ("project_apartment", "project_house", "addon_style"):
                            if project_id:
                                storage.update_project(
                                    project_id, tier="full", is_paid=True, status="paid"
                                )
                            await _notify_vk(
                                api,
                                user_id,
                                "✅ Оплата прошла!\n"
                                "Запустите «🏠 Новый проект» — полный результат и PDF будут без ограничений.",
                            )
                        else:
                            await _notify_vk(api, user_id, "✅ Платёж успешен!")
                    except Exception as exc:
                        logger.warning("Payment check %s: %s", payment_id, exc)
        except Exception as exc:
            logger.exception("Payment loop: %s", exc)
        await asyncio.sleep(60)


async def _expire_subscriptions_loop(api, storage) -> None:
    await asyncio.sleep(60)
    while True:
        try:
            for uid in storage.expire_subscriptions():
                await _notify_vk(
                    api,
                    uid,
                    "⏰ PRO истёк. Оформите подписку через «💳 Тарифы».",
                )
        except Exception as exc:
            logger.exception("Expire loop: %s", exc)
        await asyncio.sleep(3600)


async def _longpoll_available(api, group_id: int) -> bool:
    try:
        await asyncio.wait_for(
            api.request("groups.getLongPollServer", {"group_id": group_id}),
            timeout=15,
        )
        return True
    except Exception as exc:
        logger.warning("Long Poll unavailable: %s", exc)
        return False


async def _run_bot(cfg: dict) -> None:
    from grok_client import GrokClient
    from storage import create_storage
    from vkbottle import Bot
    from vk import handlers

    storage = create_storage(cfg["db_path"])
    grok = GrokClient(
        api_key=cfg.get("grok_api_key") or "",
        model=cfg.get("grok_model") or "grok-2-latest",
        url=cfg.get("grok_url") or "https://api.x.ai/v1/chat/completions",
    )
    yookassa = cfg.get("yookassa_client")
    api, session = await _build_api(cfg["vk_token"])
    bg: list[asyncio.Task] = []
    try:
        logger.info(
            "ПланДом VK (group=%s, yookassa=%s, grok=%s)",
            cfg["vk_group_id"],
            bool(yookassa),
            grok.available,
        )
        bg.append(asyncio.create_task(_expire_subscriptions_loop(api, storage)))
        if yookassa:
            bg.append(asyncio.create_task(_check_pending_payments(api, storage, yookassa)))
        if await _longpoll_available(api, cfg["vk_group_id"]):
            bot = Bot(api=api)
            handlers.setup_handlers(bot, storage, grok, cfg)
            logger.info("Long Poll started")
            await bot.run_polling()
        else:
            logger.error("Long Poll недоступен — проверьте токен и права сообщества")
    finally:
        for t in bg:
            t.cancel()
        if not session.closed:
            await session.close()


def main() -> None:
    from vk.config import get_config, load_env

    load_env()
    cfg = get_config()
    asyncio.run(_run_bot(cfg))


if __name__ == "__main__":
    main()
