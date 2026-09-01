"""ЮKassa — копия паттерна Agrobotik."""
from __future__ import annotations

import os


def build_yookassa_client():
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

    return YooKassaClient(
        shop_id=shop_id,
        secret_key=secret,
        test_mode=test_mode,
    )
