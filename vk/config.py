"""Конфигурация бота VK."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=True)
    except ImportError:
        pass


def get_config() -> dict:
    load_env()
    token = (os.getenv("VK_BOT_TOKEN") or "").strip()
    group_id_raw = (os.getenv("VK_GROUP_ID") or "").strip()
    if not token or not group_id_raw:
        raise RuntimeError("VK_BOT_TOKEN и VK_GROUP_ID обязательны в .env")
    admin_ids = [
        x.strip()
        for x in (os.getenv("VK_ADMIN_IDS") or "").split(",")
        if x.strip()
    ]
    from vk.payments import build_yookassa_client

    return {
        "vk_token": token,
        "vk_group_id": int(group_id_raw),
        "admin_ids": admin_ids,
        "db_path": REPO_ROOT / "planirovka.db",
        "database_url": (os.getenv("DATABASE_URL") or "").strip() or None,
        "yookassa_client": build_yookassa_client(),
        "grok_api_key": (os.getenv("GROK_API_KEY") or "").strip(),
    }
