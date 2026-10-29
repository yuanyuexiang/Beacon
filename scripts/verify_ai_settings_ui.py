"""AI settings UI regression; synthetic API fixtures only, no providers or real saves."""

import asyncio
import copy
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect


async def main():
    state = {
        "version": None,
        "source": "environment",
        "connections": [],
        "routes": {},
        "environment": None,
        "presets": [
            {
                "id": "deepseek",
                "label": "DeepSeek",
                "protocol": "chat",
                "base_url": "https://api.deepseek.com",
            },
            {
                "id": "custom",
                "label": "自定义兼容接口",
                "protocol": "chat",
                "base_url": "",
            },
        ],
    }
    calls = []
    errors = []

    async def handle(route):
        path = urlsplit(route.request.url).path
        method = route.request.method
        calls.append((method, path))
        if path == "/api/auth/me":
            data = {
                "id": "admin",
                "username": "admin",
                "role": "admin",
                "must_change_password": False,
            }
        elif path == "/api/ai/settings":
            if method == "PUT":
                values = route.request.post_data_json
                state.update(copy.deepcopy(values))
                state.update(version="version-one", source="managed")
                for row in state["connections"]:
                    row.pop("key", None)
                    row["key_configured"] = True
            data = state
        elif path == "/api/ai/models":
            await asyncio.sleep(2)
            assert route.request.post_data_json["key"] in ("fake-key-for-ui-only", "")
            data = {"models": ["mock-model", "other-model"]}
        elif path.endswith("/test"):
            state["connections"][0]["test"] = {
                "at": "2026-10-29T01:00:00Z",
                "status": "failed",
                "checks": {
                    "structured": {
                        "status": "failed",
                        "error": "AI 密钥无效（HTTP 401）",
                        "duration_ms": 150,
                    }
                },
            }
            data = state["connections"][0]["test"]
        elif path == "/api/ai/calls":
            data = []
        else:
            data = {}
        await route.fulfill(content_type="application/json", body=json.dumps(data))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(
            os.environ.get("BEACON_UI_TEST_URL", "http://localhost:3000")
            + "/settings?section=ai"
        )
        await page.get_by_role("button", name="添加连接", exact=True).click()
        await page.get_by_label("连接名称", exact=True).fill("测试资料模型")
        await page.get_by_label("API Key", exact=True).fill("fake-key-for-ui-only")
        await page.get_by_role("button", name="获取模型", exact=True).click()
        await expect(page.get_by_role("button", name="加入配置", exact=True)).not_to_have_class(re.compile("ant-btn-loading"))
        await expect(page.get_by_text("已获取 2 个模型", exact=False)).to_be_visible()
        await page.get_by_role("combobox", name="模型 ID", exact=True).click()
        await page.get_by_title("mock-model", exact=True).click()
        await page.get_by_role("button", name="加入配置", exact=True).click()
        await expect(page.get_by_role("dialog")).to_have_count(0)
        await page.get_by_role("combobox", name="默认模型", exact=True).click()
        await page.get_by_title("测试资料模型 · mock-model", exact=True).click()
        await page.get_by_role("button", name="保存 AI 配置", exact=True).click()
        await expect(
            page.get_by_role("button", name="测试能力", exact=True)
        ).to_be_enabled()
        await page.get_by_role("button", name="测试能力", exact=True).click()
        await expect(page.get_by_text("测试失败", exact=True)).to_be_visible()
        await expect(
            page.get_by_text("JSON 解析：AI 密钥无效（HTTP 401） · 0.1 秒", exact=True)
        ).to_be_visible()
        await page.reload()
        await expect(page.get_by_text("测试失败", exact=True)).to_be_visible()
        await page.get_by_role("button", name=re.compile(r"编\s*辑")).click()
        await expect(page.get_by_label("API Key", exact=True)).to_have_value("")
        await page.get_by_role("button", name="获取模型", exact=True).click()
        await expect(page.get_by_role("button", name="加入配置", exact=True)).not_to_have_class(re.compile("ant-btn-loading"))
        await expect(page.get_by_text("已获取 2 个模型", exact=False)).to_be_visible()
        await expect(page.get_by_title("other-model", exact=True)).to_be_visible()
        await page.get_by_label("连接名称", exact=True).fill("草稿连接名")
        await page.get_by_role("button", name="加入配置", exact=True).click()
        await (
            page.get_by_role("navigation", name="设置分类")
            .get_by_role("button", name="操作指南", exact=False)
            .click()
        )
        await (
            page.get_by_role("navigation", name="设置分类")
            .get_by_role("button", name="AI 模型", exact=False)
            .click()
        )
        await expect(page.get_by_text("草稿连接名", exact=True)).to_be_visible()
        assert not any("/gmail/" in path or "/outreach/" in path for _, path in calls)
        out = Path("data/devchecks")
        out.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out / "ai-settings-desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 480, "height": 920})
        await expect(
            page.get_by_role("button", name="展开侧边栏", exact=True)
        ).to_be_visible()
        await page.screenshot(path=str(out / "ai-settings-mobile.png"), full_page=True)
        assert not errors, errors
        await browser.close()
    print(
        "AI settings creation, routing, tests, redaction and navigation drafts passed; all APIs mocked."
    )


asyncio.run(main())
