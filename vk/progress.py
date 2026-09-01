"""Индикатор прогресса генерации в VK (typing + статусное сообщение)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

_ACTIVITY_MAP = {
    "typing": "typing",
    "plan": "typing",
    "image": "photo",
    "upload": "file",
}


class GenerationProgress:
    """Показывает «печатает» / «генерирует фото» и обновляет статус с точками."""

    def __init__(self, api: Any, peer_id: int, group_id: int) -> None:
        self._api = api
        self._peer_id = int(peer_id)
        self._group_id = int(group_id)
        self._label = "⏳ Запуск…"
        self._activity = "typing"
        self._message_id: int | None = None
        self._conversation_message_id: int | None = None
        self._dots = 0
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self, label: str, *, activity: str = "typing") -> None:
        self._label = label
        self._activity = activity
        self._stop.clear()
        LOGGER.info("Progress start peer=%s: %s (activity=%s)", self._peer_id, label, activity)
        await self._send_status()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def set_phase(self, label: str, *, activity: str = "typing") -> None:
        LOGGER.info("Progress phase peer=%s: %s (activity=%s)", self._peer_id, label, activity)
        self._label = label
        self._activity = activity
        await self._send_status()

    async def stop(self) -> None:
        LOGGER.info("Progress stop peer=%s: %s", self._peer_id, self._label)
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._message_id or self._conversation_message_id:
            try:
                await self._edit_status(f"{self._label.rstrip('.')} ✓")
            except Exception:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            await self._set_activity()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=3.0)
                break
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            self._dots = (self._dots + 1) % 4
            try:
                await self._edit_status(self._label + "." * (self._dots + 1))
            except Exception as exc:
                LOGGER.debug("Progress edit failed: %s", exc)

    async def _set_activity(self) -> None:
        activity_type = _ACTIVITY_MAP.get(self._activity, "typing")
        try:
            await self._api.request(
                "messages.setActivity",
                {
                    "peer_id": self._peer_id,
                    "group_id": self._group_id,
                    "type": activity_type,
                },
            )
        except Exception as exc:
            LOGGER.debug("setActivity failed: %s", exc)

    def _status_text(self, label: str | None = None) -> str:
        text = label if label is not None else self._label
        return text + "." * (self._dots + 1)

    async def _send_status(self) -> None:
        import random

        params: dict[str, Any] = {
            "peer_id": self._peer_id,
            "message": self._status_text(),
            "random_id": random.randint(1, 2_000_000_000),
        }
        try:
            resp = await self._api.request("messages.send", params)
            mid, cmid = _extract_message_ids(resp)
            if mid:
                self._message_id = mid
            if cmid:
                self._conversation_message_id = cmid
        except Exception as exc:
            LOGGER.debug("Progress send failed: %s", exc)

    async def _edit_status(self, text: str) -> None:
        if not self._message_id and not self._conversation_message_id:
            return
        params: dict[str, Any] = {
            "peer_id": self._peer_id,
            "group_id": self._group_id,
            "message": text,
        }
        if self._conversation_message_id:
            params["conversation_message_id"] = self._conversation_message_id
        elif self._message_id:
            params["message_id"] = self._message_id
        await self._api.request("messages.edit", params)


def _extract_message_ids(resp: Any) -> tuple[int | None, int | None]:
    item = None
    if isinstance(resp, list) and resp:
        item = resp[0]
    elif isinstance(resp, dict):
        inner = resp.get("response")
        if isinstance(inner, list) and inner:
            item = inner[0]
        elif isinstance(inner, dict):
            item = inner
    if not isinstance(item, dict):
        return None, None
    mid = item.get("message_id")
    cmid = item.get("conversation_message_id")
    return (int(mid) if mid else None, int(cmid) if cmid else None)
