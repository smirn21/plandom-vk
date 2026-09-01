"""Grok/xAI — планировка и описания комнат."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class GrokClient:
    def __init__(
        self,
        api_key: str,
        model: str = "grok-2-latest",
        url: str = "https://api.x.ai/v1/chat/completions",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def answer_text(
        self, user_text: str, system: str, *, max_tokens: int = 800
    ) -> str:
        if not self.api_key:
            raise RuntimeError("GROK_API_KEY не задан")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
            "max_output_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(self.url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Grok response: {data}") from exc

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    async def generate_layout(self, brief: dict[str, Any]) -> dict[str, Any]:
        rooms = brief.get("rooms") or []
        room_names = ", ".join(r.get("name", "Комната") for r in rooms) or "одна комната"
        area = brief.get("total_area_m2") or "не указана"
        ptype = brief.get("project_type", "apartment")
        system = (
            "Ты архитектор-планировщик. Отвечай ТОЛЬКО валидным JSON без markdown. "
            "Формат: {\"rooms\":[{\"name\":\"...\",\"x\":0,\"y\":0,\"w\":40,\"h\":30}]} "
            "Координаты x,y,w,h — числа 0..100, комнаты не пересекаются, заполняют план."
        )
        prompt = (
            f"Тип: {ptype}. Площадь: {area} м². Комнаты: {room_names}. "
            f"Этажей: {brief.get('floors', 1)}. Заметки: {brief.get('notes', '')}. "
            "Расположи комнаты логично (кухня рядом с гостиной, санузел компактно)."
        )
        try:
            raw = await self.answer_text(prompt, system, max_tokens=600)
            layout = self._extract_json(raw)
            if layout.get("rooms"):
                return layout
        except Exception as exc:
            LOGGER.warning("Grok layout failed: %s", exc)
        return {}

    async def describe_room(self, room: dict[str, Any], brief: dict[str, Any]) -> str:
        style_map = {
            "scandinavian": "скандинавский",
            "modern": "современный",
            "loft": "лофт",
            "classic": "классика",
            "minimal": "минимализм",
        }
        budget_map = {
            "economy": "эконом",
            "medium": "средний",
            "premium": "премиум",
        }
        style = style_map.get(brief.get("style", "scandinavian"), brief.get("style", ""))
        budget = budget_map.get(brief.get("budget_tier", "medium"), brief.get("budget_tier", ""))
        name = room.get("name") or "Комната"
        if not self.api_key:
            return (
                f"{name}: {style} интерьер, бюджет {budget}. "
                "Диван, стол, освещение, растения — уютная обстановка."
            )
        system = (
            "Ты дизайнер интерьеров. Кратко опиши обстановку комнаты на русском: "
            "мебель, цвета, материалы, 4–6 предложений, без markdown."
        )
        prompt = f"Комната: {name}. Стиль: {style}. Бюджет: {budget}. Заметки: {brief.get('notes', '')}"
        try:
            return await self.answer_text(prompt, system, max_tokens=400)
        except Exception as exc:
            LOGGER.warning("Grok room description failed: %s", exc)
            return f"{name}: {style} интерьер, бюджет {budget}."
