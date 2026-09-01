"""Загрузка медиа в VK."""
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import httpx
from PIL import Image

from core.image_normalize import normalize_image_bytes, MAX_VK_SIDE

LOGGER = logging.getLogger(__name__)


def _jpeg_bytes(image_bytes: bytes, *, quality: int = 85) -> bytes:
    """VK upload server часто не принимает PNG — конвертируем в JPEG."""
    try:
        normalized = normalize_image_bytes(image_bytes, quality=quality)
        if len(normalized) >= 500:
            return normalized
    except Exception:
        pass
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    if max(img.width, img.height) > MAX_VK_SIDE:
        scale = MAX_VK_SIDE / max(img.width, img.height)
        img = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    if img.width < 200 or img.height < 200:
        scale = max(200 / img.width, 200 / img.height)
        img = img.resize(
            (max(200, int(img.width * scale)), max(200, int(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    if img.width % 2:
        img = img.resize((img.width + 1, img.height), Image.Resampling.LANCZOS)
    if img.height % 2:
        img = img.resize((img.width, img.height + 1), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=False, progressive=False, subsampling=0)
    jpeg = buf.getvalue()
    if len(jpeg) < 500:
        raise ValueError(f"JPEG too small ({len(jpeg)} bytes)")
    return jpeg


def _photo_field_ok(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text not in ("[]", "{}", "null")


def _vk_upload_error(up_data: dict[str, Any]) -> str | None:
    if up_data.get("error"):
        return str(up_data.get("error_descr") or up_data.get("error"))
    return None


async def _post_multipart(upload_url: str, field: str, filename: str, data: bytes, mime: str) -> dict[str, Any]:
    LOGGER.debug("VK multipart POST field=%s file=%s size=%d mime=%s", field, filename, len(data), mime)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        files = {field: (filename, data, mime)}
        up_resp = await client.post(upload_url, files=files)
        if up_resp.status_code != 200:
            raise RuntimeError(f"HTTP {up_resp.status_code}")
        return up_resp.json()


def _attachment_from_doc(doc: dict[str, Any]) -> str | None:
    owner_id = doc.get("owner_id")
    doc_id = doc.get("id")
    if owner_id is None or doc_id is None:
        return None
    att = f"doc{owner_id}_{doc_id}"
    access_key = doc.get("access_key")
    if access_key:
        att = f"{att}_{access_key}"
    return att


async def _get_messages_upload_url(api: Any, peer_id: int, group_id: int | None) -> str | None:
    params: dict[str, int] = {"peer_id": int(peer_id)}
    if group_id:
        params["group_id"] = int(group_id)
    upload_server = await api.request("photos.getMessagesUploadServer", params)
    server_data = upload_server
    if isinstance(upload_server, dict) and "upload_url" not in upload_server:
        server_data = upload_server.get("response") or upload_server
    if isinstance(server_data, dict):
        return server_data.get("upload_url")
    return None


async def _get_doc_upload_url(api: Any, peer_id: int, group_id: int | None) -> str | None:
    params: dict = {"type": "doc", "peer_id": int(peer_id)}
    if group_id:
        params["group_id"] = int(group_id)
    upload_server = await api.request("docs.getMessagesUploadServer", params)
    server_data = upload_server
    if isinstance(upload_server, dict) and "upload_url" not in upload_server:
        server_data = upload_server.get("response") or upload_server
    if isinstance(server_data, dict):
        return server_data.get("upload_url")
    return None


async def _save_doc(api: Any, file_raw: str, title: str) -> str | None:
    saved = await api.request("docs.save", {"file": file_raw, "title": title})
    if isinstance(saved, dict) and saved.get("error"):
        LOGGER.warning("docs.save error: %s", saved)
        return None
    docs = saved if isinstance(saved, list) else (
        saved.get("response", {}).get("doc")
        if isinstance(saved, dict) and saved.get("response")
        else saved.get("doc") if isinstance(saved, dict) else None
    )
    if isinstance(docs, dict):
        return _attachment_from_doc(docs)
    if isinstance(docs, list) and docs:
        return _attachment_from_doc(docs[0])
    LOGGER.warning("docs.save empty: %s", saved)
    return None


async def upload_doc_to_messages(
    api: Any,
    peer_id: int,
    file_bytes: bytes,
    title: str = "plandom.pdf",
    *,
    group_id: int | None = None,
    mime: str = "application/pdf",
) -> str | None:
    LOGGER.info(
        "VK doc upload start peer=%s title=%s size=%d bytes mime=%s",
        peer_id,
        title,
        len(file_bytes),
        mime,
    )
    for attempt in range(1, 4):
        try:
            if attempt > 1:
                LOGGER.info("VK doc upload retry %d/3 peer=%s", attempt, peer_id)
                await asyncio.sleep(1.5 * attempt)
            upload_url = await _get_doc_upload_url(api, peer_id, group_id)
            if not upload_url:
                LOGGER.warning("No doc upload_url for peer=%s", peer_id)
                return None
            LOGGER.debug("VK doc upload_url obtained (attempt %d)", attempt)
            up_data = await _post_multipart(upload_url, "file", title, file_bytes, mime)
            err = _vk_upload_error(up_data)
            if err:
                LOGGER.warning("Doc upload VK error (attempt %s): %s", attempt, err)
                continue
            file_raw = up_data.get("file")
            if not file_raw:
                LOGGER.warning("Doc upload without file (attempt %s): %s", attempt, up_data)
                continue
            att = await _save_doc(api, str(file_raw), title)
            if att:
                LOGGER.info("VK doc upload ok peer=%s → %s (attempt %d)", peer_id, att, attempt)
            return att
        except Exception as exc:
            LOGGER.warning("upload_doc attempt %s failed: %s", attempt, exc)
    LOGGER.warning("VK doc upload failed after 3 attempts peer=%s title=%s", peer_id, title)
    return None


async def upload_photo_to_messages(
    api: Any,
    peer_id: int,
    image_bytes: bytes,
    *,
    group_id: int | None = None,
) -> str | None:
    LOGGER.info("VK photo upload start peer=%s size=%d bytes", peer_id, len(image_bytes))
    try:
        for attempt, quality in enumerate((85, 75, 65), start=1):
            LOGGER.info("VK photo attempt %d/3 quality=%d peer=%s", attempt, quality, peer_id)
            upload_url = await _get_messages_upload_url(api, peer_id, group_id)
            if not upload_url:
                LOGGER.warning("No upload_url for peer=%s", peer_id)
                return None
            if attempt > 1:
                await asyncio.sleep(0.8)
            jpeg = _jpeg_bytes(image_bytes, quality=quality)
            LOGGER.debug("VK photo JPEG ready attempt=%d size=%d", attempt, len(jpeg))
            try:
                up_data = await _post_multipart(upload_url, "photo", "photo.jpg", jpeg, "image/jpeg")
            except Exception as exc:
                LOGGER.warning("Upload POST failed (attempt %s): %s", attempt, exc)
                continue
            err = _vk_upload_error(up_data)
            if err:
                LOGGER.warning("Photo upload VK error (attempt %s): %s", attempt, err)
                continue
            photo_raw = up_data.get("photo")
            if not _photo_field_ok(photo_raw):
                LOGGER.warning(
                    "Upload response without photo (attempt %s, len=%s): %s",
                    attempt,
                    len(jpeg),
                    up_data,
                )
                continue
            save_params: dict[str, Any] = {
                "photo": photo_raw,
                "server": up_data.get("server"),
                "hash": up_data.get("hash"),
            }
            if group_id:
                save_params["group_id"] = int(group_id)
            saved = await api.request("photos.saveMessagesPhoto", save_params)
            photos = saved if isinstance(saved, list) else (
                saved.get("response") if isinstance(saved, dict) else None
            )
            if not photos:
                LOGGER.warning("photos.saveMessagesPhoto empty: %s", saved)
                continue
            photo = photos[0] if isinstance(photos, list) else photos
            owner_id = photo.get("owner_id")
            photo_id = photo.get("id")
            access_key = photo.get("access_key")
            if owner_id is None or photo_id is None:
                continue
            att = f"photo{owner_id}_{photo_id}"
            if access_key:
                att = f"{att}_{access_key}"
            LOGGER.info("VK photo upload ok peer=%s → %s (attempt %d)", peer_id, att, attempt)
            return att
        LOGGER.warning("VK photo upload failed after 3 attempts peer=%s", peer_id)
        return None
    except Exception as exc:
        LOGGER.warning("upload_photo failed: %s", exc)
        return None


async def upload_image_as_doc(
    api: Any,
    peer_id: int,
    image_bytes: bytes,
    title: str,
    *,
    group_id: int | None = None,
) -> str | None:
    """Fallback: картинка как документ (надёжнее для сообществ VK)."""
    jpeg = _jpeg_bytes(image_bytes, quality=80)
    safe_title = title if title.lower().endswith(".jpg") else f"{title}.jpg"
    return await upload_doc_to_messages(
        api,
        peer_id,
        jpeg,
        safe_title,
        group_id=group_id,
        mime="image/jpeg",
    )


async def upload_image_to_messages(
    api: Any,
    peer_id: int,
    image_bytes: bytes,
    *,
    group_id: int | None = None,
    doc_title: str = "plandom.jpg",
) -> str | None:
    """Сначала photo, при неудаче — doc."""
    LOGGER.info("VK image upload peer=%s title=%s size=%d", peer_id, doc_title, len(image_bytes))
    att = await upload_photo_to_messages(api, peer_id, image_bytes, group_id=group_id)
    if att:
        return att
    LOGGER.info("Photo upload failed, trying doc fallback for %s", doc_title)
    doc_att = await upload_image_as_doc(
        api, peer_id, image_bytes, doc_title, group_id=group_id
    )
    if doc_att:
        LOGGER.info("VK doc fallback ok peer=%s → %s", peer_id, doc_att)
    else:
        LOGGER.warning("VK image upload failed (photo + doc) peer=%s title=%s", peer_id, doc_title)
    return doc_att
