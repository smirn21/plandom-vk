"""Grok/xAI — планировка, описания, рендер интерьеров и разбор чертежей."""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)

IMAGE_API = "https://api.x.ai/v1/images/generations"
DEFAULT_IMAGE_MODEL = "grok-imagine-image-2.0"


class GrokClient:
    def __init__(
        self,
        api_key: str,
        model: str = "grok-2-latest",
        url: str = "https://api.x.ai/v1/chat/completions",
        *,
        image_model: str = DEFAULT_IMAGE_MODEL,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url
        self.image_model = image_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _post_json(self, url: str, payload: dict[str, Any], *, timeout: float = 120) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

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
        data = await self._post_json(self.url, payload)
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Grok response: {data}") from exc

    async def answer_vision(
        self,
        image_data_uri: str,
        prompt: str,
        system: str,
        *,
        max_tokens: int = 1200,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("GROK_API_KEY не задан")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_uri, "detail": "high"}},
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
            "temperature": 0.1,
            "max_output_tokens": max_tokens,
        }
        data = await self._post_json(self.url, payload, timeout=150)
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Grok vision response: {data}") from exc

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

    async def parse_blueprint_image(self, image_data_uri: str, *, floor_hint: str = "") -> dict[str, Any]:
        system = (
            "Ты архитектор. По чертежу/плану квартиры извлеки данные. "
            "Ответь ТОЛЬКО JSON без markdown:\n"
            '{"estimated":true/false,"total_area_m2":число или null,'
            '"ceiling_height_m":число или null,"notes":"...",'
            '"rooms":[{"name":"...","room_type":"living|bedroom|kitchen|bath|hall|office|kids|other",'
            '"width_m":число или null,"length_m":число или null,"area_m2":число или null,'
            '"doors":[{"wall":"north|south|east|west","offset":0.5,"width_m":0.9}],'
            '"windows":[{"wall":"north|south|east|west","offset":0.3,"width_m":1.5}]}]}'
            "\nЕсли масштаб неясен — estimated:true и приблизительные размеры."
        )
        prompt = (
            f"Распознай планировку. {floor_hint}\n"
            "Определи комнаты, размеры в метрах, двери и окна если видны."
        )
        try:
            raw = await self.answer_vision(image_data_uri, prompt, system, max_tokens=1400)
            return self._extract_json(raw)
        except Exception as exc:
            LOGGER.warning("Blueprint vision failed: %s", exc)
            return {"estimated": True, "rooms": [], "notes": str(exc)}

    async def generate_layout(self, brief: dict[str, Any]) -> dict[str, Any]:
        rooms = brief.get("rooms") or []
        room_lines = []
        for r in rooms:
            parts = [r.get("name", "Комната")]
            if r.get("width_m") and r.get("length_m"):
                parts.append(f"{r['width_m']}×{r['length_m']} м")
            elif r.get("area_m2"):
                parts.append(f"{r['area_m2']} м²")
            room_lines.append(", ".join(parts))
        room_names = "; ".join(room_lines) or "одна комната"
        area = brief.get("total_area_m2") or "не указана"
        ptype = brief.get("project_type", "apartment")
        system = (
            "Ты архитектор-планировщик. Отвечай ТОЛЬКО валидным JSON без markdown. "
            'Формат: {"rooms":[{"name":"...","x":0,"y":0,"w":40,"h":30,'
            '"width_m":3.2,"length_m":4.5,"doors":[],"windows":[]}]} '
            "Координаты x,y,w,h — 0..100, комнаты не пересекаются. "
            "Сохраняй реальные размеры комнат если указаны."
        )
        prompt = (
            f"Тип: {ptype}. Площадь: {area} м². Комнаты: {room_names}. "
            f"Потолок: {brief.get('ceiling_height_m', 'стандарт')} м. "
            f"Окна/двери: {brief.get('openings_notes', '')}. "
            f"Мокрые зоны: {brief.get('wet_zones', '')}. "
            f"Заметки: {brief.get('notes', '')}. "
            "Расположи комнаты логично."
        )
        try:
            raw = await self.answer_text(prompt, system, max_tokens=900)
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
        if brief.get("style_notes"):
            style = f"{style}, {brief['style_notes']}"
        budget = budget_map.get(brief.get("budget_tier", "medium"), brief.get("budget_tier", ""))
        name = room.get("name") or "Комната"
        size = ""
        if room.get("width_m") and room.get("length_m"):
            size = f" Размер {room['width_m']}×{room['length_m']} м."
        elif room.get("area_m2"):
            size = f" Площадь {room['area_m2']} м²."
        wishes = brief.get("furniture_wishes") or ""
        if not self.api_key:
            return (
                f"{name}:{size} {style} интерьер, бюджет {budget}. "
                "Диван, стол, освещение, растения — уютная обстановка."
            )
        system = (
            "Ты дизайнер интерьеров. Кратко опиши обстановку комнаты на русском: "
            "мебель, цвета, материалы, 4–6 предложений, без markdown."
        )
        prompt = (
            f"Комната: {name}.{size} Стиль: {style}. Бюджет: {budget}. "
            f"Пожелания: {wishes}. Заметки: {brief.get('notes', '')}"
        )
        try:
            return await self.answer_text(prompt, system, max_tokens=400)
        except Exception as exc:
            LOGGER.warning("Grok room description failed: %s", exc)
            return f"{name}: {style} интерьер, бюджет {budget}."

    def _interior_prompt(
        self,
        room: dict[str, Any],
        brief: dict[str, Any],
        description: str,
        *,
        view: str,
    ) -> str:
        style = brief.get("style", "scandinavian")
        style_notes = brief.get("style_notes") or ""
        budget = brief.get("budget_tier", "medium")
        name = room.get("name") or "room"
        ceiling = brief.get("ceiling_height_m") or 2.7
        size = ""
        if room.get("width_m") and room.get("length_m"):
            size = f"{room['width_m']}m x {room['length_m']}m"
        elif room.get("area_m2"):
            size = f"{room['area_m2']} sqm"
        view_map = {
            "entrance": "camera at entrance doorway looking into the room",
            "window": "camera facing the window wall, natural daylight",
        }
        view_line = view_map.get(view, view_map["entrance"])
        wishes = brief.get("furniture_wishes") or ""
        return (
            f"Professional photorealistic interior design photograph of {name}, "
            f"{style} style {style_notes}, {budget} budget furniture, room size {size}, "
            f"ceiling height {ceiling}m. {view_line}. "
            f"Design brief: {description}. User wishes: {wishes}. "
            "High-end architectural photography, realistic materials, soft natural lighting, "
            "no people, no logos, no text, no watermarks, 8k detail."
        )

    async def generate_interior_image(
        self,
        room: dict[str, Any],
        brief: dict[str, Any],
        description: str,
        *,
        view: str = "entrance",
        quality: str = "medium",
    ) -> bytes | None:
        if not self.api_key:
            return None
        prompt = self._interior_prompt(room, brief, description, view=view)
        payload = {
            "model": self.image_model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": "4:3",
            "resolution": "2k",
            "quality": quality,
            "response_format": "b64_json",
        }
        try:
            data = await self._post_json(IMAGE_API, payload, timeout=180)
            items = data.get("data") or []
            if not items:
                return None
            b64 = items[0].get("b64_json")
            if b64:
                return base64.b64decode(b64)
            url = items[0].get("url")
            if url:
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.content
        except Exception as exc:
            LOGGER.warning("Grok image failed (%s): %s", view, exc)
        return None
