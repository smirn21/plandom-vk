"""Загрузка медиа в VK."""
from __future__ import annotations

import io
import logging
from typing import Any

import httpx
from PIL import Image

LOGGER = logging.getLogger(__name__)


def _jpeg_bytes(image_bytes: bytes, *, quality: int = 90) -> bytes:
    """VK upload server часто не принимает PNG — конвертируем в JPEG."""
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    if img.width < 200 or img.height < 200:
        scale = max(200 / img.width, 200 / img.height)
        img = img.resize(
            (max(200, int(img.width * scale)), max(200, int(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    jpeg = buf.getvalue()
    if len(jpeg) < 500:
        raise ValueError(f"JPEG too small ({len(jpeg)} bytes)")
    return jpeg


def _photo_field_ok(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text not in ("[]", "{}", "null")


async def upload_photo_to_messages(
    api: Any,
    peer_id: int,
    image_bytes: bytes,
    *,
    group_id: int | None = None,
) -> str | None:
    try:
        params: dict[str, int] = {"peer_id": int(peer_id)}
        if group_id:
            params["group_id"] = int(group_id)
        upload_server = await api.request("photos.getMessagesUploadServer", params)
        server_data = upload_server
        if isinstance(upload_server, dict) and "upload_url" not in upload_server:
            server_data = upload_server.get("response") or upload_server
        upload_url = server_data.get("upload_url") if isinstance(server_data, dict) else None
        if not upload_url:
            LOGGER.warning("No upload_url: %s", upload_server)
            return None

        jpeg = _jpeg_bytes(image_bytes)
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            files = {"photo": ("plan.jpg", jpeg, "image/jpeg")}
            up_resp = await client.post(upload_url, files=files)
            if up_resp.status_code != 200:
                LOGGER.warning("Upload POST HTTP %s", up_resp.status_code)
                return None
            up_data = up_resp.json()

        photo_raw = up_data.get("photo")
        if not _photo_field_ok(photo_raw):
            LOGGER.warning(
                "Upload response without photo (len=%s): keys=%s preview=%r",
                len(jpeg),
                list(up_data.keys()),
                str(photo_raw)[:80] if photo_raw is not None else None,
            )
            try:
                jpeg = _jpeg_bytes(image_bytes, quality=75)
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                    files = {"photo": ("plan.jpg", jpeg, "image/jpeg")}
                    up_resp = await client.post(upload_url, files=files)
                    up_data = up_resp.json()
                photo_raw = up_data.get("photo")
            except Exception as retry_exc:
                LOGGER.warning("Upload retry failed: %s", retry_exc)
            if not _photo_field_ok(photo_raw):
                return None

        saved = await api.request(
            "photos.saveMessagesPhoto",
            {
                "photo": photo_raw,
                "server": up_data.get("server"),
                "hash": up_data.get("hash"),
            },
        )
        photos = saved if isinstance(saved, list) else (
            saved.get("response") if isinstance(saved, dict) else None
        )
        if not photos:
            LOGGER.warning("photos.saveMessagesPhoto empty: %s", saved)
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
    api: Any,
    peer_id: int,
    file_bytes: bytes,
    title: str = "plandom.pdf",
    *,
    group_id: int | None = None,
) -> str | None:
    try:
        params: dict = {"type": "doc", "peer_id": int(peer_id)}
        if group_id:
            params["group_id"] = int(group_id)
        upload_server = await api.request("docs.getMessagesUploadServer", params)
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

        file_raw = up_data.get("file")
        if not file_raw:
            LOGGER.warning("Doc upload without file field: %s", list(up_data.keys()))
            return None

        saved = await api.request(
            "docs.save",
            {
                "file": file_raw,
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
