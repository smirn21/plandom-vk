"""Скачивание вложений из сообщений VK."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


async def download_url(url: str, dest: Path, timeout: float = 90) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def _photo_url(photo: Any) -> str | None:
    sizes = getattr(photo, "sizes", None) or (photo or {}).get("sizes") or []
    if not sizes:
        return None
    best = max(sizes, key=lambda s: (getattr(s, "width", None) or s.get("width") or 0))
    return getattr(best, "url", None) or best.get("url")


def _doc_url(doc: Any) -> tuple[str | None, str]:
    title = getattr(doc, "title", None) or (doc or {}).get("title") or "file"
    url = getattr(doc, "url", None) or (doc or {}).get("url")
    ext = getattr(doc, "ext", None) or (doc or {}).get("ext") or Path(title).suffix.lstrip(".")
    return url, f"{Path(title).stem}.{ext}" if ext else title


async def save_message_attachments(message: Any, dest_dir: Path) -> list[Path]:
    """Сохраняет фото и документы из сообщения VK."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    attachments = getattr(message, "attachments", None) or []
    idx = 0
    for att in attachments:
        att_type = getattr(att, "type", None) or (att or {}).get("type")
        try:
            if att_type == "photo" and getattr(att, "photo", None):
                url = _photo_url(att.photo)
                if url:
                    path = dest_dir / f"photo_{idx}.jpg"
                    await download_url(url, path)
                    saved.append(path)
                    idx += 1
            elif att_type == "doc" and getattr(att, "doc", None):
                url, name = _doc_url(att.doc)
                if url:
                    path = dest_dir / name
                    await download_url(url, path)
                    saved.append(path)
                    idx += 1
        except Exception as exc:
            LOGGER.warning("attachment download failed: %s", exc)
    return saved
