"""Mocked readiness loop: stale admission -> recheck -> create, no real sends."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect
import verify_detail_workspace_ui as fixture

async def main():
    fixture.created_draft = True
    fixture.state = "preparing"
    fixture.chosen_contact = fixture.CONTACT["id"]
    fixture.selected_content = "content1"
    fixture.piece = dict(id="content1", version=1, mode="menu_inquiry", subject="Menu enquiry", body_text="Could you share a menu?\nTom", approved=True, approval_valid=True, kind="message_short", reason=None)
    blocked = True
    calls, errors = [], []
    original = fixture.draft
    def draft():
        d = original()
        if blocked:
            d["blockers"].append("自动准入规则已更新，请重新核验")
        return d
    fixture.draft = draft
    async def handle(route):
        nonlocal blocked
        path = urlsplit(route.request.url).path
        calls.append((path, route.request.method))
        if path.endswith("/auto-admission"):
            blocked = False
            await route.fulfill(content_type="application/json", body=json.dumps(dict(summary=dict(allowed=1,unknown=0,blocked=0))))
        elif path.endswith("/activate") and sum(p.endswith("/activate") for p, _ in calls) == 1:
            await route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "状态已变化，请重新检查"}))
        else:
            await fixture.handle(route)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport=dict(width=1500,height=1100))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{fixture.ID}")
        await expect(page.get_by_role("button", name="创建就绪任务（0）", exact=True)).to_be_disabled()
        await page.get_by_role("button", name="重新检查创建条件", exact=True).click()
        await expect(page.get_by_role("button", name="创建就绪任务（0）", exact=True)).to_be_disabled()
        await page.get_by_role("button", name="重新核验准入", exact=True).click()
        await expect(page.get_by_role("button", name="创建就绪任务（1）", exact=True)).to_be_enabled()
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.get_by_role("button", name="创建就绪任务（1）", exact=True).scroll_into_view_if_needed()
        await page.wait_for_timeout(400)
        await page.screenshot(path="data/devchecks/outreach-ready.png")
        await page.get_by_role("button", name="创建就绪任务（1）", exact=True).click()
        await expect(page.get_by_text("状态已变化，请重新检查", exact=True)).to_be_visible()
        await expect(page.get_by_role("textbox", name="文案内容", exact=True)).to_be_visible()
        await page.get_by_role("button", name="保存并检查草稿", exact=True).click()
        await expect(page.get_by_role("button", name="创建就绪任务（1）", exact=True)).to_be_enabled()
        await page.get_by_role("button", name="创建就绪任务（1）", exact=True).click()
        await expect(page.get_by_role("link", name="进入本次触达工作台 →", exact=True)).to_be_visible()
        assert sum(path.endswith("/activate") and method == "POST" for path,method in calls) == 2
        assert sum(path.endswith("/drafts/draft1") and method == "GET" for path,method in calls) >= 2
        assert not any("/send" in path for path,_ in calls)
        assert not errors and not fixture.errors, (errors, fixture.errors)
        await browser.close()
    print("PASS: blocked status explained, readonly recheck, direct admission refresh, readiness update, task creation without sending")
asyncio.run(main())
