"""Meta diagnostics regression with mocked APIs only; no real credentials or messages."""
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect

async def main():
    row = dict(id="demo", label="测试主页", platform="facebook", auth_mode="facebook_login", sender_id="1234", connected=False, sending_enabled=False, queue_enabled=False, daily_limit=20, capabilities=[])
    checks = []
    async def handle(route):
        path = urlsplit(route.request.url).path
        code = 200
        if path == "/api/auth/me":
            data = dict(id="admin", username="admin", role="admin", must_change_password=False)
        elif path == "/api/outreach/status": data = dict(configured=True, app=dict(configured=True, app_id="123", webhook_configured=True))
        elif path == "/api/outreach/accounts": data = [row]
        elif path.endswith("/credentials"):
            row['connection_diagnostics'] = dict(state="pending_check", updated_at="2026-10-28T01:00:00Z")
            data = row
        elif path.endswith("/check"):
            checks.append(path)
            row['connection_diagnostics'] = dict(state="check_failed", updated_at="2026-10-28T01:01:00Z", error="权限不足（HTTP 403; code=200）")
            code, data = 409, dict(detail=row['connection_diagnostics']['error'])
        elif path.endswith("/disconnect"):
            raise AssertionError("Must not disconnect without confirmation")
        else: data = {}
        await route.fulfill(status=code, content_type="application/json", body=json.dumps(data))
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport=dict(width=1600, height=1100))
        await page.route("**/api/**", handle)
        await page.goto(os.environ.get("BEACON_UI_TEST_URL", "http://localhost:3000") + "/settings?section=meta")
        await page.get_by_role("button", name="导入 Token", exact=True).click()
        await page.get_by_role("dialog").locator("input").fill("fake-token-for-ui-only")
        await page.get_by_role("button", name="保存并检查连接", exact=True).click()
        await expect(page.get_by_role("dialog")).to_have_count(0)
        await expect(page.get_by_text("连接检查失败", exact=True)).to_be_visible()
        assert len(checks) == 1
        await page.reload()
        await expect(page.get_by_text("权限不足（HTTP 403; code=200）", exact=True)).to_be_visible()
        await page.get_by_role("button", name=re.compile(r"断\s*开")).click()
        await expect(page.get_by_text("断开并清除该账号的令牌？", exact=True)).to_be_visible()
        await page.get_by_role("button", name=re.compile(r"取\s*消")).click()
        await expect(page.get_by_text("断开并清除该账号的令牌？", exact=True)).not_to_be_visible()
        out = Path('data/devchecks'); out.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out / 'meta-diagnostics.png'), full_page=True)
        await browser.close()
    print('Meta import/check, persistent failure and disconnect confirmation passed; mocked APIs only.')

asyncio.run(main())
