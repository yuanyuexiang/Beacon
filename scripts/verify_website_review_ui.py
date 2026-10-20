"""D62 界面回归：全部 API 模拟，无真实 AI／Google 调用或名单写入。"""

import asyncio
import json
import re
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
    elif path == "/api/batches":
        data = [{"id": "batch", "batch_key": "ai-test", "country": "UK", "region": "Aberdeen", "candidate_count": 3}]
    elif path == "/api/leads":
        data = leads
    elif path.endswith("/workflow"):
        data = None
    elif path == "/api/leads/1/website-review":
        evidence = {"citations": [{"document_id": "web0", "quote": "College Cafe serves lunch and coffee."}], "sources": [{"id": "web0", "url": "https://example.com/about"}]}
        leads[0]["operating_type"] = {"status": "verified", "category": "cafe", "reason": "官网说明咖啡与餐食", "services": ["coffee", "food_service"], **evidence}
        leads[0]["website_research"] = {"status": "verified", "reason": "官网确认门店身份", "judgment": {"citations": evidence["citations"]}, "sources": evidence["sources"]}
        data = leads[0]
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
        await page.goto("http://localhost:3000/leads?batch=ai-test")
        await page.locator(".ant-table-row-expand-icon-collapsed").first.wait_for()
        while await page.locator(".ant-table-row-expand-icon-collapsed").count():
            await page.locator(".ant-table-row-expand-icon-collapsed").first.click()
        await expect(page.get_by_text("官网：待重试", exact=True)).to_be_visible()
        await expect(page.get_by_text("官网：身份冲突，需人工核对", exact=True)).to_be_visible()
        await page.get_by_role("button", name="查看核验结果", exact=True).first.click()
        await page.get_by_role("button", name="AI 核验／重试", exact=True).click()
        await expect(page.get_by_text("官网确认门店身份", exact=True)).to_be_visible()
        await expect(page.get_by_text("College Cafe serves lunch and coffee.", exact=True).first).to_be_visible()
        await expect(page.get_by_text("来源：https://example.com/about", exact=True).first).to_be_visible()
        await expect(page.get_by_role("button", name="AI 核验／重试", exact=True)).not_to_have_class(re.compile("ant-btn-loading"))
        output = Path("data/devchecks/d62-website-review.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output), full_page=True, animations="disabled")
        await page.get_by_role("button", name="Close", exact=True).click()
        await expect(page.get_by_text("供应餐食", exact=True)).to_be_visible()
        role = "viewer"
        await page.reload()
        await page.locator(".ant-table-row-expand-icon-collapsed").first.wait_for()
        while await page.locator(".ant-table-row-expand-icon-collapsed").count():
            await page.locator(".ant-table-row-expand-icon-collapsed").first.click()
        await page.get_by_role("button", name="查看核验结果", exact=True).first.click()
        await expect(page.get_by_role("button", name="AI 核验／重试", exact=True)).to_be_disabled()
        assert writes == ["/api/leads/1/website-review"], writes
        assert not errors, errors
        await browser.close()
    print("D62 UI passed: distinct statuses, AI retry, exact evidence, mixed services, viewer read-only")


asyncio.run(main())
