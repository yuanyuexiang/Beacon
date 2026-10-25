"""单家销售工作区端到端回归；全部 API 模拟，无真实模型、商户请求或发送。"""

import asyncio
import copy
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect

ID = "11111111-1111-4111-8111-111111111111"
role = "admin"
website = "https://old.example"
assets, analyses, writes, errors, extra_contacts = [], [], [], [], []
piece = None
created_draft = False
chosen_contact = None
selected_content = None
state = "not_started"
fail_menus = False
revision = 0
empty_contacts = False
fail_ai = False
CONTACT = {
    "id": "email1",
    "channel": "email",
    "contact_ref": "hello@cafe.example",
    "contact_source": "官网",
    "contact_usable": "unknown",
    "eligibility": "allowed",
    "suppressed": False,
    "recommendation": {
        "recommendation": "recommended",
        "affiliation": "target",
        "owner": "Audit Cafe",
        "purpose": "general",
        "reason": "门店联系页列出",
        "citations": [],
    },
}


def lead():
    return {
        "id": ID,
        "name": "DOBBIES GARDEN WORLD – RESTAURANT & BAKERY",
        "address": "1 Test Road",
        "postcode": "AB1 1AA",
        "website": website,
        "source_key": "fsa:123",
        "screening_class": "candidate",
        "screening_reason": None,
        "contact_count": 1,
        "communication_progress": {"status": state, "task_id": "task1" if state in {"pending", "replied"} else None},
        "list_summary": {"menu_status": "needs_review" if analyses else "missing", "channels": ["email"]},
    }


def context():
    return {
        "lead": lead(),
        "contacts": [] if empty_contacts else [CONTACT] + extra_contacts,
        "contents": [piece] if piece else [],
        "analyses": [],
        "tasks": [{"id": "task1", "status": "pending", "channel": "email"}] if state in {"pending", "replied"} else [],
        "progress": lead()["communication_progress"],
    }


def draft():
    return {
        "id": "draft1",
        "lead_id": ID,
        "channel": "email",
        "execution_mode": "manual",
        "eligibility_id": chosen_contact,
        "content_id": selected_content,
        "assigned_to": "ui",
        "follow_up_at": None,
        "purpose": "initial",
        "notes": None,
        "status": "converted" if state in {"pending", "replied"} else "draft",
        "task_id": "task1" if state in {"pending", "replied"} else None,
        "blockers": ([] if chosen_contact else ["尚未选择联系方式"])
        + ([] if piece and piece["approved"] else ["尚未准备已审批文案"]),
        "context": context(),
    }


async def handle(route):
    global website, created_draft, chosen_contact, selected_content, piece, state, revision
    request = route.request
    url = urlsplit(request.url)
    path, method = url.path, request.method
    body = request.post_data_json if method in {"POST", "PATCH"} and request.post_data else {}
    if method != "GET":
        writes.append((method, path, body, url.query))
    if path == "/api/auth/me":
        data = {"id": "ui", "username": "ui", "role": role, "must_change_password": False}
    elif path == f"/api/leads/{ID}":
        if method == "PATCH":
            assert body.get("expected_website", website) == website
            website = body.get("website", website)
        data = lead()
    elif path.endswith("/menu-workspace"):
        if fail_menus:
            await route.fulfill(
                status=503, content_type="application/json", body=json.dumps({"detail": "测试：菜单读取暂不可用"})
            )
            return
        data = {"assets": assets, "analyses": {"asset1": analyses} if assets else {}}
    elif path.endswith("/sales-brief"):
        data = {"result": None, "stale": False}
    elif path.endswith("/eligibility"):
        data = [] if empty_contacts else [CONTACT] + extra_contacts
    elif path in {f"/api/leads/{ID}/content", f"/api/leads/{ID}/outreach-message"}:
        if method == "POST":
            if fail_ai:
                await route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "AI 起草暂不可用，已有消息未修改"}))
                return
            assert path.endswith("/outreach-message")
            assert body["channel"] == "email"
            piece = {
                "id": "content1",
                "version": 1,
                "mode": "menu_inquiry",
                "body_text": "Could you share your menu?\n" + body["sender_identity"] + "\n" + body["opt_out_text"],
                "subject": "Menu design collaboration",
                "rationale": "结合门店与真实服务，询问菜单负责人",
                "missing": ["当前菜单"],
                "sources": [{"id": "services", "text": '{"company": "Test Company", "services": "Menu design and printing"}'}],
                "approved": False,
                "reason": "待审批",
                "kind": "message_short",
                "approval_valid": False,
                "html_url": None,
                "png_url": None,
            }
            data = piece
        else:
            data = [piece] if piece else []
    elif path == f"/api/communication/leads/{ID}":
        data = {**context(), "drafts": [draft()] if created_draft and state not in {"pending", "replied"} else []}
    elif path == "/api/communication/assignees":
        data = [{"username": "ui", "display_name": "UI Tester"}]
    elif path == "/api/communication/prepare":
        created_draft, state = True, "preparing"
        data = {"items": [{"lead_id": ID, "name": "DOBBIES GARDEN WORLD – RESTAURANT & BAKERY", "draft": draft()}]}
    elif path == "/api/communication/drafts/draft1":
        chosen_contact = body.get("eligibility_id", chosen_contact)
        selected_content = body.get("content_id", selected_content)
        data = draft()
    elif path == "/api/content/content1/approve":
        piece.update(approved=True, approval_valid=True, reason=None)
        data = piece
    elif path == "/api/communication/activate":
        assert chosen_contact and piece["approved"]
        state = "pending"
        data = {"items": [{"draft_id": "draft1", "task_id": "task1", "reused": False}]}
    elif path.endswith("/website-review"):
        revision += 1
        website = f"https://new{revision}.example"
        data = {**lead(), "website_research": {"status": "verified", "reason": "测试官网已更新", "website": website}}
    elif path.endswith("/auto-research"):
        data = {"configured": False, "run": None}
    elif path.endswith("/maps-menu"):
        data = {"configured": False, "worker_online": False, "run": None}
    elif path.endswith("/google-places"):
        data = {"configured": False, "link": None}
    elif path.endswith("/menu-candidates"):
        data = {
            "website": website,
            "pages": [],
            "notice": "测试菜单候选",
            "candidates": [{"url": website + "/menu.pdf", "kind": "pdf", "label": "Test Menu", "source_url": website}],
        }
    elif path.endswith("/assets"):
        assert method == "POST"
        assets.append(
            {
                "id": "asset1",
                "kind": "pdf",
                "source_url": body["url"],
                "original_filename": "Menu.pdf",
                "fetch_status": "fetched",
                "fetch_error": None,
                "storage_path": None,
            }
        )
        data = assets[-1]
    elif path == "/api/assets/asset1/analyses":
        assert method == "POST"
        if analyses:
            assert parse_qs(url.query).get("force") == ["true"]
        analyses.append(
            {
                "id": f"analysis{len(analyses) + 1}",
                "version": len(analyses) + 1,
                "status": "needs_review",
                "review_state": None,
                "items": [{"name": "Soup", "price_text": "5.00", "evidence": {"page": 1}}],
                "issues": [
                    {
                        "issue_code": "typo",
                        "fact": "A possible typo",
                        "severity": "candidate",
                        "confirmed": None,
                        "note": None,
                        "evidence": {"page": 1, "region": "top"},
                    }
                ],
                "measurements": {},
                "error": None,
            }
        )
        data = analyses[-1]
    elif path.startswith("/api/analyses/"):
        updated = copy.deepcopy(analyses[-1])
        updated.update(id=f"analysis{len(analyses) + 1}", version=len(analyses) + 1)
        updated["issues"][0]["confirmed"] = body["corrections"][0]["new_value"]
        analyses.append(updated)
        data = updated
    elif path.endswith("/contacts"):
        item = body["items"][0]
        extra_contacts.append(
            {
                "id": "phone1",
                "channel": item["channel"],
                "contact_ref": item["contact_ref"],
                "contact_source": item["contact_source"],
                "contact_usable": "unknown",
                "eligibility": "unknown",
                "suppressed": False,
            }
        )
        data = {"created": 1, "skipped": 0}
    elif path.endswith("/auto-admission"):
        assert parse_qs(url.query).get("refresh") == ["false"]
        data = {"summary": {"allowed": 1, "blocked": 0, "unknown": 0, "manual_preserved": 0}, "ai": None}
    else:
        errors.append(path)
        data = {}
    await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


async def main():
    global fail_menus, role, state, empty_contacts, fail_ai
    output = Path("data/devchecks")
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3000/leads/{ID}")
        await expect(page.get_by_text("选择渠道并保存草稿，随后生成文案、确认内容。没有菜单也可以先询问菜单或负责人。", exact=True)).to_be_visible()
        empty_contacts = True
        await page.reload()
        await expect(page.get_by_text("先找到合适的联系人", exact=True)).to_be_visible()
        await expect(page.get_by_role("button", name="查看全部（0）", exact=True)).to_have_count(0)
        await page.screenshot(path=str(output / "detail-workspace-empty.png"), full_page=True, animations="disabled")
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        left = await page.locator("#customer-contacts").bounding_box()
        right = await page.locator("#sales-composer").bounding_box()
        assert left and right and right["x"] > left["x"] + left["width"]
        empty_contacts = False
        await page.reload()
        assert not writes, writes
        await expect(page.get_by_role("tab", name="销售准备", exact=True)).to_be_visible()
        await page.get_by_role("tab", name="来源与历史", exact=True).click()
        await page.get_by_role("button", name="查看核验结果", exact=True).click()
        await page.get_by_role("button", name="AI 核验／重试", exact=True).click()
        await page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
        await expect(page.locator("#website")).to_have_value("https://new1.example")
        await page.locator("#website").fill("https://typed.example")
        await page.get_by_role("button", name="查看核验结果", exact=True).click()
        await page.get_by_role("button", name="AI 核验／重试", exact=True).click()
        await expect(page.get_by_role("dialog").get_by_text("测试官网已更新", exact=True)).to_be_visible()
        await page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
        await expect(page.get_by_text("官网已有更新，当前输入尚未保存", exact=True)).to_be_visible()
        await expect(page.locator("#website")).to_have_value("https://typed.example")
        await page.get_by_role("button", name="采用最新官网", exact=True).click()
        await expect(page.locator("#website")).to_have_value("https://new2.example")
        await page.get_by_role("tab", name="菜单资料", exact=True).click()
        await page.get_by_role("button", name="查找官网菜单", exact=True).click()
        await page.get_by_role("button", name="核对并抓取", exact=True).click()
        await page.get_by_role("button", name="已核对，抓取菜单", exact=True).click()
        await expect(page.get_by_text("核对菜单事实 · pdf · 分析 v1", exact=False)).to_be_visible()
        assert sum(x[1].endswith("/analyses") for x in writes) == 1
        await page.get_by_label("问题 1 核对结果", exact=True).first.click()
        await page.get_by_title("不属实", exact=True).click()
        await expect(page.get_by_text("核对菜单事实 · pdf · 分析 v2", exact=False)).to_be_visible()
        assert analyses[-1]["issues"][0]["confirmed"] is False
        await page.get_by_role("button", name="重新分析", exact=True).click()
        await page.locator(".ant-popconfirm-buttons .ant-btn-primary").click()
        await expect(page.get_by_text("核对菜单事实 · pdf · 分析 v3", exact=False)).to_be_visible()
        await page.screenshot(path=str(output / "detail-workspace-menus.png"), full_page=True, animations="disabled")
        await page.get_by_role("tab", name="销售准备", exact=True).click()
        await page.get_by_role("button", name="手动添加", exact=True).click()
        manual = page.get_by_role("dialog", name="手动添加联系方式", exact=True)
        await manual.locator(".ant-select-selector").first.click()
        await page.get_by_title("电话", exact=True).click()
        await manual.get_by_label("联系方式", exact=True).fill("+441234567890")
        await manual.get_by_label("来源", exact=True).fill("客户提供的名片")
        await manual.get_by_role("button", name="保存联系方式", exact=True).click()
        await expect(manual).not_to_be_visible()
        await expect(page.get_by_role("link", name="+441234567890", exact=True)).to_be_visible()
        await page.get_by_role("button", name="用于本次触达", exact=True).first.click()
        await expect(page.get_by_text("尚不能创建可执行任务，草稿已保存", exact=True)).to_be_visible()
        assert chosen_contact == "email1"
        before_reload = len(writes)
        await page.reload()
        await expect(page.get_by_text("尚不能创建可执行任务，草稿已保存", exact=True)).to_be_visible()
        assert len(writes) == before_reload, "读取已有草稿不得自动写入"

        await page.get_by_text("发件身份与退出说明", exact=True).click()
        await page.get_by_label("发件身份", exact=True).fill("Test Company")
        await page.get_by_text("发件身份与退出说明", exact=True).click()
        await page.get_by_role("button", name="AI 起草触达消息", exact=True).click()
        await expect(page.get_by_label("文案内容", exact=True)).to_have_value(re.compile("Could you share your menu"))
        await expect(page.get_by_label("邮件主题", exact=True)).to_have_value("Menu design collaboration")
        await page.get_by_text("为什么这样写 · 生成依据", exact=True).click()
        await expect(page.get_by_text("结合门店与真实服务，询问菜单负责人", exact=True)).to_be_visible()
        fail_ai = True
        await page.get_by_role("button", name="AI 重新起草消息", exact=True).click()
        await expect(page.get_by_text("AI 起草暂不可用，已有消息未修改", exact=True)).to_be_visible()
        await expect(page.get_by_label("文案内容", exact=True)).to_have_value(re.compile("Could you share your menu"))
        fail_ai = False
        await page.get_by_text("为什么这样写 · 生成依据", exact=True).click()
        await page.get_by_role("checkbox", name="我已核对引用事实、身份和退出说明", exact=True).check()
        await page.get_by_role("button", name="确认消息内容", exact=True).click()
        await expect(page.get_by_role("button", name="创建就绪任务（1）", exact=True)).to_be_enabled()
        await page.evaluate("window.scrollTo(0, 0)")
        await page.screenshot(path=str(output / "detail-workspace-sales.png"), full_page=True, animations="disabled")
        await page.get_by_role("button", name="创建就绪任务（1）", exact=True).click()
        await expect(page.get_by_role("link", name="进入本次触达工作台 →", exact=True)).to_be_visible()
        assert not any("send" in x[1] for x in writes)
        state = "replied"
        await page.reload()
        await expect(page.get_by_role("button", name="处理客户回复", exact=True)).to_be_visible()
        await page.screenshot(path=str(output / "detail-workspace-task.png"), full_page=True, animations="disabled")
        fail_menus = True
        await page.reload()
        await expect(page.get_by_text("部分资料未能加载，已读取的结果仍可使用", exact=True)).to_be_visible()
        await expect(
            page.locator("#customer-contacts").get_by_role("link", name=CONTACT["contact_ref"], exact=True)
        ).to_be_visible()
        fail_menus, role = False, "viewer"
        before = len(writes)
        await page.reload()
        await expect(page.get_by_role("button", name="处理客户回复", exact=True)).to_be_enabled()
        await expect(page.get_by_role("button", name="用于本次触达", exact=True).first).to_be_disabled()
        await page.get_by_role("tab", name="菜单资料", exact=True).click()
        await expect(page.get_by_label("当前菜单", exact=True).first).to_be_enabled()
        assert len(writes) == before
        role, state = "admin", "suppressed"
        await page.reload()
        await expect(page.get_by_text("该客户已停止触达", exact=True)).to_be_visible()
        await expect(page.get_by_role("button", name="保存并检查草稿", exact=True)).to_have_count(0)
        assert len(writes) == before
        assert not errors, errors
        await browser.close()
        print(
            "Detail workspace passed: read-only view, website conflict, menu import/versions, "
            "inline contact/draft/inquiry/approval/task, reply, partial failure and viewer"
        )


if __name__ == "__main__":
    asyncio.run(main())
