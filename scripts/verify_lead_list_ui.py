"""销售名单列序与下一步导航，全部 API 模拟，不执行触达。"""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

role = "admin"
writes = []
errors = []


async def handle(route):
    path = urlsplit(route.request.url).path
    if route.request.method != "GET":
        writes.append(path)
    if path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": role, "must_change_password": False}
    elif path == "/api/batches":
        data = [{"id": "batch", "batch_key": "sales-view", "region": "Aberdeen", "country": "GB", "candidate_count": 1}]
    elif path.endswith("/workflow"):
        data = None
    elif path == "/api/leads":
        data = [
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "Test Cafe",
                "assigned_to": "alice",
                "source_key": "fsa:123",
                "postcode": "AB1 1AA",
                "website": "https://cafe.test",
                "screening_class": "candidate",
                "contact_count": 2,
                "business_type_id": 1,
                "operating_type": {"category": "cafe"},
                "communication_progress": {"status": "preparing", "contact_selected": False},
                "list_summary": {"menu_status": "needs_review", "channels": ["email", "phone"]},
            }
        ]
    else:
        errors.append(path)
        data = {}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    global role
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/leads?batch=sales-view")
        table = page.locator(".ant-table-wrapper").first
        await expect(page.get_by_text("Test Cafe", exact=True)).to_be_visible()
        headers = await table.locator("thead th").all_text_contents()
        assert [h for h in headers if h.strip()] == [
            "门店",
            "负责人",
            "沟通进展",
            "下一步",
            "联系方式",
            "菜单",
            "操作",
        ], headers
        await expect(page.get_by_text("fsa:123", exact=False)).to_have_count(0)
        await expect(page.get_by_text("AB1 1AA", exact=False)).to_be_visible()
        await expect(page.get_by_role("button", name="选择联系方式", exact=True)).to_be_visible()
        await table.locator(".ant-table-row-expand-icon").first.click()
        await expect(page.get_by_text("来源：fsa:123", exact=True)).to_be_visible()
        await expect(page.get_by_role("button", name="查看核验结果", exact=True)).to_be_visible()
        await table.locator(".ant-table-row-expand-icon").first.click()
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/sales-lead-list.png", full_page=True, animations="disabled")
        role = "member"
        await page.reload()
        await expect(page.get_by_text("Test Cafe", exact=True)).to_be_visible()
        await expect(table.get_by_role("columnheader", name="负责人", exact=True)).to_have_count(0)
        assert not writes and not errors, (writes, errors)
        await browser.close()
        print("Sales list priority columns, draft action, expandable evidence and member view passed")


asyncio.run(main())
