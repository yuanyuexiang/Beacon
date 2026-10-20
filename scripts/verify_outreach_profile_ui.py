"""AI service profile UI: mock APIs only, no actual credentials or external requests."""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect


async def main():
    profile = {"version": "initial", "company": "", "services": "", "proof": "", "constraints": ""}
    role = "admin"
    writes = []

    async def handle(route):
        nonlocal profile
        request = route.request
        if request.url.endswith("/api/auth/me"):
            data = {"id": "ui", "username": "ui", "role": role, "must_change_password": False}
        elif request.url.endswith("/api/outreach-profile"):
            if request.method == "PUT":
                profile = {**request.post_data_json, "version": "saved"}
                writes.append(profile)
            data = profile
        else:
            await route.fulfill(status=503, content_type="application/json", body='{"detail":"模拟未配置"}')
            return
        await route.fulfill(content_type="application/json", body=json.dumps(data))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/settings")
        await page.get_by_label("公司／品牌介绍", exact=True).fill("Test Menu Studio")
        await page.get_by_label("菜单设计与印刷服务", exact=True).fill("Menu layout design and printed menus. Ask about requirements.")
        await page.get_by_role("button", name="保存服务资料", exact=True).click()
        await expect(page.get_by_text("服务资料已保存", exact=True)).to_be_visible()
        assert len(writes) == 1
        await page.reload()
        await expect(page.get_by_label("公司／品牌介绍", exact=True)).to_have_value("Test Menu Studio")
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/outreach-profile-settings.png", full_page=True)
        role = "member"
        await page.reload()
        await expect(page.get_by_text("此页面仅限管理员使用", exact=True)).to_be_visible()
        await expect(page.get_by_role("button", name="保存服务资料", exact=True)).to_have_count(0)
        assert len(writes) == 1
        await browser.close()
        print("Service profile UI passed: admin save, reload, read-only member; no external requests")


asyncio.run(main())
