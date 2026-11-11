"""来源网站界面回归：全部 API 模拟，无真实 AI／Google 调用或名单写入。"""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

role = "admin"
errors = []
writes = []
leads = [
    {"id": "1", "name": "College Cafe", "website": "https://example.com", "source_key": "fsa:1", "postcode": "AB1", "screening_class": "candidate", "entity_status": "unknown", "contact_count": 1, "google_enrichment": {"status": "review"}},
    {"id": "2", "name": "Retry Restaurant", "website": "https://retry.example.com", "source_key": "fsa:2", "postcode": "AB1", "screening_class": "candidate", "entity_status": "unknown", "contact_count": 1, "website_research": {"status": "retry", "reason": "SSL 连接中断，可重试"}},
    {"id": "3", "name": "Conflict Restaurant", "website": "https://other.example.com", "source_key": "fsa:3", "postcode": "AB1", "screening_class": "candidate", "entity_status": "unknown", "contact_count": 1, "website_research": {"status": "conflict", "reason": "官网说明其他门店"}},
]


async def handle(route):
    request = route.request
    path = urlsplit(request.url).path
    if request.method != "GET":
        writes.append(path)
    if path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": role, "must_change_password": False}
    elif path == "/api/outreach-identity":
        data = {"sender_identity": "UI Test", "opt_out_text": "No reply needed."}
    elif path.endswith("/enrichment-history"):
        data = []
    elif path in {"/api/directory/regions", "/api/assignment/members", "/api/users", "/api/users/identities"}:
        data = []
    elif path == "/api/batches":
        data = [{"id": "batch", "batch_key": "ai-test", "country": "UK", "region": "Aberdeen", "candidate_count": 3}]
    elif path == "/api/leads":
        data = leads
    elif path.endswith("/workflow"):
        data = None
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
        await page.goto(os.environ.get("BEACON_UI_URL", "http://localhost:3000") + "/leads?batch=ai-test")
        await page.locator(".ant-table-row-expand-icon-collapsed").first.wait_for()
        while await page.locator(".ant-table-row-expand-icon-collapsed").count():
            await page.locator(".ant-table-row-expand-icon-collapsed").first.click()
        await expect(page.get_by_text("有网站", exact=True)).to_be_visible()
        await expect(page.get_by_text("官网：待重试", exact=True)).to_have_count(0)
        await page.get_by_role("button", name="查看网站与来源", exact=True).first.click()
        dialog = page.get_by_role("dialog")
        await expect(dialog.get_by_role("link", name="https://example.com", exact=True)).to_be_visible()
        await expect(dialog.get_by_role("button", name="AI 核验／重试", exact=True)).to_have_count(0)
        output = Path("data/devchecks/source-website.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output), full_page=True, animations="disabled")
        await dialog.locator(".ant-modal-footer button").click()
        role = "viewer"
        await page.reload()
        await page.locator(".ant-table-row-expand-icon-collapsed").first.wait_for()
        await page.locator(".ant-table-row-expand-icon-collapsed").first.click()
        await page.get_by_role("button", name="查看网站与来源", exact=True).first.click()
        await expect(page.get_by_role("dialog").get_by_role("link", name="https://example.com", exact=True)).to_be_visible()
        assert not writes, writes
        assert not errors, errors
        await browser.close()
    print("Source website UI passed: direct website display, no verification gate, viewer read-only")


asyncio.run(main())
