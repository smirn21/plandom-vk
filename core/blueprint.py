"""Разбор чертежей: фото, PDF, SVG, DXF и др."""
from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path
from typing import Any

from PIL import Image

LOGGER = logging.getLogger(__name__)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif", ".tif", ".tiff"}
VECTOR_EXT = {".svg"}
CAD_EXT = {".dxf", ".dwg"}
DOC_EXT = {".pdf", ".doc", ".docx"}


def blueprint_to_image_bytes(path: Path, max_side: int = 1600) -> tuple[bytes, str]:
    """Конвертирует файл чертежа в JPEG для vision API."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        img = Image.open(path)
    elif ext == ".pdf":
        img = _pdf_first_page(path)
    elif ext in VECTOR_EXT:
        try:
            import cairosvg

            png = cairosvg.svg2png(bytestring=path.read_bytes())
            img = Image.open(io.BytesIO(png))
        except Exception:
            img = Image.new("RGB", (1200, 900), (255, 255, 255))
    elif ext in CAD_EXT:
        img = _dxf_to_image(path)
    else:
        try:
            img = Image.open(path)
        except Exception as exc:
            raise ValueError(f"Формат {ext or 'без расширения'} не поддержан: {exc}") from exc

    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue(), "image/jpeg"


def image_bytes_to_data_uri(data: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _pdf_first_page(path: Path) -> Image.Image:
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise ValueError("Для PDF установите pymupdf") from exc
    doc = fitz.open(path)
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return Image.open(io.BytesIO(pix.tobytes("png")))
    finally:
        doc.close()


def _dxf_to_image(path: Path) -> Image.Image:
    try:
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext, svg
    except ImportError as exc:
        raise ValueError("Для DXF установите ezdxf") from exc
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    ctx = RenderContext(doc)
    backend = svg.SVGBackend()
    Frontend(ctx, backend).draw_layout(msp)
    svg_str = backend.get_string()
    # Простой fallback: белый холст с подписью
    img = Image.new("RGB", (1200, 900), (255, 255, 255))
    if "<line" in svg_str or "<path" in svg_str:
        return img
    raise ValueError("DXF пустой или не читается")


def merge_blueprint_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Объединяет несколько этажей/файлов."""
    rooms: list[dict[str, Any]] = []
    floors: list[dict[str, Any]] = []
    total_area = 0.0
    estimated = False
    notes: list[str] = []
    for i, res in enumerate(results):
        floor_rooms = res.get("rooms") or []
        label = res.get("floor_label") or f"Этаж {i + 1}"
        floors.append({"label": label, "rooms": floor_rooms, "area_m2": res.get("total_area_m2")})
        for r in floor_rooms:
            room = dict(r)
            if len(results) > 1:
                room["name"] = f"{label}: {room.get('name', 'Комната')}"
            rooms.append(room)
        if res.get("total_area_m2"):
            total_area += float(res["total_area_m2"])
        estimated = estimated or bool(res.get("estimated"))
        if res.get("notes"):
            notes.append(str(res["notes"]))
    return {
        "rooms": rooms,
        "total_area_m2": round(total_area, 2) if total_area else None,
        "floors": floors,
        "estimated": estimated,
        "notes": "; ".join(notes),
        "source": "blueprint",
    }


def normalize_blueprint_payload(raw: dict[str, Any]) -> dict[str, Any]:
    rooms = []
    for r in raw.get("rooms") or []:
        name = (r.get("name") or "Комната").strip()
        room: dict[str, Any] = {
            "name": name,
            "room_type": _guess_room_type(name),
        }
        w, l = r.get("width_m"), r.get("length_m")
        if w and l:
            try:
                room["width_m"] = round(float(w), 2)
                room["length_m"] = round(float(l), 2)
                room["area_m2"] = round(float(w) * float(l), 2)
            except (TypeError, ValueError):
                pass
        elif r.get("area_m2"):
            try:
                room["area_m2"] = round(float(r["area_m2"]), 2)
            except (TypeError, ValueError):
                pass
        if r.get("windows"):
            room["windows"] = r["windows"]
        if r.get("doors"):
            room["doors"] = r["doors"]
        rooms.append(room)
    out: dict[str, Any] = {
        "rooms": rooms,
        "estimated": bool(raw.get("estimated")),
        "notes": raw.get("notes") or "",
    }
    if raw.get("total_area_m2"):
        try:
            out["total_area_m2"] = round(float(raw["total_area_m2"]), 2)
        except (TypeError, ValueError):
            pass
    if raw.get("ceiling_height_m"):
        out["ceiling_height_m"] = raw["ceiling_height_m"]
    if raw.get("wet_zones"):
        out["wet_zones"] = raw["wet_zones"]
    return out


def _guess_room_type(name: str) -> str:
    n = name.lower()
    mapping = [
        (r"гостин", "living"),
        (r"спальн", "bedroom"),
        (r"кухн", "kitchen"),
        (r"сануз|ванн|туал", "bath"),
        (r"прихож|холл", "hall"),
        (r"кабинет|офис", "office"),
        (r"детск", "kids"),
    ]
    for pat, key in mapping:
        if re.search(pat, n):
            return key
    return "other"
