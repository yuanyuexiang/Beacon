"""D63 菜单到触达全流程界面回归；全部 API 模拟，不上传真实文件、不发消息。"""

import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect

ID = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
TASK = "33333333-3333-4333-8333-333333333333"
lead = {"id": ID, "name": "Journey Restaurant", "source_key": "fsa:1", "address": "1 Test Road", "postcode": "AB1", "website": None, "website_source": None, "screening_class": "candidate", "screening_reason": None, "entity_status": "unknown", "entity_evidence": None}
assets = []
analyses = []
piece = None
approved = False
task = None
requests = []
errors = []
analysis_gate = asyncio.Event()
CONTACT = {"id": "eligibility", "channel": "email", "contact_ref": "info@example.com", "contact_source": "官网", "contact_usable": "valid", "eligibility": "allowed", "suppressed": False}
FACT = "The menu uses inconsistent price formatting."


def context():
    return {"lead": lead, "contacts": [CONTACT], "contents": [{"id": "content", "version": 1, "body_text": piece["body_text"], "approved": approved, "reason": None if approved else "待审批"}] if piece else [], "analyses": [{"id": analyses[-1]["id"], "version": analyses[-1]["version"], "facts": [FACT]}] if analyses and analyses[-1]["review_state"] == "reviewed" else [], "tasks": [task] if task else [], "progress": {"status": "pending" if task else "preparing", "task_id": TASK if task else None}}


def draft():
    return {"id": "draft", "lead_id": ID, "channel": "email", "execution_mode": "manual", "eligibility_id": "eligibility", "content_id": "content" if piece else None, "assigned_to": "ui", "follow_up_at": None, "purpose": "initial", "notes": None, "status": "draft", "task_id": None, "blockers": [] if approved else ["文案尚未审批" if piece else "尚未准备已审批文案"], "context": context()}


async def handle(route):
    global piece, approved, task
    request = route.request
    url = urlsplit(request.url)
    path, method = url.path, request.method
    body = request.post_data_json if request.post_data else None
    requests.append((method, path, body))
    data = None
    if path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": "admin", "must_change_password": False}
    elif path == f"/api/leads/{ID}":
        data = lead
    elif path == f"/api/leads/{ID}/assets":
        if method == "POST":
            assets.append({"id": ASSET, "kind": "pdf", "source_url": body["url"], "original_filename": None, "fetch_status": "fetched", "fetch_error": None, "storage_path": "test.pdf", "sha256": "test"})
            data = assets[0]
        else:
            data = assets
    elif path == f"/api/assets/{ASSET}/analyses":
        if method == "POST":
            assert parse_qs(url.query)["engine"] == ["auto"]
            await analysis_gate.wait()
            analyses.append({"id": "analysis1", "version": 1, "parent_version": None, "status": "needs_review", "engine": "rules", "engine_version": "test", "review_state": None, "items": [{"name": "Soup", "price_text": "5.00", "evidence": {"page": 1}}], "issues": [{"issue_code": "price_format_mixed_decimals", "fact": FACT, "severity": "candidate", "confirmed": None, "confirmed_by": None, "note": None, "evidence": {"page": 1}}], "measurements": {}, "error": None})
            data = analyses[-1]
        else:
            data = analyses
    elif path.startswith("/api/analyses/"):
        if path.endswith("/review"):
            analyses[-1].update(review_state="reviewed", status="succeeded")
        else:
            updated = copy.deepcopy(analyses[-1])
            updated.update(id="analysis2", version=2, parent_version=1)
            updated["issues"][0]["confirmed"] = True
            analyses.append(updated)
        data = analyses[-1]
    elif path == f"/api/leads/{ID}/content":
        if method == "POST":
            assert body["kind"] == "message_short"
            piece = {"id": "content", "kind": "message_short", "version": 1, "status": "draft", "approval_valid": False, "approval_invalid_reason": "待审批", "body_text": "Hello, " + FACT + " Contact Test Company, 1 Test Road. Please let us know to opt out.", "html_url": None, "png_url": None, "spec": {}}
            data = piece
        else:
            data = [{**piece, "approval_valid": approved}] if piece else []
    elif path == "/api/content/content/approve":
        approved = True
        data = {"decision": "approved"}
    elif path == f"/api/leads/{ID}/eligibility":
        data = [CONTACT]
    elif path.endswith("/auto-research"):
        data = {"configured": False, "run": None}
    elif path.endswith("/maps-menu"):
        data = {"configured": False, "worker_online": False, "run": None}
    elif path.endswith("/google-places"):
        data = {"configured": False, "link": None}
    elif path == "/api/communication/assignees":
        data = [{"username": "ui", "display_name": "UI"}]
    elif path == "/api/communication/prepare":
        data = {"items": [{"lead_id": ID, "name": lead["name"], "draft": draft(), "existing_task": None}]}
    elif path == "/api/communication/drafts/draft":
        data = draft()
    elif path == "/api/communication/activate":
        assert approved
        task = {"id": TASK, "lead_id": ID, "eligibility_id": "eligibility", "content_id": "content", "channel": "email", "status": "pending", "status_reason": None, "execution_mode": "manual", "assigned_to": "ui", "follow_up_at": None, "sent_at": None, "preparation_group_id": body["group_id"]}
        data = {"items": [{"draft_id": "draft", "task_id": TASK, "reused": False}]}
    elif path == "/api/batches":
        data = []
    elif path == "/api/communication/overview":
        data = {"total": 1, "items": [{"id": ID, "name": lead["name"], "postcode": "AB1", "progress": context()["progress"]}]}
    elif path == f"/api/communication/leads/{ID}":
        data = context()
    elif path == f"/api/communication/activity/{ID}":
        data = {"timeline": [], "deliveries": [], "conversations": []}
    else:
        errors.append(f"Unexpected API {method} {path}")
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1700, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{ID}?returnTo=%2Fleads%3Fbatch%3Dtest")
        steps = page.get_by_label("菜单资料流程")
        await expect(steps.locator(".ant-steps-item-process")).to_contain_text("获取菜单")
        await expect(steps).not_to_contain_text("审批")
        await page.get_by_placeholder("人工核对过的菜单 URL").fill("https://example.com/menu.pdf")
        await page.get_by_role("button", name="获取并分析", exact=True).click()
        await expect(steps.locator(".ant-steps-item-process")).to_contain_text("AI 分析")
        analysis_gate.set()
        await expect(steps.locator(".ant-steps-item-process")).to_contain_text("核对事实")
        await page.get_by_role("switch").click()
        await page.get_by_role("button", name="完成事实核对", exact=True).click()
        await expect(steps.locator(".ant-steps-item-process")).to_contain_text("准备触达")
        output = Path("data/devchecks")
        output.mkdir(parents=True, exist_ok=True)
        await steps.screenshot(path=str(output / "d63-menu-steps.png"), animations="disabled")
        await page.locator(f"#menu-review-{ASSET}").screenshot(path=str(output / "d63-menu-facts.png"), animations="disabled")
        await page.get_by_role("button", name="准备触达", exact=True).first.click()
        drawer = page.get_by_role("dialog")
        await drawer.get_by_label("发件身份", exact=True).fill("Test Company, 1 Test Road")
        await drawer.get_by_role("button", name="检查并保存草稿", exact=True).click()
        await drawer.locator(".ant-table-row-expand-icon").click()
        await drawer.get_by_text("准备与核对内容", exact=True).click()
        await drawer.get_by_role("button", name="按已确认事实生成待审批文案", exact=True).click()
        await drawer.get_by_role("checkbox", name="我已核对引用事实、身份和退出说明", exact=True).check()
        await drawer.get_by_role("button", name="确认审批此版本", exact=True).click()
        await drawer.get_by_role("button", name="创建就绪任务（1）", exact=True).click()
        await page.screenshot(path=str(output / "d63-preparation.png"), full_page=False, animations="disabled")
        await drawer.get_by_role("link", name="进入本次触达工作台 →").click()
        await expect(page.get_by_role("button", name="开始人工执行", exact=True)).to_be_visible()
        assert not any(body and body.get("kind") == "sample_partial" for _, _, body in requests), requests
        assert not any(path.endswith("/sent") for _, path, _ in requests)
        assert not errors, errors
        await browser.close()
    print("D63 UI passed: menu -> automatic analysis -> fact check -> shared preparation -> approval -> task, no sample or sending")


asyncio.run(main())
