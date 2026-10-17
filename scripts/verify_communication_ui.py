"""名单到沟通工作台回归：全部 API 模拟，不写真实客户、不发送消息。"""

import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

LEAD = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
DRAFT = "33333333-3333-4333-8333-333333333333"
TASK = "44444444-4444-4444-8444-444444444444"
requests = []
errors = []
task = None
replied = False


def context(identity=LEAD):
    return {
        "lead": {"id": identity, "name": "Alpha Restaurant" if identity == LEAD else "Beta Cafe", "postcode": "AB1", "website": "https://example.com", "address": "1 Test Road"},
        "contacts": [{"id": "eligibility", "channel": "email", "contact_ref": "info@example.com", "contact_source": "官网", "contact_usable": "valid", "eligibility": "allowed", "suppressed": False}],
        "contents": [{"id": "content", "version": 1, "body_text": "Hello Alpha, approved message. Please let us know to opt out.", "approved": True, "reason": None}],
        "analyses": [], "tasks": [task] if task and identity == LEAD else [],
        "progress": {"status": "replied" if replied else "pending" if task else "not_started", "task_id": TASK if task else None},
        "drafts": [],
    }


def draft(identity):
    return {"id": DRAFT if identity == LEAD else OTHER, "lead_id": identity, "channel": "email", "execution_mode": "manual", "eligibility_id": "eligibility", "content_id": "content", "assigned_to": "ui-test", "follow_up_at": None, "purpose": "initial", "notes": None, "status": "draft", "task_id": None, "blockers": [] if identity == LEAD else ["尚未准备已审批文案"], "context": context(identity)}


async def handle(route):
    global task, replied
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
    elif path == "/api/communication/activate":
        task = {"id": TASK, "lead_id": LEAD, "eligibility_id": "eligibility", "content_id": "content", "channel": "email", "status": "pending", "status_reason": None, "execution_mode": "manual", "assigned_to": "ui-test", "follow_up_at": None, "sent_at": None, "preparation_group_id": body["group_id"]}
        result = {"items": [{"draft_id": DRAFT, "task_id": TASK, "reused": False}]}
    elif path == "/api/communication/overview":
        result = {"total": 1, "items": [{"id": LEAD, "name": "Alpha Restaurant", "postcode": "AB1", "progress": context()["progress"]}]}
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
    output = Path("data/devchecks")
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1680, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/leads?batch=%E6%B5%8B%E8%AF%95&type=1")
        await expect(page.get_by_text("Alpha Restaurant", exact=True)).to_be_visible()
        await page.get_by_role("button", name="准备触达", exact=True).click()
        await page.get_by_role("button", name="检查并保存草稿").click()
        await expect(page.get_by_text("待补 1 项", exact=True)).to_be_visible()
        await page.get_by_role("button", name="创建就绪任务（1）").click()
        await expect(page.get_by_text("任务已就绪，尚未发送", exact=True)).to_be_visible()
        await page.screenshot(path=str(output / "d60-preparation.png"), full_page=True)
        await page.get_by_role("link", name="进入本次触达工作台 →").click()
        await expect(page.get_by_role("button", name="开始人工执行")).to_be_visible()
        await page.get_by_role("button", name="开始人工执行").click()
        await expect(page.get_by_text(context()["contents"][0]["body_text"], exact=True)).to_be_visible()
        assert not any(path.endswith("/sent") for _, path, _ in requests)
        await page.get_by_role("button", name="Close", exact=True).click()
        await page.get_by_role("tab", name="客户会话").click()
        await page.get_by_label("结果", exact=True).click()
        await page.get_by_title("客户已回复", exact=True).click()
        await page.get_by_label("摘要／约定的下一步").fill("Requested a quote; follow up tomorrow")
        await page.get_by_role("button", name="记录沟通结果").click()
        await expect(page.get_by_text("结果已记录；回复会暂停待发任务，拒收会进入抑制。", exact=True)).to_be_visible()
        await page.screenshot(path=str(output / "d60-workbench.png"), full_page=True)
        await page.get_by_role("button", name="返回来源页面").click()
        await page.wait_for_url("**/leads?**")
        await expect(page.get_by_text("Alpha Restaurant", exact=True)).to_be_visible()
        assert "type=1" in page.url and "batch=" in page.url
        assert not any("/gmail/" in path or "/outreach/" in path for _, path, _ in requests)
        assert not errors, errors
        await browser.close()
    print("D60 UI passed: batch preparation, exact task, manual preview, reply, source context; no outbound calls")


asyncio.run(main())
