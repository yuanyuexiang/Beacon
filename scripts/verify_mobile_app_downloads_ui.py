"""APK management/download UI with fully mocked APIs. No real upload, publication or device changes."""

import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect


async def verify(browser, role):
    first = dict(id="first", version_name="1.0.0", version_code=1, size=110 * 1024**2, sha256="a" * 64,
                 signer_sha256="c" * 64, uploaded_at="2026-11-18T08:00:00Z", notes="当前稳定版本")
    second = dict(first, id="second", version_code=2, version_name="1.1.0", sha256="b" * 64)
    current, previous, drafts = first, None, []
    calls, errors = [], []
    page = await browser.new_page(viewport={"width":1500,"height":1100})
    page.on("pageerror", lambda error: errors.append(str(error)))

    async def handle(route):
        nonlocal current, previous, drafts
        request, path = route.request, urlsplit(route.request.url).path
        calls.append((path, request.method))
        if path == "/api/auth/me":
            data = dict(id="user", username="tester", role=role, must_change_password=False)
        elif path == "/api/mobile/app":
            data = dict(current=current, previous=previous, drafts=drafts if role=="admin" else [],
                        max_bytes=256*1024**2, server="https://beacon.example", validator_available=True)
        elif path == "/api/mobile/app/uploads":
            assert role=="admin"
            if request.post_data_buffer == b"bad":
                await route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail":"APK 签名校验失败"}))
                return
            drafts = [second]
            data = second
        elif path.endswith("/publish"):
            assert role=="admin"
            body=request.post_data_json
            assert body["expected_current_id"]==current["id"]
            previous,current=current,dict(first if body["rollback"] else second,notes=body["notes"])
            drafts=[]
            data={"ok":True}
        elif path == "/api/mobile/app/download-link":
            data=dict(path=f"/api/mobile/app-download/{current['id']}?token=mock-download-only",
                      expires_at=(datetime.now(UTC)+timedelta(minutes=15)).isoformat())
        elif path.startswith("/api/mobile/app-download/"):
            await route.fulfill(body=b"mock apk download", content_type="application/vnd.android.package-archive",
                                headers={"Content-Disposition":"attachment; filename=Beacon.apk"})
            return
        elif path == "/api/mobile/devices":
            data=[]
        elif path == "/api/mobile/pairing":
            data=dict(code="123456",owner="tester",server="https://beacon.example",
                      expires_at=(datetime.now(UTC)+timedelta(minutes=5)).isoformat())
        else:
            data={}
        await route.fulfill(content_type="application/json", body=json.dumps(data))

    await page.route("**/api/**",handle)
    await page.goto(os.environ.get("BEACON_UI_BASE","http://localhost:3001")+"/devices")
    await expect(page.get_by_text("1.0.0 · 构建 1",exact=True)).to_be_visible()
    await page.get_by_role("button",name="手机扫码下载",exact=True).click()
    await expect(page.get_by_text("扫码下载安装包 · 不是设备配对码",exact=True)).to_be_visible()
    await expect(page.locator(".ant-qrcode")).to_be_visible()
    await expect(page.get_by_role("link",name="在本机下载同一安装包",exact=True)).to_have_attribute("href","/api/mobile/app-download/first?token=mock-download-only")
    # QR download is independent of device pairing; both are clearly named.
    await page.get_by_role("button",name="绑定新手机",exact=True).click()
    await expect(page.get_by_text("用 Beacon 手机助手扫码配对",exact=True)).to_be_visible()
    assert await page.locator(".ant-qrcode").count()==2
    async with page.expect_download() as download:
        await page.get_by_role("button",name="下载 Android App",exact=True).click()
    assert (await download.value).suggested_filename=="Beacon.apk"
    if role=="admin":
        await page.get_by_text("安装包管理 · 仅管理员",exact=True).click()
        await page.get_by_label("选择 Android APK",exact=True).set_input_files({"name":"bad.apk","mimeType":"application/vnd.android.package-archive","buffer":b"bad"})
        await page.get_by_role("button",name=re.compile("上传并校验$")).click()
        await expect(page.get_by_text("APK 签名校验失败",exact=True)).to_be_visible()
        assert current["id"]=="first"
        await page.get_by_label("选择 Android APK",exact=True).set_input_files({"name":"Beacon.apk","mimeType":"application/vnd.android.package-archive","buffer":b"mock apk"})
        await page.get_by_role("button",name=re.compile("上传并校验$")).click()
        await expect(page.get_by_text("待发布",exact=True)).to_be_visible()
        assert current["id"]=="first"
        await page.get_by_role("textbox",name="App 更新说明",exact=True).fill("修复任务结束后返回 App")
        await page.get_by_role("button",name="发布此版本",exact=True).click()
        await expect(page.get_by_text("发布这个安装包？",exact=True).last).to_be_visible()
        await page.locator(".ant-modal-confirm").get_by_role("button",name="发布此版本",exact=True).click()
        await expect(page.get_by_text("安装包已发布",exact=True)).to_be_visible()
        assert current["id"]=="second" and current["notes"]=="修复任务结束后返回 App"
        await page.get_by_role("button",name="回退到上一版本",exact=True).click()
        await page.locator(".ant-modal-confirm").get_by_role("button",name="确认回退",exact=True).click()
        await expect(page.get_by_text("已回退下载版本",exact=True)).to_be_visible()
        assert current["id"]=="first"
        await expect(page.locator(".ant-modal-confirm")).to_have_count(0)
    else:
        await expect(page.get_by_text("安装包管理 · 仅管理员",exact=True)).to_have_count(0)
        assert not any(path.endswith("/uploads") or path.endswith("/publish") for path,_ in calls)
    folder=Path("data/devchecks/mobile-app");folder.mkdir(parents=True,exist_ok=True)
    await page.screenshot(path=str(folder/f"{role}-desktop.png"),full_page=True)
    await page.set_viewport_size({"width":850,"height":1100})
    await page.wait_for_timeout(250)
    await expect(page.locator(".ant-layout-header")).to_have_count(1)
    await expect(page.get_by_text("1.0.0 · 构建 1",exact=True)).to_have_count(1)
    assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    await page.screenshot(path=str(folder/f"{role}-narrow.png"),full_page=False)
    assert not errors,errors
    await page.close()
    print(f"PASS: {role} app downloads, separate pairing QR, upload/publish permissions, responsive layout")


async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel="chrome",headless=True)
        for role in ("admin","director","member"):
            await verify(browser,role)
        await browser.close()


if __name__=="__main__":
    asyncio.run(main())
