"""策略设置浏览器回归：所有 API 模拟，不写实际数据或调用外部服务。"""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

saved = {
    "version": "v1",
    "chain_action": "review",
    "institution_action": "review",
    "cafe_action": "keep",
    "pub_action": "keep",
    "brand_action": "review",
    "chain_names": ["Starbucks"],
    "institution_words": ["college"],
    "google_mode": "needed",
    "google_request_limit": 20,
    "stale_days": 90,
}
writes = []
errors = []


async def handle(route):
    global saved
    path = urlsplit(route.request.url).path
    status = 200
    if path == "/api/auth/me":
        data = {"id": "ui", "username": "ui-test", "role": "admin", "display_name": None, "must_change_password": False}
    elif path == "/api/lead-policy":
        if route.request.method == "PUT":
            body = route.request.post_data_json
            assert body["version"] == saved["version"]
            writes.append(body)
            saved = {**body, "version": "v2"}
        data = saved
    else:
        # 与邮件／社媒服务保持脱离，绝不访问真实服务。
        status, data = 503, {"detail": "UI fixture: service disabled"}
    await route.fulfill(status=status, content_type="application/json", body=json.dumps(data))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/settings")
        card = page.locator(".ant-card").filter(has=page.get_by_text("客户筛选与数据补充策略", exact=True))
        await expect(card.get_by_role("button", name="保存策略")).to_be_enabled()
        await expect(card).to_contain_text("咖啡馆／面包店／Deli")
        await card.get_by_label("每个任务最多 API 尝试次数").fill("12")
        await card.get_by_label("核验有效天数").fill("30")
        await (
            card.locator(".ant-form-item")
            .filter(has=page.get_by_text("咖啡馆／面包店／Deli", exact=True))
            .locator(".ant-select-selector")
            .click()
        )
        await page.get_by_title("标记待复核，继续研究", exact=True).last.click()
        await card.get_by_role("button", name="保存策略").click()
        await page.get_by_text("策略已保存，新任务生效", exact=True).wait_for()
        assert writes[-1]["google_request_limit"] == 12 and writes[-1]["stale_days"] == 30
        assert writes[-1]["cafe_action"] == "review"
        await page.reload()
        await expect(page.get_by_label("每个任务最多 API 尝试次数")).to_have_value("12")
        await expect(page.get_by_label("核验有效天数")).to_have_value("30")
        await expect(page.get_by_role("button", name="保存策略", exact=True)).to_be_enabled()
        await page.screenshot(path="data/devchecks/lead-policy-settings.png", full_page=True)
        assert not errors, errors
        print(json.dumps({"saved_and_reloaded": True, "page_errors": errors, "real_api_calls": 0}))
        await browser.close()


Path("data/devchecks").mkdir(parents=True, exist_ok=True)
asyncio.run(main())
