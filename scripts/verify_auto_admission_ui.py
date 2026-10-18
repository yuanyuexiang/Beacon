"""D67 UI：真正的自动准入结果、缺项、证据与设置，全部 API 模拟，无发送。"""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

ID = "11111111-1111-4111-8111-111111111111"
lead = {"id": ID, "name": "Vesper Restaurant", "source_key": "fsa:1", "website": "https://vesper.test", "screening_class": "candidate", "entity_status": "unknown"}
rows = [{"id": "email", "channel": "email", "contact_ref": "info@vesper.test", "contact_source": "官网", "contact_usable": "unknown", "eligibility": "unknown"}, {"id": "phone", "channel": "phone", "contact_ref": "+441224702191", "contact_source": "官网", "contact_usable": "unknown", "eligibility": "unknown"}]
role = "admin"
errors, writes = [], []


async def handle(route):
    path, method = urlsplit(route.request.url).path, route.request.method
    if method != "GET":
        writes.append(path)
    if path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": role, "must_change_password": False}
    elif path == f"/api/leads/{ID}":
        data = lead
    elif path in [f"/api/leads/{ID}/assets", f"/api/leads/{ID}/content"]:
        data = []
    elif path.endswith("/eligibility"):
        data = rows
    elif path.endswith("/auto-research"):
        data = {"configured": False, "run": None}
    elif path.endswith("/maps-menu"):
        data = {"configured": False, "worker_online": False, "run": None}
    elif path.endswith("/google-places"):
        data = {"configured": False, "link": None}
    elif path.endswith("/auto-admission"):
        rows[0].update(eligibility="allowed", auto_admission={"status": "allowed", "method": "ai_rules", "reason": "官网运营公司与通用业务邮箱证据完整", "missing": [], "subscriber_evidence": {"citations": [{"quote": "Vesper is operated by Vesper Dining Limited.", "url": "https://vesper.test/terms"}]}})
        rows[1]["auto_admission"] = {"status": "unknown", "method": "ai_rules", "reason": "缺少有效 TPS 筛查结果；缺少有效 CTPS 筛查结果", "missing": ["缺少有效 TPS 筛查结果", "缺少有效 CTPS 筛查结果"]}
        data = {"summary": {"allowed": 1, "blocked": 0, "unknown": 1, "manual_preserved": 0}}
    else:
        errors.append(path)
        data = {}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    global role
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1800, "height": 1150})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{ID}")
        await page.get_by_role("button", name="AI 自动准入全部", exact=True).click()
        await expect(page.get_by_text("自动允许", exact=True)).to_be_visible()
        await expect(page.get_by_text("待补证据", exact=True)).to_be_visible()
        await expect(page.locator("#customer-contacts").get_by_text("缺少有效 TPS 筛查结果；缺少有效 CTPS 筛查结果", exact=True)).to_be_visible()
        await expect(page.get_by_text("未验证", exact=True)).to_have_count(2)
        await page.get_by_role("button", name="准入设置", exact=True).first.click()
        dialog = page.get_by_role("dialog", name="渠道准入确认")
        await expect(dialog.locator("blockquote").filter(has_text="Vesper is operated by Vesper Dining Limited.")).to_be_visible()
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/d67-auto-admission.png", full_page=False, animations="disabled")
        await dialog.get_by_role("button", name="Close", exact=True).click()
        role = "viewer"
        await page.reload()
        await expect(page.get_by_role("button", name="AI 自动准入全部", exact=True)).to_be_disabled()
        await expect(page.get_by_role("button", name="AI 自动准入", exact=True).first).to_be_disabled()
        assert writes == [f"/api/leads/{ID}/auto-admission"], writes
        assert not errors, errors
        await browser.close()
    print("D67 UI passed: auto allowed, specific missing evidence, no false deliverability, proof details, viewer restrictions; no messages")


asyncio.run(main())
