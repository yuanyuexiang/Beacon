"""Detail contact to one phone confirmation. All API traffic is mocked."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
import verify_detail_workspace_ui as f


async def main():
    f.CONTACT.update(id="fb1", channel="facebook", contact_ref="https://facebook.com/mock_shop", eligibility="allowed")
    f.created_draft = False
    calls, errors = [], []
    original = f.draft
    f.draft = lambda: {**original(), "channel": "facebook", "execution_mode": "mobile"}

    async def handle(route):
        path = urlsplit(route.request.url).path
        body = route.request.post_data_json if route.request.post_data else {}
        if path == "/api/communication/prepare":
            assert body["execution_mode"] == "mobile" and body["eligibility_id"] == "fb1"
            f.chosen_contact, f.created_draft = "fb1", True
            value = {"items": [{"lead_id": f.ID, "draft": f.draft()}]}
        elif path == "/api/mobile/devices":
            value = [{"id": "phone1", "label": "My phone", "status": "ready", "online": True, "capabilities": {"protocol": 2, "installed": ["facebook"], "accounts": {}}}]
        elif path.endswith("/outreach-message"):
            assert body["channel"] == "facebook" and body["eligibility_id"] == "fb1"
            f.piece = {"id": "message1", "version": 1, "body_text": "Hello, could you share your menu?", "subject": "", "approved": False}
            value = f.piece
        elif path.endswith("/draft1/preview"):
            assert body == {"device_id": "phone1", "action": "direct_message"}
            calls.append("preview")
            value = {"issues": [], "preview_hash": "a" * 64, "payload": {"from": "", "to": f.CONTACT["contact_ref"], "body": f.piece["body_text"], "subject": "", "mode": "mobile", "mobile_context": {"device_id": "phone1", "device_label": "My phone", "payload": {"sender": "Facebook 当前登录账号", "action": "direct_message"}}}}
        elif path.endswith("/draft1/confirm"):
            assert body == {"device_id": "phone1", "action": "direct_message", "preview_hash": "a" * 64, "confirmed": True}
            calls.append("confirm")
            value = {"task_id": "task1", "job_id": "job1", "status": "mobile_queued", "message": "已交给手机，尚未发送"}
        else:
            await f.handle(route)
            return
        await route.fulfill(content_type="application/json", body=json.dumps(value))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1050})
        page.on("pageerror", lambda e: (errors.append(str(e)), print("PAGE ERROR", str(e), flush=True)))
        await page.route("**/api/**", handle)
        await page.goto(f"{os.environ.get('BEACON_UI_URL', 'http://localhost:3000')}/leads/{f.ID}")
        await page.get_by_role("button", name="准备触达", exact=True).click()
        await expect(page.get_by_role("combobox", name="执行手机")).to_be_visible()
        await page.get_by_role("button", name="AI 起草消息", exact=True).click()
        await expect(page.get_by_label("文案内容")).to_have_value("Hello, could you share your menu?")
        await expect(page.get_by_text("草稿已保存", exact=True)).to_be_visible()
        await page.get_by_role("button", name="预览手机触达", exact=True).click()
        await expect(page.get_by_role("dialog")).to_contain_text("My phone")
        await expect(page.get_by_role("dialog")).to_contain_text("https://facebook.com/mock_shop")
        await page.screenshot(path="data/devchecks/mobile-outreach-preview.png", full_page=True)
        await page.get_by_role("checkbox").last.check()
        await page.get_by_role("button", name="确认并交给手机", exact=True).click()
        await expect(page.get_by_text("已交给手机，尚未发送", exact=True)).to_be_visible()
        await expect(page.get_by_role("dialog")).not_to_be_visible()
        assert calls == ["preview", "confirm"] and not errors, (calls, errors)
        out = Path("data/devchecks/mobile-outreach-journey.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out), full_page=True)
        await browser.close()
        print("PASS: contact → AI message → one phone preview → queued; no real sends")


asyncio.run(main())
