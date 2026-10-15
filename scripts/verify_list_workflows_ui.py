"""本地生产界面回归：拦截全部 API 使用脱敏夹具，不写真实名单、不访问外部数据服务。

仓库根目录运行：
uv run --project apps/api --extra maps-worker python scripts/verify_list_workflows_ui.py
需 localhost:3000 已运行并安装本机 Chrome；截图保存在受控 data/devchecks/。
"""

import asyncio
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

batches = []
tasks = {}
leads = {}
requests = []
advances = []
errors = []
fail_overture = True
hold = False
release = asyncio.Event()


def make_task(key, body):
    task = {
        "id": f"task-{len(tasks)}-{len(requests)}",
        "batch_id": key,
        "kind": body["kind"],
        "status": "pending",
        "step": 0,
        "steps": (["pool"] if body["kind"] != "enrich" else [])
        + ["overture", "google", "screen", "contacts"],
        "params": {**body, "seed": None} if body["kind"] != "enrich" else {},
        "results": [],
        "error": None,
    }
    tasks[key] = task
    return task


async def handle(route):
    global fail_overture
    request = route.request
    path = urlsplit(request.url).path
    body = (
        request.post_data_json
        if request.method == "POST"
        and request.headers.get("content-type", "").startswith("application/json")
        else None
    )
    requests.append((request.method, path, body))
    status = 200
    if path == "/api/auth/me":
        result = {"username": "ui-test"}
    elif path == "/api/directory/regions":
        result = [
            {
                "id": 277,
                "name": "Adur",
                "region": "South East",
                "count": 464,
                "pool_count": 3,
                "last_success_at": "2026-10-15T00:00:00Z",
                "type_versions": {"1": {}, "7843": {}, "7844": {}},
            }
        ]
    elif path == "/api/batches" and request.method == "GET":
        result = batches
    elif path in ["/api/batches", "/api/lists"]:
        batch = {**body, "id": body["batch_key"], "candidate_count": 0}
        batches.insert(0, batch)
        leads[body["batch_key"]] = []
        result = (
            {"batch": batch, "workflow": make_task(body["batch_key"], body["workflow"])}
            if path == "/api/lists"
            else batch
        )
        status = 201
    elif path == "/api/leads":
        from urllib.parse import parse_qs

        key = parse_qs(urlsplit(request.url).query)["batch_key"][0]
        result = leads.get(key, [])
    elif "/workflow" in path:
        key = path.split("/")[3]
        if request.method == "GET":
            result = tasks.get(key)
        elif path.endswith("/workflow"):
            result = make_task(key, body)
            status = 201
        elif path.endswith("/cancel"):
            tasks[key]["status"] = "cancelled"
            result = tasks[key]
        elif path.endswith("/advance"):
            t = tasks[key]
            stage = t["steps"][t["step"]]
            advances.append((key, t["id"], stage))
            if hold:
                t["status"] = "running"
                await release.wait()
            if stage == "overture" and fail_overture:
                fail_overture = False
                t.update(status="failed", error="模拟网络中断；已保存检查点")
            else:
                if stage == "pool":
                    previous = len(leads[key])
                    count = 3 if not previous else 2
                    leads[key] += [
                        {
                            "id": str(i),
                            "source_key": f"fsa:{i}",
                            "name": f"Restaurant {i}",
                            "postcode": "BN1",
                            "website": None,
                            "screening_class": "unchecked",
                            "entity_status": "unknown",
                            "contact_count": 0,
                            "business_type_id": 1,
                        }
                        for i in range(previous, previous + count)
                    ]
                    for b in batches:
                        if b["batch_key"] == key:
                            b["candidate_count"] = len(leads[key])
                    r = {
                        "fetched": previous + count,
                        "already_in_list": previous,
                        "pool": count,
                        "selected": count,
                        "created": count,
                        "linked": 0,
                    }
                elif stage == "overture":
                    r = {
                        "leads": len(leads[key]),
                        "matched": 2,
                        "website_set": 2,
                        "phone_found": 1,
                    }
                elif stage == "google":
                    r = {"verified": 1, "review": 1, "failed": 0, "done": True}
                elif stage == "screen":
                    r = {"counts": {"unchecked": len(leads[key])}}
                else:
                    r = {
                        "totals": {
                            "succeeded": 2,
                            "failed": 0,
                            "pending": 0,
                            "running": 0,
                        }
                    }
                t["results"] = t["results"][: t["step"]] + [r]
                t["step"] += 1
                t.update(
                    status="completed" if t["step"] == len(t["steps"]) else "pending",
                    error=None,
                )
            result = copy.deepcopy(t)
        else:
            raise AssertionError(path)
    elif path == "/api/imports":
        result = {"created_count": 1, "linked_count": 0, "error_count": 0}
    else:
        raise AssertionError(path)
    await route.fulfill(
        status=status, content_type="application/json", body=json.dumps(result)
    )


async def main():
    global hold
    Path("data/devchecks").mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1100})
        await page.route("**/api/**", handle)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        await page.goto("http://localhost:3000/leads")
        await page.get_by_text("ui-test", exact=True).wait_for()
        await page.get_by_role("button", name="建立名单", exact=True).click()
        await page.get_by_label("地区", exact=True).click()
        await page.locator(".ant-select-item-option").filter(has_text="Adur").click()
        assert await page.get_by_label("获取餐厅数量", exact=True).count() == 0
        await expect(
            page.get_by_text("从门店池选入所选类型的全部商户", exact=True)
        ).to_be_visible()
        await page.get_by_label("商户类型", exact=True).click()
        await (
            page.locator(".ant-select-item-option")
            .filter(has_text="外卖店、三明治店")
            .click()
        )
        await (
            page.locator(".ant-select-item-option")
            .filter(has_text="酒吧、Pub、夜店")
            .click()
        )
        await page.get_by_label("名单名称", exact=True).fill("ui-workflow")
        await page.get_by_role("button", name="创建并开始获取", exact=True).click()
        await page.get_by_role("button", name="重试未完成步骤", exact=True).wait_for()
        await expect(
            page.get_by_text(
                "本次补充已停止。关闭面板即可继续操作名单；重试只处理未完成项。",
                exact=True,
            )
        ).to_be_visible()
        await expect(
            page.get_by_role("button", name="追加商户", exact=True)
        ).to_be_enabled()
        await expect(
            page.get_by_role("button", name="建立名单", exact=True)
        ).to_be_enabled()
        assert len([s for _, _, s in advances if s == "pool"]) == 1
        assert tasks["ui-workflow"]["params"]["sample_n"] is None
        assert sorted(tasks["ui-workflow"]["params"]["business_type_ids"]) == [
            1,
            7843,
            7844,
        ]
        await page.locator(".ant-drawer-close").click()
        await page.reload()
        await page.get_by_role("button", name="查看 / 继续任务", exact=True).click()
        await page.get_by_role("button", name="重试未完成步骤", exact=True).click()
        await page.get_by_text("处理完成", exact=True).wait_for()
        assert len([s for _, _, s in advances if s == "pool"]) == 1
        await page.locator(".ant-drawer-close").click()
        await page.get_by_role("button", name="完善名单", exact=True).click()
        before = len(advances)
        hold = True
        await page.get_by_role("button", name="开始完善名单", exact=True).click()
        await expect(
            page.get_by_role("dialog").get_by_role(
                "button", name=re.compile("继续任务")
            )
        ).to_be_disabled()
        await expect(
            page.get_by_role("button", name="追加 CSV", exact=True)
        ).to_be_disabled()
        await expect(
            page.get_by_role("button", name="批量抓取 + 分析", exact=True)
        ).to_be_disabled()
        await expect(
            page.get_by_role("button", name="删除批次", exact=True)
        ).to_be_disabled()
        await expect(page.locator(".ant-select-disabled").first).to_be_visible()
        hold = False
        release.set()
        await page.get_by_text("处理完成", exact=True).wait_for()
        assert [s for _, _, s in advances[before:]] == [
            "overture",
            "google",
            "screen",
            "contacts",
        ]
        await page.locator(".ant-drawer-close").click()
        await page.get_by_role("button", name="追加商户", exact=True).click()
        await expect(
            page.get_by_role("dialog").get_by_label("地区", exact=True)
        ).to_be_disabled()
        await expect(
            page.get_by_role("dialog").get_by_label("地区", exact=True)
        ).to_have_value("Adur")
        assert await page.get_by_label("追加商户数量", exact=True).count() == 0
        await page.wait_for_timeout(400)
        await page.screenshot(
            path="data/devchecks/list-workflow-append.png", full_page=True
        )
        await page.get_by_role("button", name="追加并完善", exact=True).click()
        await page.get_by_text("处理完成", exact=True).wait_for()
        assert tasks["ui-workflow"]["params"]["sample_n"] is None
        assert len(leads["ui-workflow"]) == 5
        await page.wait_for_timeout(400)
        await page.screenshot(
            path="data/devchecks/list-workflow-complete.png", full_page=True
        )
        await page.locator(".ant-drawer-close").click()
        # 完整保留 CSV、空名单创建路径。
        await page.get_by_role("button", name="建立名单", exact=True).click()
        await page.get_by_role("radio", name="导入 CSV", exact=True).check()
        await page.get_by_label("名单名称", exact=True).fill("ui-csv")
        await (
            page.get_by_role("dialog")
            .locator("input[type=file]")
            .set_input_files(
                {
                    "name": "test.csv",
                    "mimeType": "text/csv",
                    "buffer": b"source_key,name\nfsa:123,Test Restaurant\n",
                }
            )
        )
        await page.get_by_role("button", name=re.compile("创建并导入$")).click()
        await expect(page.get_by_role("dialog")).to_have_count(0)
        await expect(
            page.get_by_role("button", name="建立名单", exact=True)
        ).to_be_enabled()
        await page.get_by_role("button", name="建立名单", exact=True).click()
        await page.get_by_role("radio", name="仅建空名单", exact=True).check()
        await page.get_by_label("名单名称", exact=True).fill("ui-empty")
        await page.get_by_role("button", name=re.compile("创建空名单$")).click()
        await expect(page.get_by_role("dialog")).to_have_count(0)
        assert len([r for r in requests if r[:2] == ("POST", "/api/imports")]) == 1
        assert not errors, errors
        print(
            "Verified local production UI: create multi-type list, persisted refresh/retry, new lists use cached pool and enrich skips FSA, append full remaining members in fixed region, running controls locked, CSV and empty list; zero page errors."
        )
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
