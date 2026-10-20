"""已有结果展示与显式刷新回归：所有 API 模拟，无真实 Google／AI 调用。"""

import asyncio
import json
import re
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

ID = "11111111-1111-4111-8111-111111111111"
writes = []
errors = []


async def handle(route):
    path = urlsplit(route.request.url).path
    if route.request.method != "GET":
        writes.append(path)
    if path.endswith("/menu-workspace"):
        data = {"assets": [], "analyses": {}}
    elif path == "/api/communication/assignees":
        data = []
    elif path.startswith("/api/communication/leads/"):
        data = {"lead": {"id": ID, "name": "Mock restaurant"}, "contacts": [], "contents": [], "analyses": [], "tasks": [], "drafts": [], "progress": {"status": "not_started"}}
    elif path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": "admin", "must_change_password": False}
    elif path == f"/api/leads/{ID}":
        data = {
            "id": ID,
            "name": "Reuse Cafe",
            "source_key": "fsa:1",
            "website": "https://cafe.test",
            "screening_class": "candidate",
            "entity_status": "unknown",
        }
    elif path.endswith(("/assets", "/content", "/eligibility")):
        data = []
    elif path.endswith("/auto-research"):
        data = {"configured": False, "run": None}
    elif path.endswith("/maps-menu"):
        data = {"configured": False, "worker_online": False, "run": None}
    elif path.endswith("/google-places"):
        data = {
            "configured": True,
            "attempts_today": 1,
            "daily_limit": 200,
            "link": {
                "place_id": "test",
                "version": "v1",
                "reviewed_by": "AI+官网证据",
                "reviewed_at": "2026-10-20T00:00:00Z",
            },
            "saved_review": {
                "status": "verified",
                "google_status": "completed",
                "reason": "Google 候选通过官网原文核验",
                "checked_at": "2026-10-20T00:00:00Z",
                "website_changed": False,
            },
        }
    elif path.endswith("/menu-candidates"):
        data = {"website": "https://cafe.test", "pages": [], "candidates": [], "notice": "本次官网菜单查找结果"}
    elif path.endswith("/contact-review"):
        data = {"website": None, "candidates": [], "notice": "", "ai": {"status": "completed", "reason": "核验完成"}}
    else:
        errors.append(path)
        data = {}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1700, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{ID}")
        await page.get_by_role("tab", name="来源与历史", exact=True).click()
        await page.get_by_text("补充来源与查询工具", exact=True).click()
        await expect(page.get_by_text("已读取完善名单的核验记录", exact=True)).to_be_visible()
        await expect(page.get_by_role("button", name="获取实时价格与照片", exact=True)).to_be_visible()
        assert not writes
        for removed in ("经营主体", "主体证据", "查 Companies House"):
            await expect(page.get_by_text(removed, exact=True)).to_have_count(0)
        for entry, title, refresh, suffix in [
            ("查找官网菜单", "官网菜单候选", "重新查找官网菜单", "/menu-candidates"),
            ("查找联系方式", "联系方式 · AI 推荐", "重新查找并核验联系方式", "/contact-review"),
        ]:
            await page.get_by_role("tab", name="菜单资料" if suffix == "/menu-candidates" else "销售准备", exact=True).click()
            await page.get_by_role("button", name=entry, exact=True).click()
            dialog = page.get_by_role("dialog", name=title, exact=True)
            await expect(dialog).to_be_visible()
            await expect(dialog.get_by_role("button", name=refresh, exact=True)).not_to_have_class(
                re.compile("ant-btn-loading")
            )
            assert sum(x.endswith(suffix) for x in writes) == 1
            await dialog.get_by_role("button", name="Close", exact=True).click()
            await expect(dialog).not_to_be_visible()
            await page.get_by_role(
                "button", name="查看官网菜单候选" if suffix == "/menu-candidates" else entry, exact=True
            ).click()
            await expect(dialog).to_be_visible()
            assert sum(x.endswith(suffix) for x in writes) == 1
            await dialog.get_by_role("button", name=refresh, exact=True).click()
            await expect(dialog.get_by_role("button", name=refresh, exact=True)).not_to_have_class(
                re.compile("ant-btn-loading")
            )
            assert sum(x.endswith(suffix) for x in writes) == 2
            await dialog.get_by_role("button", name="Close", exact=True).click()
            await expect(dialog).not_to_be_visible()
        assert not errors, errors
        assert not any("google-places" in x for x in writes)
        await browser.close()
        print("Saved Google metadata, menu/contact reopen and explicit refresh passed")


asyncio.run(main())
