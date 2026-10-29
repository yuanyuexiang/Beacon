"""用户管理与首次改密 UI 回归；全部 API 模拟，不创建真实账号或发送消息。"""

import asyncio
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

NOW = "2026-10-16T00:00:00Z"
admin = {
    "id": "admin",
    "username": "admin",
    "display_name": None,
    "role": "admin",
    "must_change_password": False,
    "is_active": True,
    "created_at": NOW,
}
me = copy.deepcopy(admin)
users = [copy.deepcopy(admin)]
writes = []
errors = []


async def handle(route):
    global me
    path = urlsplit(route.request.url).path
    method = route.request.method
    body = route.request.post_data_json if route.request.post_data else {}
    status, data = 200, {}
    if method in {"POST", "PUT", "PATCH"}:
        writes.append((method, path))
    if path == "/api/auth/me":
        data = me
    elif path == "/api/auth/profile":
        me = {**me, **body}
        data = me
    elif path == "/api/auth/password":
        me = {**me, "must_change_password": False}
        data = me
    elif path == "/api/users" and method == "GET":
        data = [u for u in users if u["role"] == "member"] if me["role"] == "director" else users
    elif path == "/api/users" and method == "POST":
        data = {**body, "id": "sales", "is_active": True, "must_change_password": True, "created_at": NOW}
        data.pop("initial_password")
        users.append(data)
        status = 201
    elif path.startswith("/api/users/"):
        target = next(u for u in users if u["id"] == path.split("/")[3])
        if (
            method == "PATCH"
            and target["id"] == "admin"
            and (body.get("role", "admin") != "admin" or body.get("is_active") is False)
        ):
            status, data = 409, {"detail": "至少保留一位有效管理员，请先创建或启用其他管理员"}
        else:
            if path.endswith("reset-password"):
                target["must_change_password"] = True
            else:
                target.update(body)
            data = target
    elif path in {"/api/batches", "/api/leads"}:
        data = []
    else:
        status, data = 503, {"detail": "Mock service unavailable"}
    await route.fulfill(status=status, content_type="application/json", body=json.dumps(data))


async def main():
    global me
    Path("data/devchecks").mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1050})
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/users")
        await page.get_by_role("button", name="新增用户", exact=True).click()
        dialog = page.get_by_role("dialog")
        await dialog.get_by_label("登录名", exact=True).fill("sales")
        await dialog.get_by_label("显示名称", exact=True).fill("销售同事")
        await dialog.get_by_label("初始密码", exact=True).fill("test-only-password-123")
        await dialog.get_by_role("button", name="创建用户", exact=True).click()
        await page.get_by_text("用户已创建；请交付初始密码，首次登录需修改", exact=True).wait_for()
        row = page.get_by_role("row").filter(has=page.get_by_text("sales", exact=True))
        await expect(row).to_contain_text("业务成员")
        await row.get_by_role("button", name=re.compile(r"编\s*辑")).click()
        await dialog.get_by_label("显示名称", exact=True).fill("销售同事改名")
        await (
            dialog.locator(".ant-form-item")
            .filter(has=page.get_by_text("角色", exact=True))
            .locator(".ant-select-selector")
            .click()
        )
        await page.get_by_title("只读成员", exact=True).click()
        await dialog.get_by_role("button", name="保存修改", exact=True).click()
        await expect(row).to_contain_text("只读成员")
        await expect(row).to_contain_text("销售同事改名")
        await row.get_by_role("button", name=re.compile(r"停\s*用")).click()
        await page.get_by_role("button", name="确 定", exact=True).click()
        await expect(row).to_contain_text("已停用")
        await row.get_by_role("button", name=re.compile(r"恢\s*复")).click()
        await page.get_by_role("button", name="确 定", exact=True).click()
        await expect(row).to_contain_text("正常")
        await row.get_by_role("button", name="重置密码", exact=True).click()
        await dialog.get_by_label("临时密码", exact=True).fill("test-only-reset-456")
        await dialog.get_by_role("button", name="重置密码并撤销旧会话", exact=True).click()
        await page.get_by_text("密码已重置，旧会话已失效；请交付临时密码", exact=True).wait_for()
        own = page.locator('tr[data-row-key="admin"]')
        await own.get_by_role("button", name=re.compile(r"停\s*用")).click()
        await page.get_by_role("button", name="确 定", exact=True).click()
        await page.get_by_text("至少保留一位有效管理员，请先创建或启用其他管理员", exact=True).wait_for()
        await page.screenshot(path="data/devchecks/users-management.png", full_page=True)
        me = {**admin, "id": "director", "username": "director", "role": "director"}
        await page.goto("http://localhost:3000/users")
        await expect(page.get_by_role("link", name="用户管理", exact=True)).to_be_visible()
        assert await page.get_by_role("link", name="设置", exact=True).count() == 0
        await expect(page.locator('tr[data-row-key="admin"]')).to_have_count(0)
        await page.get_by_role("button", name="新增用户", exact=True).click()
        await expect(dialog.get_by_label("角色", exact=True)).to_be_disabled()
        await dialog.get_by_label("登录名", exact=True).fill("director-sales")
        await dialog.get_by_label("显示名称", exact=True).fill("总监添加的销售")
        await dialog.get_by_label("初始密码", exact=True).fill("test-only-password-123")
        await dialog.get_by_role("button", name="创建用户", exact=True).click()
        await expect(page.get_by_role("row").filter(has=page.get_by_text("director-sales", exact=True))).to_contain_text("业务成员")
        assert users[-1]["role"] == "member"
        await page.screenshot(path="data/devchecks/director-users.png", full_page=True)
        me = {**users[1], "must_change_password": True}
        await page.goto("http://localhost:3000/leads")
        await page.wait_for_url("**/account")
        await page.get_by_label("当前临时密码", exact=True).fill("test-only-reset-456")
        await page.get_by_label("新密码", exact=True).fill("test-only-new-789")
        await page.get_by_label("再次输入新密码", exact=True).fill("test-only-new-789")
        await page.get_by_role("button", name="修改密码", exact=True).click()
        await page.get_by_text("密码已修改，其他登录会话已失效", exact=True).wait_for()
        assert not me["must_change_password"]
        await page.get_by_label("显示名称", exact=True).fill("同事新名称")
        await page.get_by_role("button", name="保存资料", exact=True).click()
        await page.get_by_text("个人资料已保存", exact=True).wait_for()
        await page.screenshot(path="data/devchecks/account-profile.png", full_page=True)
        assert await page.get_by_role("link", name="用户管理", exact=True).count() == 0
        me = {**me, "role": "viewer"}
        await page.goto("http://localhost:3000/leads")
        await expect(page.get_by_role("button", name="建立名单", exact=True)).to_be_disabled()
        await expect(page.get_by_role("button", name="重新预筛", exact=True)).to_be_disabled()
        await page.goto("http://localhost:3000/users")
        await page.get_by_text("此页面仅限管理员使用", exact=True).wait_for()
        assert not errors, errors
        print(
            json.dumps(
                {
                    "user_management": True,
                    "director_member_management": True,
                    "last_admin_protection": True,
                    "forced_password_change": True,
                    "viewer_controls": True,
                    "page_errors": errors,
                    "real_api_calls": 0,
                }
            )
        )
        await browser.close()


asyncio.run(main())
