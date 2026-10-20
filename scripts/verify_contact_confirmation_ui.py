"""D66 当前行 AI、人工事实确认与准入入口；全部 API 模拟，不发送。"""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

ID = "11111111-1111-4111-8111-111111111111"
lead = {"id": ID, "name": "Club Test", "source_key": "fsa:1", "website": "https://club.test", "screening_class": "candidate", "entity_status": "unknown"}
row = {"id": "contact", "channel": "email", "contact_ref": "secretary@club.test", "contact_source": "官网", "contact_usable": "unknown", "eligibility": "unknown", "recommendation": {"recommendation": "review", "affiliation": "unknown", "owner": "", "purpose": "unknown", "reason": "尚缺真实上下文"}}
role = "admin"
writes, errors = [], []


async def handle(route):
    path, method = urlsplit(route.request.url).path, route.request.method
    if method != "GET":
        writes.append(path)
    if path.endswith("/menu-workspace"):
        data = {"assets": [], "analyses": {}}
    elif path == "/api/communication/assignees":
        data = []
    elif path.startswith("/api/communication/leads/"):
        data = {"lead": {"id": ID, "name": "Mock restaurant"}, "contacts": [], "contents": [], "analyses": [], "tasks": [], "drafts": [], "progress": {"status": "not_started"}}
    elif path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": role, "must_change_password": False}
    elif path == f"/api/leads/{ID}":
        data = lead
    elif path in [f"/api/leads/{ID}/assets", f"/api/leads/{ID}/content"]:
        data = []
    elif path.endswith("/eligibility"):
        if method == "POST":
            body = route.request.post_data_json
            assert body["rule_version"] == "contact-admission-manual-v1"
            assert body["evidence"] == "UI 模拟：已按团队规则核对允许依据"
            row["eligibility"] = body["eligibility"]
        data = [row] if method == "GET" else row
    elif path.endswith("/auto-research"):
        data = {"configured": False, "run": None}
    elif path.endswith("/maps-menu"):
        data = {"configured": False, "worker_online": False, "run": None}
    elif path.endswith("/google-places"):
        data = {"configured": False, "link": None}
    elif path.endswith("/contact-review"):
        if row["recommendation"].get("method") != "manual":
            row["recommendation"] = {"recommendation": "recommended", "affiliation": "target", "owner": "Club Test", "purpose": "general", "reason": "官网联系页直接列出门店邮箱", "method": "ai"}
        data = {"ai": {"status": "completed", "reason": "完成"}, "notice": "", "website": None, "candidates": [{"kind": "email", "channel": "email", "value": row["contact_ref"], "sources": [], "recorded": True, "suppressed": False, "assessment": row["recommendation"]}]}
    elif path.endswith("/contacts/contact/confirm"):
        row["recommendation"] = {**route.request.post_data_json, "method": "manual", "confirmed_by": "ui"}
        data = row["recommendation"]
    else:
        errors.append(path)
        data = {}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    global role
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1700, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{ID}")
        await expect(page.get_by_role("button", name="人工确认", exact=True)).to_be_visible()
        await page.get_by_role("button", name="查找联系方式", exact=True).click()
        await expect(page.get_by_role("dialog", name="联系方式 · AI 推荐").get_by_text("AI 已确认", exact=True)).to_be_visible()
        await page.get_by_role("dialog", name="联系方式 · AI 推荐").get_by_role("button", name="Close", exact=True).click()
        await page.locator("#customer-contacts .ant-table-row-expand-icon-collapsed").first.click()
        await page.get_by_role("button", name="人工确认", exact=True).click()
        facts = page.get_by_role("dialog", name="确认联系方式归属与用途")
        await facts.get_by_label("所属门店／部门").fill("Club Test 门店团队")
        await facts.get_by_label("确认依据", exact=True).fill("人工核对官网联系页及部门用途")
        await facts.get_by_role("button", name="保存人工确认", exact=True).click()
        await expect(facts).not_to_be_visible()
        await expect(page.locator("#customer-contacts").get_by_text("人工已确认", exact=True)).to_be_visible()
        await page.get_by_role("button", name="查找联系方式", exact=True).click()
        await page.get_by_role("dialog", name="联系方式 · AI 推荐").get_by_role("button", name="Close", exact=True).click()
        await expect(page.locator("#customer-contacts").get_by_text("人工已确认", exact=True)).to_be_visible()
        await page.get_by_role("button", name="准入设置", exact=True).click()
        admission = page.get_by_role("dialog", name="渠道准入确认")
        await admission.locator(".ant-form-item").filter(has=page.get_by_text("渠道准入", exact=True)).locator(".ant-select-selector").click()
        await page.get_by_title("允许", exact=True).click()
        await admission.get_by_label("准入依据与核对结果").fill("UI 模拟：已按团队规则核对允许依据")
        await expect(admission.get_by_role("button", name="保存准入确认", exact=True)).to_be_disabled()
        await admission.get_by_role("checkbox", name="我已核对允许该渠道触达的依据").check()
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/d66-contact-admission.png", full_page=False, animations="disabled")
        await admission.get_by_role("button", name="保存准入确认", exact=True).click()
        await expect(admission).not_to_be_visible()
        await expect(page.get_by_text("允许", exact=True)).to_be_visible()
        role = "viewer"
        await page.reload()
        for name in ["人工确认", "准入设置", "查找联系方式"]:
            await expect(page.get_by_role("button", name=name, exact=True)).to_be_disabled()
        assert len(writes) == 4, writes
        assert not errors, errors
        await browser.close()
    print("D66 UI passed: row AI confirmation, manual preservation, direct admission with evidence and acknowledgment, viewer restrictions; no messages")


asyncio.run(main())
