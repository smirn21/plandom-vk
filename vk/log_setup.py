"""Настройка подробного логирования ПланДом."""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

PROJECT_LOGGERS = (
    "vk",
    "core",
    "grok_client",
    "storage",
    "yookassa_client",
)

NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "aiohttp",
    "vkbottle",
    "PIL",
)


def configure_logging() -> None:
    """LOG_LEVEL=DEBUG или PLANDOM_VERBOSE=1 — максимум деталей по шагам."""
    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    root_level = getattr(logging, level_name, logging.INFO)
    verbose = (os.getenv("PLANDOM_VERBOSE") or "").strip().lower() in ("1", "true", "yes", "on")
    project_level = logging.DEBUG if verbose or root_level <= logging.DEBUG else root_level

    logging.basicConfig(
        level=root_level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        force=True,
    )
    for name in PROJECT_LOGGERS:
        logging.getLogger(name).setLevel(project_level)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(
            logging.DEBUG if verbose else logging.WARNING
        )
    logging.getLogger(__name__).info(
        "Logging: root=%s project=%s verbose=%s",
        logging.getLevelName(root_level),
        logging.getLevelName(project_level),
        verbose,
    )


class StepLog:
    """Пошаговый лог с номером шага и временем от старта."""

    def __init__(self, logger: logging.Logger, scope: str) -> None:
        self._log = logger
        self._scope = scope
        self._n = 0
        self._t0 = time.monotonic()

    def _elapsed(self) -> float:
        return time.monotonic() - self._t0

    def step(self, msg: str, *args: object) -> None:
        self._n += 1
        self._log.info(
            "[%s | шаг %d | +%.1fs] " + msg,
            self._scope,
            self._n,
            self._elapsed(),
            *args,
        )

    def debug(self, msg: str, *args: object) -> None:
        self._log.debug("[%s | +%.1fs] " + msg, self._scope, self._elapsed(), *args)

    def warn(self, msg: str, *args: object) -> None:
        self._log.warning("[%s | +%.1fs] " + msg, self._scope, self._elapsed(), *args)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        self.step("▶ Начало: %s", name)
        t = time.monotonic()
        try:
            yield
            self.step("✓ Готово: %s (%.1fs)", name, time.monotonic() - t)
        except Exception:
            self.step("✗ Ошибка: %s (%.1fs)", name, time.monotonic() - t)
            raise
