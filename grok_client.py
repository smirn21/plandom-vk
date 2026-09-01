"""Grok/xAI — планировка, описания, рендер интерьеров и разбор чертежей."""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)

IMAGE_API_BASE = "https://api.x.ai/v1"
DEFAULT_IMAGE_MODEL = "grok-imagine-image"
DEFAULT_CHAT_MODEL = "grok-build-0.1"
IMAGE_MODEL_FALLBACKS = (
    "grok-imagine-image",
    "grok-imagine-image-quality",
    "grok-imagine-image-2.0",
)
CHAT_MODEL_FALLBACKS = (
    "grok-build-0.1",
    "grok-4-1-fast-non-reasoning",
    "grok-4-fast-non-reasoning",
    "grok-2-1212",
    "grok-2-vision-1212",
    "grok-beta",
    "grok-3",
    "grok-3-mini",
)
MODELS_LIST_URL = "https://api.x.ai/v1/models"

ROOM_TYPE_IMAGE_HINTS: dict[str, str] = {
    "bedroom": "master bedroom: double bed, nightstands, wardrobe, soft bedding, curtains",
    "bath": "bathroom: toilet, sink, vanity, shower or bathtub, wall and floor tiles",
    "living": "living room: sofa, coffee table, TV wall, rug, ambient lighting",
    "kitchen": "kitchen: cabinets, countertop, sink, stove, dining zone if space allows",
    "hall": "entry hallway: console, mirror, shoe storage, coat hooks, good lighting",
    "office": "home office: desk, ergonomic chair, shelves, task lighting",
    "kids": "children room: bed, desk, toy storage, playful but tidy decor",
    "other": "functional interior appropriate to the room purpose",
}


def is_grok_image_model(name: str) -> bool:
    n = name.lower()
    if "imagine" in n or "voice" in n:
        return True
    return n.startswith("grok-") and "-image" in n and "vision" not in n


def normalize_grok_models(chat_model: str, image_model: str) -> tuple[str, str]:
    chat = (chat_model or "").strip()
    image = (image_model or "").strip()
    if chat and is_grok_image_model(chat):
        LOGGER.warning(
            "GROK_MODEL=%s — это image-модель, не chat. "
            "Используйте GROK_IMAGE_MODEL для картинок и GROK_MODEL для текста.",
            chat,
        )
        if not image or image == DEFAULT_IMAGE_MODEL:
            image = chat
        chat = DEFAULT_CHAT_MODEL
    if not chat:
        chat = DEFAULT_CHAT_MODEL
    if not image:
        image = DEFAULT_IMAGE_MODEL
    return chat, image


class GrokClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_CHAT_MODEL,
        url: str = "https://api.x.ai/v1/chat/completions",
        *,
        image_model: str = DEFAULT_IMAGE_MODEL,
        image_api_url: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url
        self.image_model = image_model
        self.image_api_url = image_api_url or f"{IMAGE_API_BASE}/images/generations"
        self._working_image_model: str | None = None
        self._blocked_image_models: set[str] = set()
        self._blocked_chat_models: set[str] = set()
        self._available_chat_models: list[str] | None = None
        self._available_image_models: list[str] | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: float = 120,
        raise_for_status: bool = True,
    ) -> tuple[int, dict[str, Any] | str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            try:
                body: dict[str, Any] | str = response.json()
            except Exception:
                body = response.text
            if raise_for_status:
                response.raise_for_status()
            return response.status_code, body

    def _chat_model_candidates(self) -> list[str]:
        models: list[str] = []

        def add(name: str) -> None:
            if (
                name
                and name not in models
                and not is_grok_image_model(name)
                and name not in self._blocked_chat_models
            ):
                models.append(name)

        if self._available_chat_models:
            for name in self._available_chat_models:
                add(name)
            return models

        add(self.model)
        for name in CHAT_MODEL_FALLBACKS:
            add(name)
        return models

    async def refresh_chat_models(self) -> None:
        if not self.api_key:
            return
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(MODELS_LIST_URL, headers=headers)
            if response.status_code != 200:
                return
            body = response.json()
            items = body.get("data") if isinstance(body, dict) else None
            if not isinstance(items, list):
                return
            chat_models: list[str] = []
            image_models: list[str] = []
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                model_id = str(item["id"])
                if is_grok_image_model(model_id):
                    image_models.append(model_id)
                elif "voice" not in model_id.lower():
                    chat_models.append(model_id)
            if chat_models:
                self._available_chat_models = chat_models
                LOGGER.info("Grok chat models available: %s", ", ".join(chat_models[:8]))
            if image_models:
                self._available_image_models = image_models
                LOGGER.info("Grok image models available: %s", ", ".join(image_models[:8]))
        except Exception as exc:
            LOGGER.debug("Grok models list failed: %s", exc)

    async def _chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        timeout: float = 120,
    ) -> str:
        if self._available_chat_models is None:
            await self.refresh_chat_models()
        last_error = ""
        for model in self._chat_model_candidates():
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
            }
            status, body = await self._post_json(
                self.url, payload, timeout=timeout, raise_for_status=False
            )
            if status == 200 and isinstance(body, dict):
                try:
                    content = body["choices"][0]["message"]["content"]
                    if content and str(content).strip():
                        if model != self.model:
                            LOGGER.info("Grok chat ok with model %s", model)
                        return str(content).strip()
                except (KeyError, IndexError, TypeError) as exc:
                    raise RuntimeError(f"Unexpected Grok response: {body}") from exc
            err = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)[:400]
            last_error = f"HTTP {status} model={model}: {err}"
            LOGGER.warning("Grok chat attempt failed: %s", last_error)
            if status in (400, 404):
                self._blocked_chat_models.add(model)
        raise RuntimeError(last_error or "Grok chat failed")

    async def answer_text(
        self, user_text: str, system: str, *, max_tokens: int = 800
    ) -> str:
        if not self.api_key:
            raise RuntimeError("GROK_API_KEY не задан")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
        return await self._chat_completion(messages, max_tokens=max_tokens, temperature=0.2)

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
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_uri, "detail": "high"}},
                    {"type": "text", "text": prompt},
                ],
            },
        ]
        return await self._chat_completion(
            messages, max_tokens=max_tokens, temperature=0.1, timeout=150
        )

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
        room_count = len(rooms)
        system = (
            "Ты профессиональный архитектор-планировщик с 15-летним опытом жилых интерьеров. "
            "Отвечай ТОЛЬКО валидным JSON без markdown. "
            'Формат: {"rooms":[{"name":"...","x":0,"y":0,"w":40,"h":30,'
            '"width_m":3.2,"length_m":4.5,"doors":[],"windows":[]}]} '
            "Координаты x,y,w,h — 0..100, комнаты не пересекаются. "
            f"ОБЯЗАТЕЛЬНО верни ровно {room_count} комнат — ни одной больше, ни одной меньше. "
            "Сохраняй реальные размеры комнат если указаны."
        )
        prompt = (
            f"Тип: {ptype}. Площадь: {area} м². "
            f"Список комнат ({room_count} шт., каждая обязательна): {room_names}. "
            f"Потолок: {brief.get('ceiling_height_m', 'стандарт')} м. "
            f"Окна/двери: {brief.get('openings_notes', '')}. "
            f"Мокрые зоны: {brief.get('wet_zones', '')}. "
            f"Заметки: {brief.get('notes', '')}. "
            "Расположи комнаты логично: санузел у мокрой зоны, спальня приватно, гостиная центрально."
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
            "Ты профессиональный дизайнер интерьеров премиум-класса. "
            "Пиши как для презентации клиенту: конкретная мебель, материалы, палитра, "
            "освещение, текстуры. 4–6 предложений на русском, без markdown."
        )
        room_type = room.get("room_type") or "other"
        prompt = (
            f"Комната: {name} (тип: {room_type}).{size} Стиль: {style}. Бюджет: {budget}. "
            f"Пожелания клиента: {wishes}. Заметки: {brief.get('notes', '')}. "
            f"Опиши именно {name}, не путай с другими помещениями."
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
        room_type = str(room.get("room_type") or "other")
        type_hint = ROOM_TYPE_IMAGE_HINTS.get(room_type, ROOM_TYPE_IMAGE_HINTS["other"])
        ceiling = brief.get("ceiling_height_m") or 2.7
        size = ""
        if room.get("width_m") and room.get("length_m"):
            size = f"{room['width_m']}m x {room['length_m']}m"
        elif room.get("area_m2"):
            size = f"{room['area_m2']} sqm"
        view_map = {
            "entrance": "camera at entrance doorway looking into the room",
            "window": "camera facing the window wall, natural daylight",
            "corner": "wide corner angle showing two walls and depth of the room",
        }
        view_line = view_map.get(view, view_map["entrance"])
        wishes = brief.get("furniture_wishes") or ""
        return (
            f"Professional interior design photography by an award-winning designer. "
            f"Room: {name}. Room type: {room_type}. Required elements: {type_hint}. "
            f"Style: {style} {style_notes}. Budget tier: {budget}. Size: {size}. "
            f"Ceiling height {ceiling}m. {view_line}. "
            f"Designer brief: {description}. Client wishes: {wishes}. "
            f"CRITICAL: image must clearly be a {name} ({room_type}), not another room type. "
            "Photorealistic, magazine-quality, natural materials, soft daylight, "
            "no people, no logos, no text, no watermarks, 8k detail."
        )

    def _image_model_candidates(self) -> list[str]:
        if self._working_image_model:
            return [self._working_image_model]
        models: list[str] = []

        def add(name: str) -> None:
            if name and name not in models and name not in self._blocked_image_models:
                models.append(name)

        if self._available_image_models:
            for name in self._available_image_models:
                add(name)
            return models

        for name in (self.image_model, *IMAGE_MODEL_FALLBACKS):
            add(name)
        return models

    @staticmethod
    def _image_payload_variants(model: str, prompt: str, *, quality: str) -> list[dict[str, Any]]:
        if model == "grok-imagine-image-2.0":
            return [
                {
                    "model": model,
                    "prompt": prompt,
                    "n": 1,
                    "aspect_ratio": "4:3",
                    "quality": quality,
                    "response_format": "b64_json",
                },
                {"model": model, "prompt": prompt, "n": 1, "aspect_ratio": "4:3"},
                {"model": model, "prompt": prompt, "n": 1},
            ]
        return [
            {"model": model, "prompt": prompt, "n": 1, "response_format": "b64_json"},
            {"model": model, "prompt": prompt, "n": 1},
        ]

    async def _decode_image_response(self, data: dict[str, Any]) -> bytes | None:
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
        return None

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
        last_error = ""
        for model in self._image_model_candidates():
            for payload in self._image_payload_variants(model, prompt, quality=quality):
                try:
                    status, body = await self._post_json(
                        self.image_api_url,
                        payload,
                        timeout=180,
                        raise_for_status=False,
                    )
                    if status == 200 and isinstance(body, dict):
                        image = await self._decode_image_response(body)
                        if image:
                            self._working_image_model = model
                            if model != self.image_model:
                                LOGGER.info("Grok image ok with model %s", model)
                            return image
                    if status == 404:
                        self._blocked_image_models.add(model)
                        break
                    err = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)[:300]
                    last_error = f"HTTP {status} model={model}: {err}"
                    LOGGER.debug("Grok image attempt failed: %s", last_error)
                except Exception as exc:
                    last_error = f"model={model}: {exc}"
                    LOGGER.debug("Grok image attempt error: %s", last_error)
        LOGGER.warning(
            "Grok image failed (%s): %s. Проверьте Imagine API и биллинг на console.x.ai",
            view,
            last_error or "unknown",
        )
        return None
