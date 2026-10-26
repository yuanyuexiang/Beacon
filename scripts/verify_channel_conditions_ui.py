"""Mocked channel review and preparation todo UI; no real contact or sending."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import verify_detail_workspace_ui as fixture
from app.modules.sales.channel_conditions import REQUIREMENTS, requirements
from playwright.async_api import async_playwright, expect


async def main():
    fixture.created_draft = True
    fixture.chosen_contact = "email1"
    fixture.CONTACT.update(eligibility="unknown")
    fixture.state = "preparing"
    queued = False
    current_channel = "email"
    saved = None
    calls, errors = [], []
    original = fixture.draft

    def draft():
        return {**original(), "queued": queued}

    fixture.draft = draft

    async def handle(route):
        nonlocal queued, saved
        path = urlsplit(route.request.url).path
        method = route.request.method
        calls.append((path, method))
        if path.endswith("/conditions"):
            if method == "POST":
                saved = route.request.post_data_json
            value = {
                "requirements": REQUIREMENTS[current_channel],
                "reply_requirements": requirements(current_channel, "requested_reply"),
                "record": saved,
                "missing": [],
                "execution": "API 权限和会话窗口在执行前单独检查",
                "legacy": saved is None,
            }
        elif path == "/api/communication/drafts/draft1":
            if method == "PATCH":
                queued = route.request.post_data_json.get("queued", queued)
            value = draft()
        elif path == "/api/batches":
            value = []
        elif path == "/api/communication/overview":
            value = {
                "items": [
                    {
                        "id": fixture.ID,
                        "name": "Audit Cafe",
                        "postcode": "AB1",
                        "progress": {"status": "preparing", "draft_id": "draft1"},
                    }
                ]
                if queued
                else [],
                "total": int(queued),
            }
        elif path.endswith(f"/activity/{fixture.ID}"):
            value = {"timeline": [], "deliveries": [], "conversations": []}
        else:
            await fixture.handle(route)
            return
        await route.fulfill(content_type="application/json", body=json.dumps(value))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1100})
        page.on("pageerror", lambda e: (errors.append(str(e)), print("PAGE ERROR:", e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{fixture.ID}")
        await expect(page.get_by_role("button", name="创建就绪任务（0）", exact=True)).to_be_disabled()
        await page.get_by_role("button", name="加入准备待办", exact=True).click()
        await expect(page.get_by_role("button", name="移出准备待办", exact=True)).to_be_visible()
        # All channel forms use one component and their own requirements.
        for current_channel in REQUIREMENTS:
            await page.reload()
            await page.get_by_role("button", name="核验与设置", exact=True).first.click()
            await page.get_by_role("button", name="联系条件", exact=True).filter(visible=True).first.click()
            modal = page.get_by_role("dialog", name="核对本次业务联系条件")
            for r in REQUIREMENTS[current_channel]:
                await expect(modal.get_by_text(r["label"], exact=True)).to_be_visible()
            await modal.get_by_text("待补充依据", exact=True).click()
            await page.get_by_text("依据已核对", exact=True).last.click()
            await modal.get_by_text("核对本次业务联系条件", exact=True).click()
            await expect(modal.get_by_role("button", name="保存核对结果", exact=True)).to_be_disabled()
            if current_channel == "phone":
                Path("data/devchecks").mkdir(parents=True, exist_ok=True)
                await page.screenshot(path="data/devchecks/channel-phone-conditions.png")
            await modal.get_by_role("button", name="Close", exact=True).click()
        await page.goto(f"http://localhost:3000/tasks?lead={fixture.ID}")
        await expect(page.get_by_text("邮件 · 准备待办", exact=True)).to_be_visible()
        await expect(page.get_by_role("link", name="继续准备", exact=True)).to_be_visible()
        await page.screenshot(path="data/devchecks/channel-preparation-todo.png")
        await page.get_by_role("button", name="移出待办", exact=True).click()
        assert not queued
        assert not any("/send" in path or "/activate" in path for path, _ in calls)
        assert not errors and not fixture.errors, (errors, fixture.errors)
        await browser.close()
    print("PASS: channel-specific evidence, no unconfirmed approval, incomplete todo add/list/remove, no sending")


asyncio.run(main())
