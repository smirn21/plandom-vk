#!/usr/bin/env python3
"""Достать VK_BOT_TOKEN после подтверждения push на телефоне."""
from __future__ import annotations

import re
import sqlite3
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
GID = None  # auto from .env


def load_cookies() -> list[dict]:
    db = Path.home() / "Library/Application Support/Cursor/Partitions/cursor-browser/Cookies"
    tmp = Path(tempfile.mkdtemp()) / "Cookies"
    shutil.copy2(db, tmp)
    conn = sqlite3.connect(tmp)
    rows = conn.execute(
        "SELECT host_key,name,value,path,expires_utc,is_secure,is_httponly,samesite FROM cookies WHERE host_key LIKE '%vk%'"
    ).fetchall()
    conn.close()
    out = []
    for host, name, value, path, exp, sec, http, samesite in rows:
        if not value:
            continue
        c = {
            "name": name,
            "value": value,
            "domain": host,
            "path": path or "/",
            "secure": bool(sec),
            "httpOnly": bool(http),
        }
        if exp and exp > 0:
            c["expires"] = exp / 1_000_000 - 11644473600
        c["sameSite"] = {0: "Lax", 1: "Strict", 2: "None"}.get(samesite, "Lax")
        out.append(c)
    return out


def main() -> None:
    from playwright.sync_api import sync_playwright

    env_text = ENV.read_text(encoding="utf-8") if ENV.is_file() else ""
    m = re.search(r"^VK_GROUP_ID=(\d+)", env_text, re.M)
    if not m:
        print("VK_GROUP_ID не задан в .env")
        return
    gid = m.group(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies(load_cookies())
        page = ctx.new_page()
        page.goto(f"https://vk.ru/club{gid}?act=tokens", timeout=90000)
        page.wait_for_timeout(5000)

        if "Подтверждение действия" in page.content():
            print("Подтвердите push на iPhone, затем нажмите «Создать ключ» снова в браузере.")
            input("После подтверждения нажмите Enter…")

        page.locator("button.FlatButton--primary", has_text="Создать").first.click(force=True)
        page.wait_for_timeout(2000)
        box = page.locator("#box_layer")
        for perm in ["Сообщения сообщества", "Управление сообществом", "Фото", "Документы"]:
            loc = box.get_by_text(perm, exact=False)
            if loc.count():
                loc.first.click()
        box.get_by_role("button", name=re.compile("Создать|Сохранить")).last.click(force=True)
        page.wait_for_timeout(4000)

        html = page.content()
        tm = re.search(r"(vk1\.a\.[A-Za-z0-9_\-]{50,})", html)
        if not tm:
            print("Токен не найден — скопируйте вручную со страницы")
            browser.close()
            return

        token = tm.group(1)
        env_text = re.sub(r"^VK_BOT_TOKEN=.*$", f"VK_BOT_TOKEN={token}", env_text, flags=re.M)
        if "VK_BOT_TOKEN=" not in env_text:
            env_text += f"\nVK_BOT_TOKEN={token}\n"
        ENV.write_text(env_text.strip() + "\n", encoding="utf-8")
        print(f"VK_BOT_TOKEN записан в .env")
        browser.close()


if __name__ == "__main__":
    main()
