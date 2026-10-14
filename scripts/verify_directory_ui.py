"""门店池界面回归，拦截全部 API，不读取 FSA、不写实际数据。

仓库根目录运行：uv run --project apps/api --extra maps-worker python scripts/verify_directory_ui.py
需本机 Chrome 和 localhost:3000；截图在受控 data/devchecks/。
"""

import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect

regions = []
runs = []
entries = []
requests = []
errors = []
online = True
NOW = "2026-10-15T00:00:00Z"


def entry(identity, name, kind, present=True, discovered="baseline"):
    return {
        "fhrsid": identity,
        "name": name,
        "address": "Test Road",
        "postcode": "BN1",
        "business_type_id": kind,
        "present": present,
        "discovery_kind": discovered,
        "last_change_kind": discovered,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "last_changed_at": NOW,
        "inspection_pending": False,
    }


def queued():
    run = {
        "id": f"sync-{len(runs) + 1}",
        "status": "queued",
        "business_type_ids": [1, 7843, 7844],
        "created_at": NOW,
        "finished_at": None,
        "error": None,
        "counts": None,
    }
    runs.insert(0, run)
    regions[0]["latest_sync"] = run
    return run


def complete(changed=False):
    global entries
    if changed:
        entries = [
            entry(1, "Alpha revised", 1),
            entry(2, "Beta Pub", 7843, False),
            entry(3, "Gamma Takeaway", 7844),
            entry(4, "New Delta", 1, discovered="added"),
        ]
        entries[0]["last_change_kind"] = "changed"
    else:
        entries = [
            entry(1, "Alpha Restaurant", 1),
            entry(2, "Beta Pub", 7843),
            entry(3, "Gamma Takeaway", 7844),
        ]
    runs[0].update(
        status="completed",
        finished_at=NOW,
        counts={
            "baseline": 0 if changed else 3,
            "added": 1 if changed else 0,
            "changed": 1 if changed else 0,
            "missing": 1 if changed else 0,
            "reappeared": 0,
            "total": 3,
        },
    )
    regions[0].update(
        last_success_at=NOW,
        pool_count=3,
        counts={"1": 2 if changed else 1, "7843": 0 if changed else 1, "7844": 1},
        type_versions={str(k): {"synced_at": NOW} for k in [1, 7843, 7844]},
    )


async def handle(route):
    request = route.request
    url = urlsplit(request.url)
    path = url.path
    query = parse_qs(url.query)
    body = (
        request.post_data_json
        if request.method in {"POST", "PATCH"} and request.post_data
        else None
    )
    requests.append((request.method, path, body))
    status = 200
    if path == "/api/auth/me":
        result = {"username": "ui-test"}
    elif path == "/api/directory/status":
        result = {"online": online}
    elif path == "/api/directory/authorities":
        result = [{"id": 277, "name": "Adur", "region": "South East", "count": 464}]
    elif path == "/api/directory/authorities/refresh":
        result = {"count": 1}
    elif path == "/api/directory/regions" and request.method == "GET":
        result = regions
    elif path == "/api/directory/regions":
        regions.append(
            {
                "id": body["authority_id"],
                "name": "Adur",
                "region": "South East",
                "count": 464,
                "business_type_ids": body["business_type_ids"],
                "auto_sync": body["auto_sync"],
                "interval_hours": body["interval_hours"],
                "next_sync_at": NOW,
                "last_success_at": None,
                "pool_count": 0,
                "counts": {},
                "type_versions": {},
                "latest_sync": None,
            }
        )
        queued()
        result = regions[0]
        status = 201
    elif path == "/api/directory/regions/277":
        regions[0].update(body)
        result = regions[0]
    elif path.endswith("/sync"):
        result = queued()
        status = 202
    elif path.endswith("/syncs"):
        result = runs
    elif path == "/api/directory/entries":
        view = query.get("view", ["current"])[0]
        selected = [
            e
            for e in entries
            if view == "all"
            or (view == "current" and e["present"])
            or (view == "missing" and not e["present"])
            or (view == "added" and e["discovery_kind"] == "added")
            or (view == "changed" and e["last_change_kind"] == "changed")
        ]
        result = {"total": len(selected), "items": selected}
    elif path.endswith("/changes"):
        result = {
            "total": 3,
            "items": [
                {
                    "fhrsid": 1,
                    "name": "Alpha revised",
                    "kind": "changed",
                    "diff": {
                        "name": {"before": "Alpha Restaurant", "after": "Alpha revised"}
                    },
                },
                {"fhrsid": 2, "name": "Beta Pub", "kind": "missing", "diff": {}},
                {"fhrsid": 4, "name": "New Delta", "kind": "added", "diff": {}},
            ],
        }
    else:
        raise AssertionError(path)
    await route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(copy.deepcopy(result)),
    )


async def main():
    global online
    Path("data/devchecks").mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1550, "height": 1100})
        await page.route("**/api/**", handle)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        await page.goto("http://localhost:3000/directory")
        await page.get_by_text("ui-test", exact=True).wait_for()
        await page.get_by_role("button", name="添加地区", exact=True).click()
        await page.get_by_role("button", name="更新地区名录", exact=True).click()
        await page.get_by_label("地区", exact=True).click()
        await page.locator(".ant-select-item-option").filter(has_text="Adur").click()
        await expect(page.get_by_role("switch")).to_be_checked()
        await page.get_by_role("button", name="添加并首次同步", exact=True).click()
        await page.get_by_text("等待同步", exact=True).wait_for()
        post = next(
            r[2] for r in requests if r[:2] == ("POST", "/api/directory/regions")
        )
        assert (
            sorted(post["business_type_ids"]) == [1, 7843, 7844]
            and post["auto_sync"] is True
            and post["interval_hours"] == 24
        )
        complete()
        await page.get_by_text("Alpha Restaurant", exact=True).wait_for()
        assert await page.get_by_text("后续新增", exact=True).count() == 0
        await page.get_by_role("button", name="同步设置", exact=True).click()
        await page.get_by_role("switch").click()
        await page.get_by_role("button", name="保存设置", exact=True).click()
        await page.get_by_text("定期同步已关闭", exact=True).wait_for()
        await page.get_by_role("button", name="立即同步", exact=True).click()
        await page.get_by_text("等待同步", exact=True).wait_for()
        runs[0].update(status="failed", error="模拟连接中断")
        await page.get_by_text(
            "本次同步失败，继续使用最后成功的数据", exact=True
        ).wait_for()
        await expect(page.get_by_text("Alpha Restaurant", exact=True)).to_be_visible()
        online = False
        await page.get_by_text(
            "同步服务暂不可用，排队任务会保留", exact=True
        ).wait_for()
        await page.get_by_role("button", name="立即同步", exact=True).click()
        await page.get_by_text("等待同步", exact=True).wait_for()
        online = True
        complete(changed=True)
        await page.get_by_text("Alpha revised", exact=True).wait_for()
        await expect(page.get_by_text("New Delta", exact=True)).to_be_visible()
        await expect(page.get_by_text("Beta Pub", exact=True)).to_have_count(0)
        await page.wait_for_timeout(400)
        await page.screenshot(path="data/devchecks/directory-pool.png", full_page=True)
        await page.locator(".ant-select-selector").nth(1).click()
        await (
            page.locator(".ant-select-item-option")
            .filter(has_text="后续新增发现")
            .click()
        )
        await expect(page.get_by_text("Alpha revised", exact=True)).to_have_count(0)
        await expect(page.get_by_text("New Delta", exact=True)).to_be_visible()
        await page.locator(".ant-select-selector").nth(1).click()
        await (
            page.locator(".ant-select-item-option")
            .filter(has_text="本次未发现")
            .click()
        )
        await expect(page.get_by_text("Beta Pub", exact=True)).to_be_visible()
        await page.get_by_role("button", name="同步记录", exact=True).click()
        await page.get_by_text("查看新增与变更", exact=True).first.click()
        await page.get_by_text(
            "名称：Alpha Restaurant → Alpha revised", exact=True
        ).wait_for()
        await page.wait_for_timeout(400)
        await page.screenshot(
            path="data/devchecks/directory-history.png", full_page=True
        )
        assert not errors, errors
        print(
            "Verified directory UI: scope/daily defaults, queued sync, baseline, schedule pause, offline/failure preserve pool, retry, added/missing filters and change history; zero browser errors."
        )
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
