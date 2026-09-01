#!/usr/bin/env python3
"""
Полная настройка VK «ПланДом» через сессию браузера Cursor.

1. Читает cookies из Cursor browser profile
2. Создаёт сообщество (если нет)
3. Публикует посты через web access_token
4. Обновляет .env (VK_GROUP_ID, VK_USER_TOKEN)

Для VK_BOT_TOKEN: подтвердите push на телефоне и запустите:
  python3 scripts/fetch_vk_bot_token.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets" / "vk"
ENV = ROOT / ".env"
COOKIE_DB = Path.home() / "Library/Application Support/Cursor/Partitions/cursor-browser/Cookies"
API = "https://api.vk.com/method"
V = "5.199"
TITLE = "ПланДом"


def load_cookies() -> list[dict]:
    tmp = Path(tempfile.mkdtemp()) / "Cookies"
    shutil.copy2(COOKIE_DB, tmp)
    conn = sqlite3.connect(tmp)
    rows = conn.execute(
        "SELECT host_key,name,value,path,expires_utc,is_secure,is_httponly,samesite "
        "FROM cookies WHERE host_key LIKE '%vk%'"
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


def update_env(**kwargs: str) -> None:
    text = ENV.read_text(encoding="utf-8") if ENV.is_file() else ""
    for key, val in kwargs.items():
        line = f"{key}={val}"
        if re.search(rf"^{re.escape(key)}=", text, re.M):
            text = re.sub(rf"^{re.escape(key)}=.*$", line, text, flags=re.M)
        else:
            text += f"\n{line}\n"
    ENV.write_text(text.strip() + "\n", encoding="utf-8")


def get_web_token(page) -> str | None:
    raw = page.evaluate(
        """() => {
          for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k && k.includes('web_token:login:auth')) return localStorage.getItem(k);
          }
          return null;
        }"""
    )
    if not raw:
        return None
    return json.loads(raw).get("access_token")


def vk_api(token: str, method: str, **params):
    params = {**params, "access_token": token, "v": V}
    r = httpx.post(f"{API}/{method}", data=params, timeout=90)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{method}: {data['error']}")
    return data["response"]


def create_group(page) -> str:
    page.goto("https://vk.ru/groups?act=edit&create=1&w=groups_create_new", timeout=90000)
    page.wait_for_timeout(4000)
    frame = page.frame(url=re.compile("community_create"))
    if not frame:
        raise RuntimeError("iframe community_create не найден")
    frame.get_by_role("textbox").first.fill(TITLE)
    frame.locator('[data-testid="thematic_select"]').click()
    page.wait_for_timeout(800)
    for opt in ["Дом, дача и ремонт", "Бизнес", "Другое"]:
        o = frame.get_by_text(opt, exact=False)
        if o.count():
            o.first.click()
            break
    page.wait_for_timeout(800)
    frame.get_by_role("button", name="Создать сообщество").click()
    page.wait_for_timeout(12000)
    m = re.search(r"club(\d+)", page.url)
    if m:
        return m.group(1)
    page.goto("https://vk.ru/groups?tab=admin")
    page.wait_for_timeout(3000)
    pl = page.get_by_text(TITLE, exact=True)
    if pl.count():
        pl.first.click()
        page.wait_for_timeout(4000)
        m = re.search(r"club(\d+)", page.url)
        if m:
            return m.group(1)
    raise RuntimeError("Не удалось создать/найти сообщество")


def fill_description(page, gid: str) -> None:
    page.goto(f"https://vk.ru/club{gid}?act=edit", timeout=90000)
    page.wait_for_timeout(3000)
    ta = page.locator("textarea")
    if ta.count() >= 2:
        ta.nth(1).fill(
            "AI-планировка и обстановка квартир и домов. "
            "Напишите боту «Начать» в сообщениях — схема + обстановка по комнатам. PDF в PRO."
        )
    save = page.get_by_role("button", name="Сохранить")
    if save.count():
        save.first.click()
        page.wait_for_timeout(3000)


def publish_posts(token: str, gid: int) -> None:
    posts = json.loads((ASSETS / "posts.json").read_text(encoding="utf-8"))
    for post in posts:
        vk_api(token, "wall.post", owner_id=-gid, from_group=1, message=post["text"])
        time.sleep(1.2)


def main() -> None:
    if not (ASSETS / "logo.png").is_file():
        import subprocess

        subprocess.run([sys.executable, str(ROOT / "scripts/generate_vk_assets.py")], check=True)

    cookies = load_cookies()
    results: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ru-RU")
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto("https://vk.ru/feed", timeout=90000)
        page.wait_for_timeout(3000)

        # existing group in .env?
        env = ENV.read_text(encoding="utf-8") if ENV.is_file() else ""
        m = re.search(r"^VK_GROUP_ID=(\d+)", env, re.M)
        if m:
            gid = m.group(1)
            print(f"Используем VK_GROUP_ID={gid}")
        else:
            gid = create_group(page)
            results["VK_GROUP_ID"] = gid
            print(f"Создано: club{gid}")

        fill_description(page, gid)
        token = get_web_token(page)
        browser.close()

    if token:
        results["VK_USER_TOKEN"] = token
        publish_posts(token, int(gid))
        print("Посты опубликованы")

    if results:
        update_env(**results)

    print(f"\nhttps://vk.com/club{gid}")
    print("Для VK_BOT_TOKEN: подтвердите push → python3 scripts/fetch_vk_bot_token.py")


if __name__ == "__main__":
    main()
