"""
Создание и оформление сообщества VK «ПланДом» через user token.

Требует VK_USER_TOKEN с правами groups, photos, wall, offline.
После запуска обновляет .env (VK_GROUP_ID) и печатает ссылку на выпуск токена бота.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets" / "vk"
ENV_PATH = ROOT / ".env"
API = "https://api.vk.com/method"
V = "5.199"


def api(token: str, method: str, **params):
    params = {**params, "access_token": token, "v": V}
    for attempt in range(4):
        r = httpx.post(f"{API}/{method}", data=params, timeout=90)
        data = r.json()
        if "error" in data:
            err = data["error"]
            if err.get("error_code") == 6 and attempt < 3:
                time.sleep(1.2)
                continue
            raise RuntimeError(f"{method}: {err}")
        return data["response"]
    raise RuntimeError(f"{method}: retries exceeded")


def upload_photo(token: str, group_id: int, path: Path) -> str:
    server = api(token, "photos.getGroupsUploadServer", group_id=group_id)
    with path.open("rb") as f:
        up = httpx.post(server["upload_url"], files={"photo": (path.name, f, "image/png")}, timeout=90)
    up.raise_for_status()
    saved = api(
        token,
        "photos.savePhoto",
        group_id=group_id,
        photo=up.json()["photo"],
        server=up.json()["server"],
        hash=up.json()["hash"],
    )
    p = saved[0]
    return f"photo{p['owner_id']}_{p['id']}"


def upload_cover(token: str, group_id: int, path: Path) -> None:
    server = api(
        token,
        "photos.getOwnerCoverPhotoUploadServer",
        group_id=group_id,
        crop_x=0,
        crop_y=0,
        crop_x2=1590,
        crop_y2=400,
    )
    with path.open("rb") as f:
        up = httpx.post(server["upload_url"], files={"photo": (path.name, f, "image/png")}, timeout=90)
    up.raise_for_status()
    j = up.json()
    api(
        token,
        "photos.saveOwnerCoverPhoto",
        group_id=group_id,
        photo=j["photo"],
        hash=j["hash"],
    )


def upload_wall_photo(token: str, group_id: int, path: Path) -> str:
    server = api(token, "photos.getWallUploadServer", group_id=group_id)
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    with path.open("rb") as f:
        up = httpx.post(server["upload_url"], files={"photo": (path.name, f, mime)}, timeout=90)
    up.raise_for_status()
    j = up.json()
    saved = api(
        token,
        "photos.saveWallPhoto",
        group_id=group_id,
        photo=j["photo"],
        server=j["server"],
        hash=j["hash"],
    )
    p = saved[0]
    return f"photo{p['owner_id']}_{p['id']}"


def update_env(group_id: int) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    if re.search(r"^VK_GROUP_ID=", text, re.M):
        text = re.sub(r"^VK_GROUP_ID=.*$", f"VK_GROUP_ID={group_id}", text, flags=re.M)
    else:
        text += f"\nVK_GROUP_ID={group_id}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def find_existing_group(token: str, title: str) -> int | None:
    items = api(token, "groups.get", filter="admin", extended=0, count=100)
    ids = items.get("items") or []
    if not ids:
        return None
    info = api(token, "groups.getById", group_ids=",".join(str(i) for i in ids))
    for g in info:
        if (g.get("name") or "").strip().lower() == title.lower():
            return int(g["id"])
    return None


def main() -> None:
    load_dotenv(ROOT / ".env")
    token = (os.getenv("VK_USER_TOKEN") or "").strip()
    if not token:
        print("VK_USER_TOKEN не задан в .env", file=sys.stderr)
        sys.exit(1)

    if not (ASSETS / "logo.png").is_file():
        import subprocess

        subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_vk_assets.py")], check=True)

    title = "ПланДом"
    desc = (
        "AI-планировка и обстановка квартир и домов. "
        "Бот в сообщениях: схема, визуализации комнат, PDF. "
        "Бесплатный пробник · тарифы от 399 ₽."
    )

    gid = find_existing_group(token, title)
    if gid:
        print(f"Сообщество уже есть: id={gid}")
    else:
        created = api(
            token,
            "groups.create",
            title=title,
            description=desc,
            type="group",
            subtype=1,
        )
        gid = int(created["id"])
        print(f"Создано сообщество: id={gid}")

    api(token, "groups.edit", group_id=gid, description=desc, website="https://github.com/smirn21/plandom-vk")
    try:
        api(token, "groups.setSettings", group_id=gid, messages=1, bots_enabled=1)
    except Exception as exc:
        print("groups.setSettings:", exc)

    upload_photo(token, gid, ASSETS / "logo.png")
    upload_cover(token, gid, ASSETS / "cover.png")

    posts = json.loads((ASSETS / "posts.json").read_text(encoding="utf-8"))
    for i, post in enumerate(posts):
        img = ASSETS / post["file"]
        att = upload_wall_photo(token, gid, img)
        api(
            token,
            "wall.post",
            owner_id=-gid,
            from_group=1,
            message=post["text"],
            attachments=att,
        )
        print(f"Пост {i + 1}/{len(posts)}")
        time.sleep(1.5)

    update_env(gid)
    print(f"\nГотово: https://vk.com/club{gid}")
    print(f"VK_GROUP_ID={gid} записан в .env")
    print(f"Токен бота: https://vk.com/club{gid}?act=tokens")


if __name__ == "__main__":
    main()
