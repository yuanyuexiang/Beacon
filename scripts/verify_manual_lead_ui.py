"""手动新增回归；所有 API 模拟，不写真实门店或发送。"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect
LEAD = "11111111-1111-4111-8111-111111111111"
async def fallback(route):
    path = urlsplit(route.request.url).path
    if path == "/api/auth/me":
        result = {"id": "ui", "username": "ui-test", "role": "admin", "must_change_password": False}
    elif path == "/api/batches":
        result = [{"id": "batch", "batch_key": "测试", "country": "GB", "source_name": "manual", "candidate_count": 0}]
    elif path == "/api/communication/assignees":
        result = [{"username": "ui-test", "display_name": "UI Tester"}]
    elif path.endswith("/workflow"):
        result = None
    else:
        result = []
    await route.fulfill(json=result)


async def main():
    writes = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        async def handle(route):
            path = urlsplit(route.request.url).path
            if path.startswith("/api/leads/manual"):
                body = route.request.post_data_json
                writes.append((path, body))
                if path.endswith("/check"):
                    result = {"duplicates": [{"id": LEAD, "name": "Rose Garden", "reasons": ["名称相同"]}]}
                else:
                    result = {"id": LEAD, "batch_key": "测试", "reused": False}
                await route.fulfill(json=result)
            elif path.endswith("/enrichment"):
                await route.fulfill(status=503, json={"detail": "模拟后台暂不可用"})
            else:
                await fallback(route)
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/leads?batch=测试")
        await page.get_by_role("button", name="新增门店", exact=True).click()
        await page.get_by_label("门店名称", exact=True).fill("Rose Garden")
        await page.get_by_role("button", name="添加联系方式", exact=True).click()
        await page.get_by_role("textbox", name="联系方式", exact=True).fill("owner@example.com")
        await page.get_by_role("button", name="保存并 AI 完善", exact=True).click()
        await expect(page.get_by_text("发现可能已有的门店", exact=True)).to_be_visible()
        assert not any(path == "/api/leads/manual" for path, _ in writes)
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/manual-lead-duplicate.png")
        await page.get_by_role("button", name="仍然新建并 AI 完善", exact=True).click()
        await expect(page.get_by_text("门店已保存", exact=True)).to_be_visible()
        await expect(page.get_by_text("门店已保存，自动完善未启动：模拟后台暂不可用", exact=True)).to_be_visible()
        assert len([x for x in writes if x[0] == "/api/leads/manual"]) == 1
        assert writes[-1][1]["allow_duplicate"] is True
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path="data/devchecks/manual-lead-saved-mobile.png")
        await browser.close()
    print(json.dumps({"result": "passed", "manual_requests": len(writes)}))

asyncio.run(main())
