"""Сервис распознавания чертежей."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.blueprint import (
    blueprint_to_image_bytes,
    image_bytes_to_data_uri,
    merge_blueprint_results,
    normalize_blueprint_payload,
)
from grok_client import GrokClient

LOGGER = logging.getLogger(__name__)


async def recognize_blueprint_files(
    grok: GrokClient,
    paths: list[Path],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for i, path in enumerate(paths):
        try:
            data, mime = blueprint_to_image_bytes(path)
            uri = image_bytes_to_data_uri(data, mime)
            raw = await grok.parse_blueprint_image(uri, floor_hint=f"Файл {i + 1}: {path.name}")
            results.append(normalize_blueprint_payload(raw))
        except Exception as exc:
            LOGGER.warning("Blueprint file %s failed: %s", path, exc)
            results.append({"estimated": True, "rooms": [], "notes": str(exc)})
    merged = merge_blueprint_results(results)
    merged["blueprint_files"] = [str(p) for p in paths]
    return merged
