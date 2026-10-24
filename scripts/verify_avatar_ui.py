"""Avatar preview/save/remove UI regression; mock APIs only."""
import asyncio
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright, expect


async def main():
    user = dict(id="admin", username="admin", display_name="管理员", role="admin", must_change_password=False, avatar_url=None)
    image = io.BytesIO()
    Image.new("RGB", (256, 256), "#fab736").save(image, "JPEG")
    calls = []
    errors = []

    async def handle(route):
        path = urlsplit(route.request.url).path
        if path.startswith("/api/avatars/"):
            await route.fulfill(content_type="image/jpeg", body=image.getvalue())
            return
        if path == "/api/auth/avatar":
            calls.append(route.request.method)
            user["avatar_url"] = "/api/avatars/admin?v=1" if route.request.method == "PUT" else None
        await route.fulfill(content_type="application/json", body=json.dumps(user))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/account")
        await page.get_by_label("选择头像", exact=True).set_input_files(dict(name="avatar.jpg", mimeType="image/jpeg", buffer=image.getvalue()))
        await expect(page.get_by_role("button", name="保存头像", exact=True)).to_be_visible()
        assert not calls
        await page.get_by_role("button", name="保存头像", exact=True).click()
        await expect(page.get_by_role("button", name="恢复默认头像", exact=True)).to_be_visible()
        assert calls == ["PUT"]
        await expect(page.locator('img[src*="/api/avatars/admin"]')).to_have_count(2)
        Path("data/devchecks").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/avatar-account.png", full_page=True)
        await page.get_by_role("button", name="恢复默认头像", exact=True).click()
        await expect(page.get_by_role("button", name="恢复默认头像", exact=True)).to_have_count(0)
        assert calls == ["PUT", "DELETE"]
        assert not errors, errors
        await browser.close()
    print("Avatar preview/save/header refresh/remove passed; mocked APIs only")


asyncio.run(main())
