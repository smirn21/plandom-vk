"""HTTP/API надёжность для VK."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)

_PYDANTIC_PATCHED = False


def patch_vkbottle_pydantic() -> None:
    """Починить MessagesSendPeerIdsResponse на Python 3.10 + pydantic 2.13.

    vkbottle_types объявляет MessagesSendPeerIdsResponse в другом модуле, чем
    MessagesSendUserIdsResponseItem. Pydantic не резолвит forward-ref и
    message.answer() падает с class-not-fully-defined — уже после того, как
    VK принял messages.send. Нельзя «повторить» send в except: уйдёт дубль.
    """
    global _PYDANTIC_PATCHED
    if _PYDANTIC_PATCHED:
        return
    _PYDANTIC_PATCHED = True

    try:
        import vkbottle_types.codegen.responses.messages as codegen_ns
        import vkbottle_types.responses.messages as msg_ns
        from vkbottle_types.objects import MessagesSendUserIdsResponseItem
    except Exception as exc:
        LOGGER.warning("vkbottle_types unavailable, skip pydantic patch: %s", exc)
        return

    msg_ns.MessagesSendUserIdsResponseItem = MessagesSendUserIdsResponseItem
    codegen_ns.MessagesSendUserIdsResponseItem = MessagesSendUserIdsResponseItem

    types_ns = {
        "MessagesSendUserIdsResponseItem": MessagesSendUserIdsResponseItem,
        **vars(msg_ns),
        **vars(codegen_ns),
    }
    for model_name in ("MessagesSendUserIdsResponse", "MessagesSendPeerIdsResponse"):
        model = getattr(msg_ns, model_name, None)
        if model is None or not hasattr(model, "model_rebuild"):
            continue
        try:
            model.model_rebuild(force=True, _types_namespace=types_ns)
        except Exception as exc:
            LOGGER.warning("model_rebuild %s failed: %s", model_name, exc)

    # Всегда подменяем messages.send: даже после rebuild на 3.10 модель
    # может остаться mock-валидатором, а повторный send в except даст дубль.
    _install_messages_send_fallback()


def _install_messages_send_fallback() -> None:
    """Разбор ответа messages.send без недособранной pydantic-модели."""
    try:
        from vkbottle_types.methods.messages import MessagesCategory
    except Exception as exc:
        LOGGER.warning("Cannot patch messages.send: %s", exc)
        return

    async def send(
        self,
        user_id=None,
        random_id=None,
        peer_id=None,
        peer_ids=None,
        domain=None,
        chat_id=None,
        user_ids=None,
        message=None,
        lat=None,
        long=None,
        attachment=None,
        reply_to=None,
        forward_messages=None,
        forward=None,
        sticker_id=None,
        group_id=None,
        keyboard=None,
        template=None,
        payload=None,
        content_source=None,
        dont_parse_links=None,
        disable_mentions=None,
        intent=None,
        subscribe_id=None,
        **kwargs,
    ):
        params = self.get_set_params(locals())
        response = await self.api.request("messages.send", params)
        if isinstance(response, dict) and "response" in response:
            return response["response"]
        return response

    MessagesCategory.send = send  # type: ignore[method-assign]
    LOGGER.info("vkbottle messages.send: pydantic fallback enabled")


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
