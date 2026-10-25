"""单家完善 UI 回归：全 API 模拟，不查询真实门店或调用模型。"""
import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
import verify_detail_workspace_ui as fixture


async def main():
    state = {"items": [dict(key=k, title=t, needed=True, updated_at=None, description=d) for k, t, d in [
        ("website", "门店与官网", "官网读取未完成，已有网址保留"),
        ("contacts", "联系方式", "已有候选 2 项；页面读取失败 1 页"),
        ("menus", "菜单获取", "尚无菜单；也可上传文件"),
        ("analysis", "菜单 AI 分析", "取得菜单后再分析"),
    ]], "task": None}
    requests = []
    errors = []

    async def handle(route):
        path = urlsplit(route.request.url).path
        if "/enrichment" not in path:
            return await fixture.handle(route)
        method = route.request.method
        if method == "POST":
            requests.append((path, route.request.post_data_json))
            if path.endswith("/cancel"):
                state["task"]["status"] = "cancelled"
                data = state["task"]
            else:
                body = route.request.post_data_json
                state["task"] = dict(id="single1", status="pending", single=True, step=0, steps=body["items"], results=[], error=None, message="正在完善这家门店", updated_at="2026-10-25T12:00:00Z")
                data = dict(task=state["task"], reused=False)
        else:
            data = copy.deepcopy(state)
        await route.fulfill(content_type="application/json", body=json.dumps(data))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport=dict(width=1500, height=1050))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{fixture.ID}")
        await expect(page.get_by_text("4 项可继续完善", exact=True)).to_be_visible()
        assert not requests, "Reading detail must not start work"
        await page.get_by_role("button", name="继续完善", exact=True).click()
        drawer = page.get_by_role("dialog")
        await expect(drawer.get_by_text("继续完善这家门店", exact=True)).to_be_visible()
        await drawer.get_by_role("checkbox", name="菜单获取", exact=True).uncheck()
        await drawer.get_by_role("checkbox", name="菜单 AI 分析", exact=True).uncheck()
        await drawer.get_by_role("button", name="开始完善所选项").click()
        await expect(drawer.get_by_text("正在完善这家门店", exact=True)).to_be_visible()
        assert requests[-1][1] == dict(mode="continue", items=["website", "contacts"])
        await drawer.get_by_role("button", name="关闭", exact=True).click()
        await page.reload()
        await page.get_by_role("button", name="查看完善进度", exact=True).click()
        await expect(drawer.get_by_text("正在完善这家门店", exact=True)).to_be_visible()
        await drawer.get_by_role("button", name="结束本次完善").click()
        await expect(drawer.get_by_text("本次完善已结束，已取得的结果保留", exact=True)).to_be_visible()
        await drawer.get_by_role("button", name="关闭", exact=True).click()
        await page.get_by_role("button", name="重新完善", exact=True).click()
        await expect(drawer.get_by_text("重新完善这家门店", exact=True)).to_be_visible()
        for name in ("门店与官网", "菜单获取", "菜单 AI 分析"):
            await drawer.get_by_role("checkbox", name=name, exact=True).uncheck()
        await drawer.get_by_role("button", name="更新所选资料").click()
        assert requests[-1][1] == dict(mode="refresh", items=["contacts"])
        state["task"].update(status="failed", step=1, error="部分资料未补齐，已有结果可继续使用", results=[dict(key="contacts", status="failed", message="官网连接超时，候选已保留", at="2026-10-25T12:00:00Z")])
        await expect(drawer.get_by_text("官网连接超时，候选已保留", exact=True)).to_be_visible(timeout=10000)
        await expect(drawer.get_by_role("button", name="重试此项")).to_be_enabled()
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.wait_for_timeout(400)  # Let checkbox and drawer transitions settle for visual QA.
        await page.screenshot(path="data/devchecks/lead-enrichment-drawer.png", full_page=True)
        await drawer.get_by_role("button", name="关闭", exact=True).click()
        await expect(drawer).not_to_be_visible()
        await page.screenshot(path="data/devchecks/lead-enrichment-overview.png", full_page=True)
        # A bulk task is displayed, but cannot be cancelled from a single lead.
        state["task"].update(single=False, status="running", steps=["google", "contacts"], step=1, results=[], error=None, message="已有名单任务包含这家门店，沿用该任务进度")
        await page.reload()
        await page.get_by_role("button", name="查看完善进度", exact=True).click()
        await expect(drawer.get_by_text("批量任务请在名单页面管理", exact=True)).to_be_visible()
        await expect(drawer.get_by_role("button", name="结束本次完善")).to_have_count(0)
        await page.set_viewport_size(dict(width=700, height=1000))
        await page.screenshot(path="data/devchecks/lead-enrichment-narrow.png", full_page=True)
        assert not errors, errors
        await browser.close()
    print("PASS: read-only overview, selected continuation/refresh, reload recovery, cancel, failure and bulk reuse")


if __name__ == "__main__":
    asyncio.run(main())
