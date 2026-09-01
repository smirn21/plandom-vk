"""HTTP/API надёжность для VK."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


class LimitedRequestRescheduler:
    def __init__(self, delay: float = 1.5, max_attempts: int = 3) -> None:
        self.delay = delay
        self.max_attempts = max_attempts

    async def reschedule(
        self,
        ctx_api: Any,
        method: str,
        data: dict[str, Any],
        recent_response: Any,
    ) -> dict[str, Any]:
        attempt = 0
        response = recent_response
        while not isinstance(response, dict) and attempt < self.max_attempts:
            attempt += 1
            LOGGER.warning(
                "VK API bad response type=%s method=%s — retry %s/%s",
                type(response).__name__,
                method,
                attempt,
                self.max_attempts,
            )
            await asyncio.sleep(self.delay)
            response = await ctx_api.request(method, data)
        if not isinstance(response, dict):
            return {"error": {"error_code": -1, "error_msg": "invalid_response_after_retries"}}
        return response
