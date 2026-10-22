"""Mock-only Gmail onboarding; no Google authorization or email sending."""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect


async def main():
    state = {"configured": True, "client_type": "none", "oauth_configured": False,
             "redirect_uri": "http://localhost:3000/api/gmail/oauth/callback", "connected": False,
             "policy": {"sending_enabled": False, "queue_enabled": False, "daily_limit": 1}}
    writes = []
    check_started, release_check = asyncio.Event(), asyncio.Event()
    hold_check = False
    fail_check = False
    async def route(r):
        req = r.request
        path = urlsplit(req.url).path
        data = {}
        if req.method != "GET":
            writes.append((path, req.post_data_json))
        if path == "/api/auth/me":
            data = {"id": "admin", "username": "admin", "role": "admin", "must_change_password": False}
        elif path == "/api/gmail/status":
            data = state
        elif path == "/api/gmail/configure":
            assert req.post_data_json["credentials"]["web"]
            state.update(client_type="web", oauth_configured=True, pending_configuration=True)
            data = state
        elif path == "/api/gmail/test/preview":
            data = {"to": req.post_data_json["to"], "from_email": "test@example.com", "subject": "Beacon 邮箱发送测试", "body": "固定测试内容", "approval_token": "mock"}
        elif path == "/api/gmail/test/send":
            data = {"status": "sent", "id": "mock"}
        elif path == "/api/gmail/check":
            if hold_check:
                check_started.set()
                await release_check.wait()
            if fail_check:
                await r.fulfill(status=409, content_type="application/json", body='{"detail":"模拟连接失败"}')
                return
            data = state
        elif path == "/api/gmail/connect":
            assert req.post_data_json["purpose"] in ("send", "replies")
            state.update(pending_configuration=False, connected=True, send_authorized=True, token_present=True,
                         readonly_authorized=req.post_data_json["purpose"] == "replies", email="test@example.com")
            data = {"url": "http://localhost:3000/settings?gmail=connected"}
        else:
            await r.fulfill(status=503, content_type="application/json", body='{"detail":"模拟未配置"}')
            return
        await r.fulfill(content_type="application/json", body=json.dumps(data))
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.route("**/api/**", route)
        await page.goto("http://localhost:3000/settings")
        await expect(page.get_by_role("button", name=re.compile(r"连接 Gmail$"))).to_be_disabled()
        await expect(page.get_by_text(state["redirect_uri"], exact=True)).to_be_visible()
        await page.get_by_label("Web OAuth 客户端 JSON", exact=True).set_input_files({
            "name": "client.json", "mimeType": "application/json",
            "buffer": json.dumps({"web": {"client_id": "test", "client_secret": "mock", "redirect_uris": [state["redirect_uri"]]}}).encode()})
        await page.get_by_role("button", name="保存 Web 客户端", exact=True).click()
        await expect(page.get_by_role("button", name=re.compile(r"连接 Gmail$"))).to_be_enabled()
        await page.get_by_role("button", name=re.compile(r"连接 Gmail$")).click()
        await expect(page.get_by_text("Gmail 已连接。发送已暂停，请核对邮箱后再开启。", exact=True)).to_be_visible()
        await expect(page.get_by_text("test@example.com", exact=True)).to_be_visible()
        await page.get_by_role("button", name=re.compile(r"开启／重新授权回复同步$")).click()
        await expect(page.get_by_text("已授权邮件头读取", exact=False)).to_be_visible()
        await page.get_by_label("测试收件邮箱", exact=True).fill("self@example.com")
        await page.get_by_role("button", name="预览测试邮件", exact=True).click()
        await expect(page.get_by_text("收件人：self@example.com", exact=True)).to_be_visible()
        assert not any(path == "/api/gmail/test/send" for path, _ in writes)
        await page.get_by_role("button", name="确认发送一封", exact=True).click()
        await expect(page.get_by_text("Gmail 已接受测试邮件，请检查收件箱或垃圾邮件。", exact=True)).to_be_visible()
        assert sum(path == "/api/gmail/test/send" for path, _ in writes) == 1
        hold_check = True
        before_check = len(writes)
        await page.get_by_role("button", name=re.compile(r"检查连接$")).click()
        await asyncio.wait_for(check_started.wait(), timeout=5)
        card = page.locator(".ant-card").filter(has=page.get_by_text("Gmail 邮箱连接", exact=True)).first
        await expect(card.locator("button.ant-btn-loading")).to_have_count(1)
        await expect(page.get_by_role("button", name=re.compile(r"检查连接$"))).to_have_class(re.compile("ant-btn-loading"))
        for button in ("重新连接 Gmail", "刷新状态", "断开并暂停发送", "保存发送设置"):
            await expect(page.get_by_role("button", name=button, exact=True)).to_be_disabled()
        assert len(writes) == before_check + 1 and writes[-1][0] == "/api/gmail/check"
        await page.get_by_role("button", name=re.compile(r"检查连接$")).evaluate("button => { button.click(); button.click(); }")
        assert len(writes) == before_check + 1, "重复点击不得重复请求"
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await card.screenshot(path="data/devchecks/gmail-single-button-loading.png")
        release_check.set()
        await expect(card.locator("button.ant-btn-loading")).to_have_count(0)
        await expect(page.get_by_role("button", name="刷新状态", exact=True)).to_be_enabled()
        hold_check, fail_check = False, True
        await page.get_by_role("button", name="检查连接", exact=True).click()
        await expect(page.get_by_text("模拟连接失败", exact=True)).to_be_visible()
        await expect(card.locator("button.ant-btn-loading")).to_have_count(0)
        await expect(page.get_by_role("button", name="刷新状态", exact=True)).to_be_enabled()
        fail_check = False
        state["redirect_uri"] = "https://beacon.example.com/api/gmail/oauth/callback"
        await page.reload()
        await page.get_by_role("button", name=re.compile(r"重新连接 Gmail$")).click()
        await expect(page.get_by_text("当前访问地址与回调不一致，请从 https://beacon.example.com/settings 打开工作台后重新连接。", exact=True)).to_be_visible()
        state["redirect_uri"] = "http://localhost:3000/api/gmail/oauth/callback"
        await page.goto("http://localhost:3000/settings?gmail=failed&gmail_error=invalid_grant")
        await expect(page.get_by_text("Google 授权失效或授权码不可用，请重新连接。若反复失效，请核对 Google 项目的 Testing 状态。", exact=True)).to_be_visible()
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/gmail-web-oauth.png", full_page=True)
        await page.locator(".ant-card").filter(has=page.get_by_text("Gmail 邮箱连接", exact=True)).first.screenshot(path="data/devchecks/gmail-web-oauth-card.png")
        assert len(writes) == 7 and not any(path.endswith("/send") and "/test/" not in path for path, _ in writes)
        await browser.close()
        print("Gmail web UI passed: OAuth, test mail preview/confirmation, isolated button loading, duplicate prevention, failure recovery, invalid_grant; no external requests")

asyncio.run(main())
