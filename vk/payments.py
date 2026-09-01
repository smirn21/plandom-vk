"""Платежи ЮKassa для ПланДом."""
from __future__ import annotations

import json
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

PRICES: dict[str, float] = {
    "project_apartment": 399.0,
    "project_house": 799.0,
    "addon_style": 99.0,
    "subscription": 399.0,
    "subscription_year": 3990.0,
}

PAYMENT_LABELS = {
    "project_apartment": "ПланДом — полный проект квартиры",
    "project_house": "ПланДом — полный проект дома",
    "addon_style": "ПланДом — доп. стиль/комната",
    "subscription": "ПланДом PRO — 1 месяц",
    "subscription_year": "ПланДом PRO — 1 год",
}


def build_yookassa_client():
    import os

    shop_id = (os.getenv("YOOKASSA_SHOP_ID") or "").strip()
    secret = (os.getenv("YOOKASSA_SECRET_KEY") or "").strip()
    if not shop_id or not secret:
        return None
    test_mode = (os.getenv("YOOKASSA_TEST_MODE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    from yookassa_client import YooKassaClient

    return YooKassaClient(shop_id=shop_id, secret_key=secret, test_mode=test_mode)


def pay_link_keyboard(url: str) -> str:
    return json.dumps(
        {
            "inline": True,
            "buttons": [[{"action": {"type": "open_link", "label": "💳 Оплатить", "link": url}}]],
        },
        ensure_ascii=False,
    )


async def create_plandom_payment(
    *,
    yookassa_client: Any,
    storage: Any,
    user_id: str,
    group_id: int,
    payment_kind: str,
    project_id: str | None = None,
) -> dict[str, Any] | None:
    if not yookassa_client:
        return None
    amount = PRICES.get(payment_kind)
    if amount is None:
        return None
    description = PAYMENT_LABELS.get(payment_kind, "ПланДом")
    return_url = f"https://vk.com/write-{group_id}"
    subscription_type = None
    payment_type = payment_kind
    if payment_kind == "subscription":
        subscription_type = "month"
    elif payment_kind == "subscription_year":
        payment_type = "subscription"
        subscription_type = "year"

    payment = await yookassa_client.create_payment(
        amount=amount,
        description=description,
        return_url=return_url,
        user_id=str(user_id),
        payment_type=payment_type,
        subscription_type=subscription_type,
        project_id=project_id,
    )
    storage.create_payment(
        payment_id=payment["id"],
        user_id=str(user_id),
        amount=amount,
        payment_type=payment_kind if payment_kind != "subscription_year" else "subscription",
        subscription_type=subscription_type,
        project_id=project_id,
    )
    return payment
