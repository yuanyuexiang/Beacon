"""All API responses mocked. Never authorizes a real message."""

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import verify_detail_workspace_ui as f
from playwright.async_api import async_playwright, expect


async def main():
    f.created_draft = True
    f.chosen_contact = "email1"
    f.CONTACT.update(eligibility="allowed")
    f.state = "preparing"
    f.piece = {
        "id": "message1",
        "version": 1,
        "body_text": "Hello, could you share your menu?\nAlice\nPlease let us know to opt out.",
        "subject": "Menu enquiry",
        "approved": False,
        "mode": "menu_inquiry",
    }
    f.selected_content = "message1"
    original = f.draft
    f.draft = lambda: {**original(), "execution_mode": "gmail"}
    actions = []
    issues = []
    errors = []

    async def handle(route):
        nonlocal issues
        path = urlsplit(route.request.url).path
        body = route.request.post_data_json if route.request.post_data else {}
        if path.endswith("/auto-admission"):
            actions.append("research")
            issues = []
            value = {}
        elif path.endswith("/message") and route.request.method == "PUT":
            f.piece = {
                **f.piece,
                "body_text": body["body_text"],
                "subject": body["subject"],
            }
            value = f.draft()
            actions.append("save")
        elif path.endswith("/draft1/preview"):
            value = {
                "issues": issues,
                "preview_hash": "a" * 64,
                "payload": {
                    "to": "hello@cafe.example",
                    "from": "alice@example.org",
                    "subject": f.piece["subject"],
                    "body": f.piece["body_text"],
                    "mode": "gmail",
                },
            }
            actions.append("preview")
        elif path.endswith("/draft1/confirm"):
            assert body["confirmed"] and body["preview_hash"] == "a" * 64
            value = {
                "task_id": "task1",
                "status": "ready",
                "message": "已提交发送，请在沟通记录查看结果",
            }
            actions.append("confirm")
        else:
            await f.handle(route)
            return
        await route.fulfill(content_type="application/json", body=json.dumps(value))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1050})
        page.on("pageerror", lambda e: (errors.append(str(e)), print("PAGE ERROR:", e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{f.ID}")
        await expect(
            page.get_by_role("button", name=re.compile("预览并发送$"))
        ).to_be_visible()
        for label in [
            "保存并检查草稿",
            "重新核验准入",
            "重新检查创建条件",
            "确认消息内容",
        ]:
            await expect(
                page.get_by_role("button", name=label, exact=True)
            ).to_have_count(0)
        await page.get_by_label("邮件主题", exact=True).fill("New menu enquiry")
        await expect(page.get_by_text("草稿已保存", exact=True)).to_be_visible()
        assert "save" in actions
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/simple-send-editor.png")
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.get_by_label("邮件主题", exact=True).scroll_into_view_if_needed()
        await page.screenshot(path="data/devchecks/simple-send-mobile.png")
        await page.set_viewport_size({"width": 1500, "height": 1050})
        await page.get_by_role("button", name=re.compile("预览并发送$")).click()
        dialog = page.get_by_role("dialog", name="确认发送", exact=True)
        await expect(dialog).to_be_visible()
        await expect(
            dialog.get_by_role("button", name="确认发送", exact=True)
        ).to_be_disabled()
        assert "confirm" not in actions
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.wait_for_timeout(350)
        await page.screenshot(path="data/devchecks/simple-send-preview.png")
        await dialog.get_by_role("button", name="Close").click()
        assert "confirm" not in actions
        issues = ["尚缺职务邮箱说明；缺少公司订户证据"]
        await page.get_by_role("button", name=re.compile("预览并发送$")).click()
        await expect(
            page.get_by_role("button", name="补充确认", exact=True)
        ).to_be_visible()
        await expect(
            page.get_by_text("尚缺职务邮箱说明；缺少公司订户证据", exact=True)
        ).not_to_be_visible()
        await page.screenshot(path="data/devchecks/simple-send-blocker.png")
        issues = ["缺少该联系方式属于目标门店的原文证据"]
        await page.get_by_role("button", name=re.compile("预览并发送$")).click()
        await expect(
            page.get_by_role("button", name="AI 补查联系方式", exact=True)
        ).to_be_visible()
        await page.get_by_role("button", name="AI 补查联系方式", exact=True).click()
        await expect(dialog).to_be_visible()
        assert actions.count("research") == 1
        await dialog.get_by_role("button", name="Close").click()
        issues = []
        await expect(
            page.get_by_role("button", name=re.compile("预览并发送$"))
        ).to_be_visible()
        await page.get_by_role("button", name=re.compile("预览并发送$")).click()
        await dialog.get_by_role("checkbox").check()
        await dialog.get_by_role("button", name="确认发送", exact=True).click()
        await expect(
            page.get_by_text("已提交发送，请在沟通记录查看结果", exact=True)
        ).to_be_visible()
        assert actions.count("confirm") == 1
        assert not errors, errors
        await browser.close()
    print(
        "PASS: autosave, one primary action, one blocker action, preview cancel, explicit final confirmation; mocked only"
    )


asyncio.run(main())
