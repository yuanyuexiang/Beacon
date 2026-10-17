"""D61 统计与失败明细界面回归，全部 API 模拟，不访问官网或修改真实名单。"""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

LEADS = [{"id": str(i), "name": f"Restaurant {i}", "source_key": f"fsa:{i}", "website": "https://example.com", "postcode": "AB1", "screening_class": "candidate", "entity_status": "unknown", "contact_count": 1} for i in range(3)]
TOTALS = {"succeeded": 1, "failed": 2, "pending": 0, "running": 0, "read_complete": 1, "read_partial": 1, "read_failed": 1, "with_contacts": 2}
WORKFLOW = {"id": "workflow", "batch_id": "batch", "kind": "enrich", "status": "failed", "step": 0, "steps": ["contacts"], "params": {}, "results": [{"totals": TOTALS, "run_id": "run"}], "error": "部分读取 1 家，读取失败 1 家；成功结果已保留"}
errors = []
mutations = []


async def handle(route):
    request = route.request
    path = urlsplit(request.url).path
    if request.method != "GET":
        mutations.append(path)
    if path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": "admin", "must_change_password": False}
    elif path == "/api/batches":
        data = [{"id": "batch", "batch_key": "contact-test", "country": "UK", "region": "Aberdeen", "candidate_count": 3}]
    elif path == "/api/leads":
        data = LEADS
    elif path.endswith("/workflow"):
        data = WORKFLOW
    elif path == "/api/runs/run":
        data = {"totals": TOTALS, "jobs": [
            {"id": "partial", "lead_id": "1", "step": "contacts", "status": "failed", "error": "部分读取", "contact_result": {"page_errors": [{"url": "https://example.com/contact", "error": "ConnectError: SSL UNEXPECTED_EOF"}]}},
            {"id": "failed", "lead_id": "2", "step": "contacts", "status": "failed", "error": "读取失败", "contact_result": {"page_errors": [{"url": "https://example.com", "error": "ValueError: HTTP 502（unknown）"}]}},
        ]}
    else:
        errors.append(path)
        data = {}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/leads?batch=contact-test")
        await page.get_by_role("button", name="查看 / 继续任务").click()
        await expect(page.get_by_text("读取完成 1，部分读取 1，读取失败 1；找到联系方式 2 家；待处理 0", exact=True)).to_be_visible()
        await page.get_by_text("查看未完成门店与具体原因", exact=True).click()
        await expect(page.get_by_text("HTTPS／SSL 连接中断或证书错误", exact=True)).to_be_visible()
        await expect(page.get_by_text("网站或上游网关异常（5xx）", exact=True)).to_be_visible()
        await page.locator(".ant-collapse-content").evaluate("el => Promise.all(el.getAnimations({subtree: true}).map(a => a.finished.catch(() => {})))")
        await page.get_by_text("原始记录", exact=True).first.click()
        await expect(page.get_by_text("ConnectError: SSL UNEXPECTED_EOF", exact=False)).to_be_visible()
        output = Path("data/devchecks/d61-contact-read.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output), full_page=True, animations="disabled")
        assert not errors, errors
        assert not mutations, mutations
        await browser.close()
    print("D61 UI passed: read categories, contact counts, per-site reasons; zero mutations")


asyncio.run(main())
