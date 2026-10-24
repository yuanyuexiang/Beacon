"""Settings navigation regression; mocked APIs, no credentials or sends."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect

async def main():
    requests = []
    errors = []
    profile = dict(version="v1", company="示例公司", services="菜单设计", proof="", constraints="")
    async def handle(route):
        path = urlsplit(route.request.url).path
        requests.append((path, route.request.method))
        if path == "/api/auth/me":
            data = dict(id="admin", username="admin", role="admin", must_change_password=False, display_name="管理员")
        elif path == "/api/outreach-profile":
            if route.request.method == "PUT": profile.update(route.request.post_data_json)
            data = profile
        elif path == "/api/gmail/status":
            data = dict(configured=True, client_type="web", oauth_configured=True, connected=True, token_present=True, send_authorized=True, email="demo@example.com", policy=dict(sending_enabled=False, queue_enabled=False, daily_limit=1))
        elif path == "/api/outreach/status": data = dict(configured=True, app=dict(configured=False))
        elif path == "/api/outreach/accounts": data = []
        else: data = {}
        await route.fulfill(content_type="application/json", body=json.dumps(data))
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport=dict(width=1600, height=1100))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/settings?section=profile")
        await expect(page.get_by_label("公司／品牌介绍", exact=True)).to_have_value("示例公司")
        assert not any("gmail" in path or "outreach/status" in path for path, _ in requests)
        await page.get_by_label("公司／品牌介绍", exact=True).fill("保留中的草稿")
        nav = page.get_by_role("navigation", name="设置分类")
        await nav.get_by_role("button", name="Gmail 未检查 邮箱授权、测试与发送", exact=True).click()
        await expect(page.get_by_text("demo@example.com", exact=True)).to_be_visible()
        assert sum(path == "/api/gmail/status" for path, _ in requests) == 1
        await page.get_by_label("滚动 24 小时限额", exact=True).fill("9")
        await nav.get_by_role("button", name="我们的服务 未保存 AI 起草使用的真实服务资料", exact=True).click()
        await expect(page.get_by_label("公司／品牌介绍", exact=True)).to_have_value("保留中的草稿")
        await page.get_by_role("button", name="保存服务资料", exact=True).click()
        await expect(page.get_by_text("服务资料已保存", exact=True)).to_be_visible()
        await nav.get_by_role("button", name="Gmail 未保存 邮箱授权、测试与发送", exact=True).click()
        await expect(page.get_by_label("滚动 24 小时限额", exact=True)).to_have_value("9")
        assert sum(path == "/api/gmail/status" for path, _ in requests) == 1
        # Internal navigation must not silently discard modified settings.
        page.once("dialog", lambda d: d.dismiss())
        await page.get_by_role("link", name="批次与线索", exact=True).click()
        assert "/settings" in page.url
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/settings-three-columns.png", full_page=True)
        page.once("dialog", lambda d: d.accept())
        await page.goto("http://localhost:3000/settings?gmail=connected")
        await expect(page.get_by_text("demo@example.com", exact=True)).to_be_visible()
        await expect(nav.get_by_role("button", name="Gmail 已连接 邮箱授权、测试与发送", exact=True)).to_have_attribute("aria-current", "page")
        await page.set_viewport_size(dict(width=900, height=1000))
        await expect(nav).to_be_hidden()
        await expect(page.get_by_role("combobox", name="设置分类", exact=True)).to_be_visible()
        await page.screenshot(path="data/devchecks/settings-narrow.png", full_page=True)
        assert not errors, errors
        assert not any(path.endswith("/send") for path, _ in requests)
        await browser.close()
    print("PASS: lazy requests, drafts, leave guard, OAuth return, responsive navigation")

asyncio.run(main())
