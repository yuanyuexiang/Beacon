"""销售总监分配 UI 回归：所有 API 拦截，无真实门店写入或外部触达。"""

import asyncio
import json
import re
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

role = "director"
requests = []
errors = []
rows = [{"id": str(n), "source_key": f"fsa:{n}", "name": f"Store {n}", "postcode": "AB1", "website": None, "screening_class": "candidate", "entity_status": "unknown", "contact_count": 0, "business_type_id": 1, "assigned_to": "bob" if n == 3 else None} for n in (1, 2, 3)]


async def handle(route):
    r = route.request
    path = urlsplit(r.url).path
    body = r.post_data_json if r.method == "POST" else None
    requests.append((r.method, path, body))
    if path == "/api/auth/me":
        result = {"id": "ui", "username": "boss" if role == "director" else "alice", "display_name": None, "role": role, "must_change_password": False}
    elif path == "/api/batches":
        result = [{"id": "team", "batch_key": "team", "region": "Aberdeen", "country": "GB", "source_name": "fsa", "candidate_count": 3}]
    elif path == "/api/leads":
        result = rows if role == "director" else [p for p in rows if p["assigned_to"] == "alice"]
    elif path == "/api/directory/regions":
        result = []
    elif path.endswith("/workflow"):
        result = None
    elif path == "/api/assignment/members":
        result = [{"username": n, "display_name": n.title(), "leads": 0, "open_tasks": 2, "drafts": 1, "followups_due": 0, "last_communication_at": None} for n in ("alice", "bob")]
    elif path == "/api/assignment/preview":
        chosen = [p for p in rows if p["id"] in body["lead_ids"]]
        result = {"count": len(chosen), "owners": {"未分配": len(chosen)}, "expected": {p["id"]: p["assigned_to"] for p in chosen}}
    elif path == "/api/assignment/apply":
        assert body["expected"] == {"1": None, "2": None}
        assert body["assigned_to"] == "alice" and body["reason"] == "North team allocation"
        rows[0]["assigned_to"] = "alice"
        result = {"items": [{"lead_id": "1", "assigned_to": "alice", "changed": True}, {"lead_id": "2", "error": "门店负责人已变化，请重新预览"}]}
    else:
        errors.append(f"Unmocked: {r.method} {path}")
        result = {"detail": "unmocked"}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(result))


async def main():
    global role
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1680, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/leads?batch=team")
        await expect(page.get_by_text("销售总监", exact=True)).to_be_visible()
        await expect(page.get_by_role("link", name="Store 3", exact=True)).to_be_visible()
        await page.get_by_label("门店归属视图", exact=True).first.click()
        await page.get_by_title("未分配", exact=True).click()
        await expect(page.get_by_role("link", name="Store 3", exact=True)).to_have_count(0)
        await page.get_by_role("button", name="分配门店", exact=True).click()
        dialog = page.get_by_role("dialog", name="分配／转交门店", exact=True)
        await expect(dialog.get_by_text("尚未选择分配范围。可先勾选门店，或在这里明确选择当前筛选全部门店。", exact=True)).to_be_visible()
        assert not any(path == "/api/assignment/preview" for _, path, _ in requests)
        await expect(dialog.get_by_role("button", name="确认分配", exact=True)).to_be_disabled()
        await dialog.get_by_role("radio", name="当前筛选全部 2 家（包含其他分页）", exact=True).check()
        await expect(dialog.get_by_text("本次 2 家", exact=False)).to_be_visible()
        await dialog.get_by_text("查看团队工作量", exact=True).click()
        await expect(dialog.get_by_role("columnheader", name="未完成任务", exact=True)).to_be_visible()
        await page.get_by_label("门店接收人", exact=True).first.click()
        await page.locator(".ant-select-item-option").filter(has_text="Alice").click()
        await expect(page.locator(".ant-select-dropdown:visible")).to_have_count(0)
        await page.get_by_label("分配原因", exact=True).fill("North team allocation")
        await expect(page.get_by_label("分配原因", exact=True)).to_have_value("North team allocation")
        await page.screenshot(path="data/devchecks/d70-assignment-preview.png", full_page=True, animations="disabled")
        await dialog.get_by_role("button", name="确认分配", exact=True).click()
        await expect(dialog.get_by_text(re.compile("成功 1 家，失败 1 家"))).to_be_visible()
        await expect(dialog.get_by_text("门店负责人已变化，请重新预览", exact=True)).to_be_visible()
        await page.screenshot(path="data/devchecks/d70-assignment-result.png", full_page=True, animations="disabled")
        await dialog.locator(".ant-modal-close").click()
        await page.locator('.ant-table-row[data-row-key="2"]').get_by_role("checkbox").check()
        await page.get_by_role("button", name="分配门店", exact=True).click()
        await expect(dialog.get_by_text("本次 1 家", exact=False)).to_be_visible()
        assert [body for _, path, body in requests if path == "/api/assignment/preview"][-1]["lead_ids"] == ["2"]
        await dialog.locator(".ant-modal-close").click()
        role = "member"
        await page.reload()
        await expect(page.get_by_role("link", name="Store 1", exact=True)).to_be_visible()
        await expect(page.get_by_role("link", name="Store 2", exact=True)).to_have_count(0)
        await expect(page.get_by_role("button", name="分配门店", exact=True)).to_have_count(0)
        await expect(page.get_by_role("link", name="门店池", exact=True)).to_have_count(0)
        await expect(page.get_by_role("combobox", name="门店归属视图", exact=True)).to_be_disabled()
        await expect(page.get_by_role("button", name="建立名单", exact=True)).to_be_disabled()
        await page.screenshot(path="data/devchecks/d70-my-leads.png", full_page=True, animations="disabled")
        assert not errors, errors
        assert all(path.startswith("/api/assignment/") for method, path, _ in requests if method == "POST")
        await browser.close()
    print("D70 UI passed: director, filtered preview, workload, partial results, member scope and controls; no real writes or sends")


asyncio.run(main())
