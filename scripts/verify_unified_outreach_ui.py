"""Unified contact selection and manual social workflow; all API calls mocked."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
import verify_detail_workspace_ui as f


async def main():
    mode = "mobile"
    calls, errors = [], []
    f.CONTACT.update(id="fb1", channel="facebook", contact_ref="https://facebook.com/mock_shop", eligibility="allowed")
    original = f.draft
    f.draft = lambda: {**original(), "channel": f.CONTACT["channel"], "execution_mode": mode}

    async def handle(route):
        nonlocal mode
        path = urlsplit(route.request.url).path
        body = route.request.post_data_json if route.request.post_data else {}
        method = route.request.method
        if path == "/api/communication/prepare":
            mode = body["execution_mode"]
            f.chosen_contact, f.created_draft = f.CONTACT["id"], True
            value = {"items": [{"lead_id": f.ID, "draft": f.draft()}]}
        elif path == "/api/mobile/devices":
            value = []  # Manual execution must work with no phone or API credentials.
        elif path.endswith("/outreach-message"):
            f.piece = {"id": "message1", "version": 1, "body_text": "Hello, could you share your menu?", "subject": "", "approved": False}
            value = f.piece
        elif path.endswith("/draft1/message"):
            f.piece.update(body_text=body["body_text"], subject=body["subject"])
            value = f.draft()
        elif path.endswith("/draft1") and method == "PATCH":
            mode = body.get("execution_mode", mode)
            f.selected_content = body.get("content_id", f.selected_content)
            value = f.draft()
        elif path.endswith("/draft1/preview"):
            assert mode == "manual" and body == {}
            value = {"issues": [], "preview_hash": "a"*64, "payload": {"mode": mode, "from": "", "to": f.CONTACT["contact_ref"], "subject": "", "body": f.piece["body_text"]}}
        elif path.endswith("/draft1/confirm"):
            assert body == {"preview_hash": "a"*64, "confirmed": True}
            calls.append("confirmed")
            value = {"task_id": "task1", "status": "manual", "message": "已准备好，请打开联系入口并在完成后记录结果"}
        elif path.endswith("/task1/manual-open"):
            value = {"url": f.CONTACT["contact_ref"], "text": f.piece["body_text"]}
        elif path.endswith("/task1/sent"):
            assert body["sent_at"]
            calls.append("sent")
            value = {}
        else:
            await f.handle(route)
            return
        await route.fulfill(content_type="application/json", body=json.dumps(value))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(viewport={"width":1500,"height":1050}, permissions=["clipboard-read", "clipboard-write"])
        page = await context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"{os.environ.get('BEACON_UI_URL', 'http://localhost:3000')}/leads/{f.ID}")
        await expect(page.get_by_text("请从左侧选择一个联系方式", exact=False)).to_be_visible()
        assert await page.get_by_role("combobox", name="触达渠道", exact=True).count() == 0
        await page.get_by_role("button", name="准备触达", exact=True).click()
        await expect(page.get_by_label("当前收件人")).to_contain_text(f.CONTACT["contact_ref"])
        assert await page.get_by_role("combobox", name="收件人", exact=True).count() == 0
        await page.get_by_role("button", name="AI 起草消息", exact=True).click()
        editor = page.get_by_label("文案内容", exact=True)
        await editor.fill("Edited message for this restaurant")
        await page.get_by_role("radio", name="人工触达", exact=True).click()
        await expect(page.get_by_role("radio", name="人工触达", exact=True)).to_be_checked()
        await expect(editor).to_have_value("Edited message for this restaurant")
        await expect(page.get_by_role("combobox", name="执行手机", exact=True)).to_have_count(0)
        await page.get_by_role("radio", name="手机触达", exact=True).click()
        await expect(page.get_by_role("radio", name="手机触达", exact=True)).to_be_checked()
        await expect(editor).to_have_value("Edited message for this restaurant")
        await page.get_by_role("radio", name="人工触达", exact=True).click()
        await expect(page.get_by_role("radio", name="人工触达", exact=True)).to_be_checked()
        out = Path("data/devchecks"); out.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out / "unified-outreach-manual-editor.png"), full_page=True)
        await page.get_by_role("button", name="预览人工触达", exact=True).click()
        dialog = page.get_by_role("dialog", name="确认联系内容", exact=True)
        await dialog.get_by_role("checkbox").check()
        await dialog.get_by_role("button", name="确认并准备联系", exact=True).click()
        await expect(page.get_by_role("button", name="复制消息", exact=True)).to_be_visible()
        await page.get_by_role("button", name="复制消息", exact=True).click()
        assert await page.evaluate("navigator.clipboard.readText()") == "Edited message for this restaurant"
        await expect(page.get_by_role("link", name="打开 Facebook 主页", exact=True)).to_have_attribute("href", f.CONTACT["contact_ref"])
        assert calls == ["confirmed"]
        await page.get_by_role("button", name="已发送，记录结果", exact=True).click()
        await page.get_by_role("button", name="还未发送", exact=True).click()
        assert calls == ["confirmed"]
        await page.get_by_role("button", name="已发送，记录结果", exact=True).click()
        await page.get_by_role("button", name="确认已实际发送", exact=True).click()
        await expect(page.get_by_text("已记录人工发送，可在沟通记录查看回复与跟进", exact=True)).to_be_visible()
        assert calls == ["confirmed", "sent"] and not errors, (calls, errors)
        await browser.close()
        print("PASS: one contact selector, manual/mobile switch preserves edits; copy/open do not mark sent; explicit result recorded")


asyncio.run(main())
