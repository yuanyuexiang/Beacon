"""Mocked customer / contact / message journey. No real pairing, credentials or sending."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import verify_detail_workspace_ui as f
from playwright.async_api import async_playwright, expect


async def main():
    contacts = [
        {**f.CONTACT, "id": "email1"},
        {**f.CONTACT, "id": "email2", "contact_ref": "manager@cafe.example"},
        {**f.CONTACT, "id": "facebook1", "channel": "facebook", "contact_ref": "https://facebook.com/testcafe"},
    ]
    drafts = {}
    active = {}
    messages = {c["id"]: [] for c in contacts}
    messages["email1"] = [
        {
            "id": "old1",
            "direction": "outbound",
            "channel": "email",
            "at": "2026-11-10T08:00:00Z",
            "arrived_at": "2026-11-10T08:00:00Z",
            "body": "Previous menu enquiry",
            "status": "sent",
            "source": "gmail",
            "deliveries": [],
        },
        {
            "id": "reply1",
            "direction": "inbound",
            "channel": "email",
            "at": "2026-11-10T08:05:00Z",
            "arrived_at": "2026-11-10T08:05:00Z",
            "body": "Please contact our manager.",
            "status": "reply",
            "source": "manual",
            "deliveries": [],
        },
    ]
    errors = []
    writes = []

    def context():
        c = f.context()
        c.update(contacts=contacts, tasks=[], drafts=[], contents=[])
        c["lead"]["name"] = "Test Cafe"
        c["progress"] = {"status": "waiting_reply"}
        return c

    def public(d):
        c = context()
        if d.get("piece"):
            c["contents"] = [d["piece"]]
        return {**d, "context": c, "blockers": []}

    async def handle(route):
        path = urlsplit(route.request.url).path
        method = route.request.method
        body = route.request.post_data_json if route.request.post_data else {}
        if method != "GET":
            writes.append((path, body))
        if path == "/api/batches":
            value = []
        elif path == "/api/communication/overview":
            value = {
                "total": 18,
                "items": [
                    {
                        "id": f.ID,
                        "name": "Test Cafe",
                        "postcode": "AB1 1AA",
                        "progress": {"status": "waiting_reply"},
                        "last_message": "Please contact our manager.",
                        "last_at": "2026-11-10T08:05:00Z",
                        "unread": 1,
                        "assigned_to": "ui",
                    }
                ],
            }
            value["items"].extend(
                [
                    {
                        "id": f"customer-{n}",
                        "name": ("LONG RESTAURANT AND COMMUNITY CENTRE " * 4) + str(n),
                        "postcode": "AB1 1AA",
                        "progress": {"status": "waiting_reply"},
                        "last_message": ("A very long customer message without convenient truncation. " * 70)
                        + ("X" * 800),
                        "last_at": "2026-11-10T08:05:00Z",
                        "unread": n % 3,
                        "assigned_to": "ui",
                    }
                    for n in range(17)
                ]
            )
        elif path == f"/api/communication/leads/{f.ID}":
            value = context()
        elif path == f"/api/communication/conversations/{f.ID}":
            value = {
                "items": [
                    {
                        "id": c["id"],
                        "channel": c["channel"],
                        "contact_ref": c["contact_ref"],
                        "unread": 0,
                        "read_through": None,
                        "messages": messages[c["id"]],
                    }
                    for c in contacts
                ]
            }
        elif path == "/api/communication/prepare":
            contact = body["eligibility_id"]
            if contact not in active:
                key = "draft" + str(len(drafts) + 1)
                d = {
                    "id": key,
                    "lead_id": f.ID,
                    "channel": body["channel"],
                    "execution_mode": body["execution_mode"],
                    "eligibility_id": contact,
                    "content_id": None,
                    "assigned_to": "ui",
                    "purpose": "message",
                    "status": "draft",
                    "queued": False,
                }
                drafts[key] = d
                active[contact] = key
            value = {"items": [{"lead_id": f.ID, "draft": public(drafts[active[contact]])}]}
        elif path.startswith("/api/communication/drafts/"):
            key = path.split("/")[4]
            d = drafts[key]
            if path.endswith("/message"):
                d["piece"] = {
                    "id": "piece-" + key,
                    "body_text": body["body_text"],
                    "subject": body["subject"],
                    "version": 1,
                    "approved": False,
                }
                d["content_id"] = d["piece"]["id"]
                value = public(d)
            elif path.endswith("/preview"):
                c = next(c for c in contacts if c["id"] == d["eligibility_id"])
                value = {
                    "preview_hash": "hash",
                    "issues": [],
                    "payload": {
                        "from": "alice@example.org",
                        "to": c["contact_ref"],
                        "subject": d["piece"]["subject"],
                        "body": d["piece"]["body_text"],
                        "mode": "gmail",
                    },
                }
            elif path.endswith("/confirm"):
                assert body["confirmed"] and body["preview_hash"] == "hash"
                d["status"] = "converted"
                del active[d["eligibility_id"]]
                messages[d["eligibility_id"]].append(
                    {
                        "id": "new-" + key,
                        "direction": "outbound",
                        "channel": d["channel"],
                        "at": "2026-11-10T09:00:00Z",
                        "arrived_at": "2026-11-10T09:00:00Z",
                        "body": d["piece"]["body_text"],
                        "subject": d["piece"]["subject"],
                        "status": "queued",
                        "source": "gmail",
                        "deliveries": [],
                    }
                )
                value = {"task_id": "task-new", "status": "ready", "message": "已提交发送"}
            else:
                if method == "PATCH":
                    d.update(body)
                value = public(d)
        elif path.endswith("/reply"):
            contact = path.split("/")[-2]
            messages[contact].append(
                {
                    "id": "manual-reply",
                    "direction": "inbound",
                    "channel": "email",
                    "at": "2026-11-10T10:00:00Z",
                    "arrived_at": "2026-11-10T10:00:00Z",
                    "body": body["summary"],
                    "status": "reply",
                    "source": "manual",
                    "deliveries": [],
                }
            )
            value = {"id": "manual-reply"}
        elif path == "/api/mobile/devices" or path.startswith("/api/mobile/notifications"):
            value = []
        else:
            await f.handle(route)
            return
        await route.fulfill(content_type="application/json", body=json.dumps(value))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1150})
        page.on("pageerror", lambda e: (errors.append(str(e)), print("PAGE ERROR", e)))
        await page.route("**/api/**", handle)
        await page.goto(os.environ.get("BEACON_UI_BASE", "http://localhost:3001") + f"/tasks?lead={f.ID}")
        await expect(page.get_by_text("Previous menu enquiry", exact=True)).to_be_visible()
        await expect(page.get_by_text("Please contact our manager.", exact=True).last).to_be_visible()
        await page.get_by_role("button", name="写消息／继续草稿").click()
        await page.get_by_role("textbox", name="文案内容", exact=True).fill("Hello, following up on my earlier note.")
        await page.get_by_role("textbox", name="邮件主题").fill("Menu follow-up")
        await expect(page.get_by_text("草稿已保存", exact=True)).to_be_visible()
        # Two addresses on the same channel retain independent drafts.
        await page.locator(".conversation-toolbar .ant-select-selector").click()
        await page.get_by_text("邮件 · manager@cafe.example", exact=True).click()
        await page.get_by_role("button", name="写消息／继续草稿").click()
        await expect(page.get_by_role("textbox", name="文案内容", exact=True).last).to_have_value("")
        await page.locator(".conversation-toolbar .ant-select-selector").click()
        await page.get_by_text("邮件 · hello@cafe.example", exact=True).click()
        await expect(page.get_by_role("textbox", name="文案内容", exact=True).first).to_have_value(
            "Hello, following up on my earlier note."
        )
        await page.get_by_role("button", name="预览邮件", exact=True).first.click()
        await page.get_by_role("checkbox").check()
        await page.get_by_role("button", name="确认发送", exact=True).click()
        await expect(page.get_by_text("排队中", exact=True)).to_be_visible()
        # Confirmation automatically starts a fresh composer while preserving the previous send.
        await expect(page.get_by_role("textbox", name="文案内容", exact=True).first).to_have_value("")
        await page.get_by_role("button", name="记录回复", exact=True).click()
        await page.get_by_label("回复原文／备注").fill("Thanks, our manager will get back to you.")
        await page.get_by_role("button", name="保存回复", exact=True).click()
        await expect(page.get_by_text("Thanks, our manager will get back to you.", exact=True)).to_be_visible()
        await page.locator(".conversation-toolbar .ant-select-selector").click()
        await page.get_by_text("Facebook · https://facebook.com/testcafe", exact=True).click()
        await page.get_by_role("button", name="写消息／继续草稿").click()
        await expect(page.get_by_role("radio", name="手机触达")).to_be_checked()
        await page.get_by_role("radio", name="人工触达").click()
        await expect(page.get_by_role("radio", name="人工触达")).to_be_checked()
        await expect(
            page.get_by_text("复制消息，打开对方主页后自行粘贴发送。不需要连接手机或配置社媒 API。", exact=True)
        ).to_be_visible()
        await page.get_by_role("textbox", name="文案内容", exact=True).last.fill(
            "Hello from our Facebook conversation."
        )
        await expect(page.get_by_text("草稿已保存", exact=True).last).to_be_visible()
        await page.locator(".conversation-toolbar .ant-select-selector").click()
        await page.get_by_text("邮件 · hello@cafe.example", exact=True).click()
        await expect(page.get_by_role("textbox", name="文案内容", exact=True).first).to_have_value("")
        await page.get_by_role("button", name="客户资料", exact=True).click()
        out = Path("data/devchecks/customer-conversations")
        out.mkdir(parents=True, exist_ok=True)
        for width in [1440, 1920]:
            await page.set_viewport_size({"width": width, "height": 1100})
            await page.wait_for_timeout(200)
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "页面被长消息撑宽"
            assert await page.locator(".customer-list").evaluate("el => el.getBoundingClientRect().height < 900"), (
                "客户列表必须内部滚动"
            )
        await page.screenshot(path=str(out / "desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 850, "height": 1100})
        await page.wait_for_timeout(200)
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "窄屏横向溢出"
        await page.screenshot(path=str(out / "narrow.png"), full_page=True)
        assert not errors, errors
        assert len([x for x in writes if x[0].endswith("/confirm")]) == 1
        assert all(not path.endswith("/send") for path, _ in writes)
        await browser.close()
    print("PASS: per-contact drafts, history, preview-confirm-next message, reply, responsive layout; APIs mocked")


if __name__ == "__main__":
    asyncio.run(main())
