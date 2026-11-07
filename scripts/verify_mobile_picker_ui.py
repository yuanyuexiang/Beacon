import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
import verify_detail_workspace_ui as f
from playwright.async_api import async_playwright, expect


async def main():
    f.created_draft = True
    f.chosen_contact = "email1"
    f.state = "preparing"
    f.CONTACT.update(channel="facebook", contact_ref="https://www.facebook.com/test")
    original = f.draft
    f.draft = lambda: {**original(), "channel": "facebook", "execution_mode": "mobile"}
    ready = False

    async def handle(route):
        if "/api/mobile/devices" in route.request.url:
            await route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    [
                        {
                            "id": "phone",
                            "label": "Xiaomi 14 Pro",
                            "status": "ready" if ready else "paired",
                            "online": True,
                            "capabilities": {
                                "protocol": 2,
                                "installed": ["facebook"],
                                "accessibility": True,
                            },
                        }
                    ]
                ),
            )
            return
        await f.handle(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1050})
        await page.route("**/api/**", handle)
        await page.goto("http://localhost:3000/leads/" + f.ID)
        await page.get_by_role("button", name="准备触达", exact=True).click()
        await expect(
            page.get_by_role("combobox", name="执行手机", exact=True)
        ).to_be_visible()
        await expect(
            page.get_by_text("Xiaomi 14 Pro · 待就绪", exact=True)
        ).to_be_visible()
        await expect(page.get_by_text("在线，待开启执行", exact=False)).to_be_visible()
        await page.screenshot(path="data/devchecks/mobile-picker-paused.png")
        ready = True
        await expect(
            page.get_by_text("Xiaomi 14 Pro · 已就绪", exact=True)
        ).to_be_visible(timeout=16000)
        await page.screenshot(path="data/devchecks/mobile-picker-ready.png")
        await browser.close()
    print(
        "mobile picker UI passed: paused visible, heartbeat refresh ready; all APIs mocked"
    )


asyncio.run(main())
