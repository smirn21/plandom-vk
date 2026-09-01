"""
Точка входа VK-бота «Планировка».
MVP: заглушка — полные handlers после согласования PRODUCT.md.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    from vk.config import get_config

    cfg = get_config()
    logger.info(
        "Планировка VK — scaffold (group_id=%s, yookassa=%s)",
        cfg.get("vk_group_id"),
        "yes" if cfg.get("yookassa_client") else "no",
    )
    logger.info(
        "Реализация бота в ветке feature/mvp. См. docs/PRODUCT.md"
    )
    # TODO: vkbottle Bot + wizard + core planner


if __name__ == "__main__":
    main()
