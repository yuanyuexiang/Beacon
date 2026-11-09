"""Phone settings regression with mocked APIs; never pairs a real device or sends."""
import asyncio
import json
import re
from datetime import datetime, timedelta, UTC
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect

async def main():
    errors = []
    calls = []
    device = dict(id="mock-device", label="验证手机", owner="tester", status="ready", online=True, account="+447700900001", last_seen_at="2026-11-05T09:00:00Z")
    async def handle(route):
        path = urlsplit(route.request.url).path
        calls.append(path)
        if path == "/api/auth/me":
            data = dict(id="tester", username="tester", role="admin", must_change_password=False)
        elif path == "/api/mobile/devices": data = [] if device.get("removed") else [device]
        elif path == "/api/mobile/devices/mock-device" and route.request.method == "DELETE":
            device["removed"] = True
            data = {"removed": True}
        elif path == "/api/mobile/pairing": data = dict(code="123456", expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(), owner="tester", server="http://192.168.3.103:8000")
        elif path.endswith("/revoke"):
            device["status"] = "revoked"
            data = device
        else: data = {}
        await route.fulfill(content_type="application/json", body=json.dumps(data))
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport=dict(width=1600, height=1050))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/settings?section=mobile")
        await expect(page.get_by_text("验证手机", exact=True)).to_be_visible()
        await page.get_by_role("button", name="绑定新手机", exact=True).click()
        await expect(page.get_by_text("123456", exact=True)).to_be_visible()
        await expect(page.locator(".ant-qrcode")).to_be_visible()
        await expect(page.get_by_text("绑定账号：tester", exact=True)).to_be_visible()
        address = page.get_by_role("textbox", name="手机访问地址", exact=True)
        await address.fill("http://192.168.86.32:8000")
        await page.get_by_role("button", name="刷新配对码", exact=True).click()
        await expect(address).to_have_value("http://192.168.86.32:8000")
        await expect(page.get_by_text("http://192.168.86.32:8000", exact=True)).to_be_visible()
        await page.get_by_role("button", name="使用服务器推荐地址", exact=True).click()
        await expect(address).to_have_value("http://192.168.3.103:8000")
        await expect(page.get_by_role("button", name="刷新手机", exact=True)).not_to_have_class("ant-btn-loading")
        out = Path("data/devchecks/mobile"); out.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out / "settings-desktop.png"), full_page=True)
        await page.get_by_role("button", name="解除绑定", exact=True).click()
        await expect(page.get_by_text("已解除", exact=True)).to_be_visible()
        await page.set_viewport_size(dict(width=900, height=1000))
        await page.screenshot(path=str(out / "settings-narrow.png"), full_page=True)
        await page.get_by_role("button", name=re.compile(r"^删\s*除$"), exact=True).click()
        await page.get_by_role("button", name="删除设备", exact=True).click()
        await expect(page.get_by_text("验证手机", exact=True)).to_have_count(0)
        assert not errors, errors
        assert not any(path.endswith("/send") for path in calls)
        await browser.close()
    print("PASS: mobile pairing UI, revoke, responsive layout, no external sends")

asyncio.run(main())
