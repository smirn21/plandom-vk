"""Загрузка медиа в VK."""
from __future__ import annotations

import logging
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


async def upload_photo_to_messages(api: Any, peer_id: int, image_bytes: bytes) -> str | None:
    try:
        upload_server = await api.request(
            "photos.getMessagesUploadServer",
            {"peer_id": int(peer_id)},
        )
        server_data = upload_server
        if isinstance(upload_server, dict) and "upload_url" not in upload_server:
            server_data = upload_server.get("response") or upload_server
        upload_url = server_data.get("upload_url") if isinstance(server_data, dict) else None
        if not upload_url:
            return None

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            files = {"photo": ("plan.png", image_bytes, "image/png")}
            up_resp = await client.post(upload_url, files=files)
            if up_resp.status_code != 200:
                return None
            up_data = up_resp.json()

        saved = await api.request(
            "photos.saveMessagesPhoto",
            {
                "photo": up_data.get("photo", ""),
                "server": up_data.get("server"),
                "hash": up_data.get("hash"),
            },
        )
        photos = saved if isinstance(saved, list) else (
            saved.get("response") if isinstance(saved, dict) else None
        )
        if not photos:
            return None
        photo = photos[0] if isinstance(photos, list) else photos
        owner_id = photo.get("owner_id")
        photo_id = photo.get("id")
        access_key = photo.get("access_key")
        if owner_id is None or photo_id is None:
            return None
        att = f"photo{owner_id}_{photo_id}"
        if access_key:
            att = f"{att}_{access_key}"
        return att
    except Exception as exc:
        LOGGER.warning("upload_photo failed: %s", exc)
        return None


async def upload_doc_to_messages(
    api: Any, peer_id: int, file_bytes: bytes, title: str = "plandom.pdf"
) -> str | None:
    try:
        upload_server = await api.request(
            "docs.getMessagesUploadServer",
            {"type": "doc", "peer_id": int(peer_id)},
        )
        server_data = upload_server
        if isinstance(upload_server, dict) and "upload_url" not in upload_server:
            server_data = upload_server.get("response") or upload_server
        upload_url = server_data.get("upload_url") if isinstance(server_data, dict) else None
        if not upload_url:
            return None

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            files = {"file": (title, file_bytes, "application/pdf")}
            up_resp = await client.post(upload_url, files=files)
            if up_resp.status_code != 200:
                return None
            up_data = up_resp.json()

        saved = await api.request(
            "docs.save",
            {
                "file": up_data.get("file", ""),
                "title": title,
            },
        )
        docs = saved if isinstance(saved, list) else (
            saved.get("response", {}).get("doc")
            if isinstance(saved, dict) and saved.get("response")
            else saved.get("doc") if isinstance(saved, dict) else None
        )
        if isinstance(docs, dict):
            doc = docs
        elif isinstance(docs, list) and docs:
            doc = docs[0]
        else:
            return None
        owner_id = doc.get("owner_id")
        doc_id = doc.get("id")
        access_key = doc.get("access_key")
        if owner_id is None or doc_id is None:
            return None
        att = f"doc{owner_id}_{doc_id}"
        if access_key:
            att = f"{att}_{access_key}"
        return att
    except Exception as exc:
        LOGGER.warning("upload_doc failed: %s", exc)
        return None
