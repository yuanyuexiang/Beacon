"""无菜单询问触达界面回归：全部 API 模拟，不写真实客户、不发送消息。"""

import asyncio
import copy
import json
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

LEAD = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
DRAFT = "33333333-3333-4333-8333-333333333333"
TASK = "44444444-4444-4444-8444-444444444444"
piece = None
selected_content = None
requests = []
errors = []
task = None
replied = False


def context(identity=LEAD):
    return {
        "lead": {"id": identity, "name": "Alpha Restaurant" if identity == LEAD else "Beta Cafe", "postcode": "AB1", "website": "https://example.com", "address": "1 Test Road"},
        "contacts": [{"id": "eligibility", "channel": "email", "contact_ref": "info@example.com", "contact_source": "官网", "contact_usable": "valid", "eligibility": "allowed", "suppressed": False}],
        "contents": [piece] if piece else [],
        "analyses": [], "tasks": [task] if task and identity == LEAD else [],
        "progress": {"status": "replied" if replied else "pending" if task else "not_started", "task_id": TASK if task else None},
        "drafts": [],
    }


def draft(identity):
    return {"id": DRAFT if identity == LEAD else OTHER, "lead_id": identity, "channel": "email", "execution_mode": "manual", "eligibility_id": "eligibility", "content_id": selected_content, "assigned_to": "ui-test", "follow_up_at": None, "purpose": "initial", "notes": None, "status": "draft", "task_id": None, "blockers": [] if piece and piece["approved"] else ["尚未准备已审批文案"], "context": context(identity)}


async def handle(route):
    global task, replied, piece, selected_content
    request = route.request
    path = urlsplit(request.url).path
    body = request.post_data_json if request.post_data and request.method in {"POST", "PATCH"} else None
    requests.append((request.method, path, body))
    if path == "/api/auth/me":
        result = {"id": "ui", "username": "ui-test", "role": "admin", "display_name": None, "must_change_password": False}
    elif path == "/api/batches":
        result = [{"id": "batch", "batch_key": "测试", "country": "UK", "region": "Aberdeen", "source_name": "fsa", "candidate_count": 2}]
    elif path == "/api/leads":
        result = [{"id": i, "name": context(i)["lead"]["name"], "postcode": "AB1", "source_key": f"fsa:{n}", "website": "https://example.com", "screening_class": "candidate", "entity_status": "unknown", "contact_count": 1, "business_type_id": 1, "communication_progress": context(i)["progress"]} for n, i in enumerate([LEAD, OTHER])]
    elif path.endswith("/workflow"):
        result = None
    elif path == "/api/communication/assignees":
        result = [{"username": "ui-test", "display_name": "UI Tester"}]
    elif path == "/api/communication/prepare":
        result = {"items": [{"lead_id": i, "name": context(i)["lead"]["name"], "draft": draft(i), "existing_task": None} for i in body["lead_ids"]]}
    elif path == f"/api/leads/{LEAD}/content":
        assert body["mode"] == "menu_inquiry" and "analysis_id" not in body
        piece = {"id": "inquiry", "version": 1, "mode": "menu_inquiry", "body_text": "Who is responsible for your menu design?\n" + body["sender_identity"] + "\n" + body["opt_out_text"], "approved": False, "reason": "待审批"}
        result = piece
    elif path == f"/api/communication/drafts/{DRAFT}":
        selected_content = body["content_id"]
        result = draft(LEAD)
    elif path == "/api/content/inquiry/approve":
        piece["approved"] = True
        result = piece
    elif path == "/api/communication/activate":
        task = {"id": TASK, "lead_id": LEAD, "eligibility_id": "eligibility", "content_id": "content", "channel": "email", "status": "pending", "status_reason": None, "execution_mode": "manual", "assigned_to": "ui-test", "follow_up_at": None, "sent_at": None, "preparation_group_id": body["group_id"]}
        result = {"items": [{"draft_id": DRAFT, "task_id": TASK, "reused": False}]}
    elif path == "/api/communication/overview":
        result = {"total": 1, "items": [{"id": LEAD, "name": "Alpha Restaurant", "postcode": "AB1", "progress": context()["progress"]}]} if task else {"total": 0, "items": []}
    elif path == f"/api/communication/leads/{LEAD}":
        result = context()
    elif path == f"/api/communication/activity/{LEAD}":
        result = {"timeline": [], "deliveries": [], "conversations": []}
    elif path == f"/api/communication/tasks/{TASK}/manual-open":
        task["status"] = "opened"
        result = {"task_id": TASK, "channel": "email", "url": "mailto:info@example.com", "text": context()["contents"][0]["body_text"]}
    elif path == f"/api/leads/{LEAD}/events":
        replied = True
        task["status"] = "paused"
        result = {"id": "event", "duplicate": False}
    else:
        errors.append(f"未模拟 API: {request.method} {path}")
        result = {"detail": "unexpected request"}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(copy.deepcopy(result)))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1680, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/leads?batch=测试")
        await page.get_by_role("button", name="准备触达", exact=True).first.click()
        await page.get_by_role("button", name="检查并保存草稿").click()
        await page.locator(".ant-table-row-expand-icon").first.click()
        await expect(page.get_by_text("暂无可引用的已确认菜单问题，可直接询问菜单或负责人。", exact=True)).to_be_visible()
        await page.get_by_label("发件身份", exact=True).fill("Beacon Menu Studio")
        await page.get_by_role("button", name="生成询问菜单／负责人文案", exact=True).first.click()
        await expect(page.get_by_label("文案内容", exact=True)).to_contain_text("Who is responsible")
        await page.get_by_text("我已核对引用事实、身份和退出说明", exact=True).first.click()
        await page.get_by_role("button", name="确认审批此版本", exact=True).first.click()
        await expect(page.get_by_role("button", name="创建就绪任务（1）")).to_be_enabled()
        await page.screenshot(path="data/devchecks/d68-menu-inquiry.png", full_page=True)
        assert not any("/gmail/" in path or path.endswith("/sent") for _, path, _ in requests)
        assert not errors, errors
        await browser.close()
    print("D68 UI passed: no menu analysis, inquiry generation, preview, approval, readiness; no sends")


asyncio.run(main())
