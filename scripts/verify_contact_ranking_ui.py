"""D65 联系方式推荐界面；所有 API 模拟，不调用模型、网络商户或发送消息。"""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

ID = "11111111-1111-4111-8111-111111111111"
lead = {"id": ID, "name": "Vesper Restaurant", "source_key": "fsa:1", "website": "https://vesper.test", "website_source": "官网核验", "screening_class": "candidate", "entity_status": "unknown"}
errors, writes, recorded = [], [], []
mode = "completed"
role = "admin"


def candidate(number, recommendation, purpose, owner, reason, suppressed=False):
    return {"kind": "phone", "channel": "phone", "value": number, "sources": [{"type": "website", "ref": "https://vesper.test/contact"}], "personal": False, "mobile": False, "recorded": number in recorded, "eligibility": "unknown", "suppressed": suppressed, "assessment": {"recommendation": recommendation if mode == "completed" else "review", "owner": owner, "purpose": purpose, "reason": reason, "citations": [{"quote": f"Vesper Restaurant · {owner} · {purpose}", "url": "https://vesper.test/contact"}]}}


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
    elif path == f"/api/leads/{ID}/eligibility":
        data = [{"id": "stored", "channel": "phone", "contact_ref": "+441224348534", "contact_source": "官网", "contact_usable": "unknown", "eligibility": "blocked", "recommendation": {"recommendation": "not_recommended", "owner": "媒体办公室", "purpose": "media", "reason": "只接收媒体事务，不适合本次业务联系"}}]
    elif path.endswith("/auto-research"):
        data = {"configured": False, "run": None}
    elif path.endswith("/maps-menu"):
        data = {"configured": False, "worker_online": False, "run": None}
    elif path.endswith("/google-places"):
        data = {"configured": False, "link": None}
    elif path.endswith("/contact-review"):
        assert method == "POST"
        data = {"notice": "推荐只表示业务相关，渠道准入另行核对。", "website": {"url": "https://vesper.test", "pages": [{"url": "https://vesper.test", "ok": True}]}, "ai": {"status": mode, "reason": "AI 已按官网证据判断归属和用途" if mode == "completed" else "AI 暂不可用，候选已保留"}, "candidates": [candidate("+44800833551", "recommended", "business", "门店经营团队", "官网明确公布商务联络用途"), candidate("+441224348534", "not_recommended", "media", "媒体办公室", "只接收媒体事务"), candidate("+442079460123", "backup", "booking", "订位专线", "仅用于订位，可作为备选"), candidate("+447700900123", "recommended", "general", "门店", "该号码已抑制", True)]}
    elif path.endswith("/contacts"):
        body = route.request.post_data_json
        assert [c["contact_ref"] for c in body["items"]] == ["+44800833551"]
        recorded.append("+44800833551")
        data = {"created": 1, "skipped": 0}
    else:
        errors.append(path)
        data = {}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    global mode, role
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1700, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{ID}")
        await expect(page.get_by_text("不推荐", exact=True)).to_be_visible()
        await page.get_by_role("button", name="查找联系方式", exact=True).click()
        modal = page.get_by_role("dialog", name="联系方式 · AI 推荐")
        await expect(modal.get_by_role("link", name="+44800833551", exact=True)).to_be_visible()
        await expect(modal.get_by_role("link", name="+441224348534", exact=True)).to_have_count(0)
        await expect(modal.get_by_role("button", name="记录所选 1 项", exact=True)).to_be_enabled()
        await modal.get_by_role("button", name="查看全部候选（4）", exact=True).click()
        await expect(modal.get_by_role("link", name="+441224348534", exact=True)).to_be_visible()
        await expect(modal.get_by_text("订位专线", exact=False).first).to_be_visible()
        await modal.locator(".ant-table-row-expand-icon").first.click()
        await expect(modal.get_by_text("Vesper Restaurant · 门店经营团队 · business", exact=True)).to_be_visible()
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/d65-contact-ranking.png", full_page=True, animations="disabled")
        await modal.get_by_role("button", name="记录所选 1 项", exact=True).click()
        await expect(modal).not_to_be_visible()
        mode = "ai_unavailable"
        await page.get_by_role("button", name="查找联系方式", exact=True).click()
        await expect(modal.get_by_text("AI 暂不可用，候选已保留", exact=True)).to_be_visible()
        await expect(modal.get_by_role("button", name="记录所选 0 项", exact=True)).to_be_disabled()
        await modal.get_by_role("button", name="查看全部候选（4）", exact=True).click()
        await expect(modal.get_by_role("link", name="+441224348534", exact=True)).to_be_visible()
        role = "viewer"
        await page.reload()
        await expect(page.get_by_role("button", name="查找联系方式", exact=True)).to_be_disabled()
        assert writes == [f"/api/leads/{ID}/contact-review", f"/api/leads/{ID}/contacts", f"/api/leads/{ID}/contact-review"], writes
        assert not errors, errors
        await browser.close()
    print("D65 UI passed: default recommendations, all candidates, grounded evidence, suppression, record selected only, AI unavailable, protected legacy rows, viewer read-only; no external sends")


asyncio.run(main())
