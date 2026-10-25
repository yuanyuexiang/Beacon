"""British English settings and personal signature; mock APIs, no sends or real data writes."""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect


async def main():
    profile = dict(version="initial", company="", services="", proof="", constraints="", tone="professional", opt_out_text="Please let me know if you would prefer not to hear from us again.")
    own = dict(version="initial", name="", role="", sender_identity="")
    role = "admin"
    writes, requests, errors = [], [], []
    release = asyncio.Event()
    hold = False

    async def handle(route):
        nonlocal profile, own
        request = route.request
        path = urlsplit(request.url).path
        requests.append((path, request.method))
        if path == "/api/auth/me":
            data = dict(id="ui", username="ui", role=role, must_change_password=False)
        elif path == "/api/outreach-profile":
            if request.method == "PUT":
                profile = {**request.post_data_json, "version": "saved"}
                writes.append(profile)
            data = profile
        elif path == "/api/outreach-identity":
            if request.method == "PUT":
                own = {**request.post_data_json, "version": "own-saved", "sender_identity": "Alice\nExample Studio"}
            data = own
        elif path == "/api/outreach-profile/organise":
            if hold:
                await release.wait()
            data = dict(english_summary="We provide menu layout design.", missing=["报价需按需求确认"])
        elif path == "/api/outreach-profile/preview":
            data = dict(subject="A question about your menus", body="Hello,\n\nCould you point me to the person responsible for menus?\n\nTom\nExample Studio\n\nPlease let me know if you would prefer not to hear from us again.", translation_zh="您好，请问谁负责贵店的菜单？", rationale="未提供菜单，因此先询问负责人。", missing=[])
        else:
            data = {}
        await route.fulfill(content_type="application/json", body=json.dumps(data))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport=dict(width=1600, height=1100))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/settings?section=profile")
        await page.get_by_label("公司／品牌介绍", exact=True).fill("真实菜单工作室")
        await page.get_by_label("菜单设计与印刷服务", exact=True).fill("提供菜单排版设计")
        await page.get_by_label("英文品牌名称", exact=True).fill("Example Studio")
        await page.get_by_label("默认发件人英文姓名", exact=True).fill("Tom")
        # A model response must not overwrite newer edits, and other buttons must not spin.
        hold = True
        await page.get_by_role("button", name="AI 整理英文介绍", exact=True).click()
        await expect(page.get_by_role("button", name="AI 整理英文介绍")).to_have_class(re.compile(".*ant-btn-loading.*"))
        await expect(page.get_by_role("button", name="预览英文示例", exact=True)).not_to_have_class(re.compile(".*ant-btn-loading.*"))
        await page.get_by_label("菜单设计与印刷服务", exact=True).fill("提供菜单排版设计，不承诺交期")
        release.set()
        await expect(page.get_by_text("资料已修改，请根据最新资料重新生成。", exact=True)).to_be_visible()
        hold = False
        await page.get_by_role("button", name="AI 整理英文介绍", exact=True).click()
        await expect(page.get_by_role("button", name="采用英文介绍", exact=True)).to_be_visible()
        await page.get_by_role("button", name="采用英文介绍", exact=True).click()
        await expect(page.get_by_label("英文服务介绍（可选）", exact=True)).to_have_value("We provide menu layout design.")
        assert not writes
        await page.get_by_role("button", name="预览英文示例", exact=True).click()
        await expect(page.get_by_text("英文邮件示例 · 未发送", exact=True)).to_be_visible()
        await page.get_by_text("中文对照与起草说明（仅内部查看）", exact=True).click()
        await expect(page.get_by_text("您好，请问谁负责贵店的菜单？", exact=True)).to_be_visible()
        assert not writes
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/outreach-profile-settings.png", full_page=True)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
        await page.screenshot(path="data/devchecks/outreach-profile-top.png")
        await page.get_by_role("button", name="保存服务资料", exact=True).click()
        await expect(page.get_by_text("服务资料已保存", exact=True)).to_be_visible()
        assert len(writes) == 1 and writes[0]["english_brand"] == "Example Studio"
        role = "member"
        await page.goto("http://localhost:3000/account")
        await page.get_by_label("我的英文姓名", exact=True).fill("Alice")
        await page.get_by_role("button", name="保存我的署名", exact=True).click()
        await expect(page.get_by_text("个人署名已保存", exact=True)).to_be_visible()
        await page.goto("http://localhost:3000/settings")
        await expect(page.get_by_text("此页面仅限管理员使用", exact=True)).to_be_visible()
        assert len(writes) == 1
        assert not errors, errors
        assert not any("/send" in path or "/tasks" in path for path, _ in requests)
        await browser.close()
    print("PASS: Chinese facts, English identity, explicit AI apply, stale result protection, independent loading, preview only, member signature")

asyncio.run(main())
