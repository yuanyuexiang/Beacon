"""Multi-channel phone preview uses simulated API only; no external apps or sends."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

LEAD = "11111111-1111-4111-8111-111111111111"
TASK = "22222222-2222-4222-8222-222222222222"


async def main():
    errors, calls = [], []
    job = None
    notices = [
        dict(
            id="notice",
            channel="instagram",
            title="Mock Restaurant",
            body="Please share the details.",
            occurred_at="2026-11-06T03:00:00Z",
            status="pending",
            stable_thread=True,
            structured=True,
            read=False,
            lead_id=None,
            lead_name=None,
        )
    ]
    linked = []

    async def handle(route):
        nonlocal job
        path = urlsplit(route.request.url).path
        body = route.request.post_data_json if route.request.post_data else {}
        calls.append((path, body))
        if path == "/api/auth/me":
            data = dict(id="tester", username="tester", role="admin", must_change_password=False)
        elif path == "/api/batches":
            data = []
        elif path == "/api/communication/assignees":
            data = [dict(username="tester", display_name="Tester")]
        elif path == "/api/communication/overview":
            data = dict(
                total=1, items=[dict(id=LEAD, name="Mock Restaurant", postcode="AB1", progress=dict(status="pending"))]
            )
        elif path == f"/api/communication/leads/{LEAD}":
            data = dict(
                lead=dict(id=LEAD, name="Mock Restaurant", postcode="AB1", website=None, address=None),
                contacts=[
                    dict(
                        id="contact",
                        channel="instagram",
                        contact_ref="https://instagram.com/mock_shop",
                        contact_usable="valid",
                        eligibility="allowed",
                        suppressed=False,
                    )
                ],
                contents=[],
                analyses=[],
                drafts=[],
                tasks=[
                    dict(
                        id=TASK,
                        lead_id=LEAD,
                        eligibility_id="contact",
                        content_id="content",
                        channel="instagram",
                        status="pending",
                        execution_mode="mobile",
                        assigned_to="tester",
                        sent_at=None,
                        follow_up_at=None,
                    )
                ],
                progress=dict(status="pending"),
            )
        elif path == f"/api/communication/activity/{LEAD}":
            data = dict(timeline=[], deliveries=[], conversations=[])
        elif path == "/api/mobile/notifications":
            data = linked if "status=linked" in route.request.url else notices
        elif path == "/api/mobile/reply-targets":
            data = [
                dict(
                    id="execution",
                    channel="instagram",
                    lead_name="Mock Restaurant",
                    target="https://instagram.com/mock_shop",
                )
            ]
        elif path == "/api/mobile/notifications/notice/link":
            assert body == dict(execution_id="execution", remember=True)
            n = notices.pop()
            n.update(status="linked", read=True, lead_id=LEAD, lead_name="Mock Restaurant")
            linked.append(n)
            data = n
        elif path == "/api/mobile/notifications/notice/read" or path == "/api/mobile/notification-threads/reset":
            data = dict(ok=True)
        elif path == "/api/mobile/devices":
            data = [
                dict(
                    id="device",
                    label="模拟手机",
                    status="ready",
                    online=True,
                    account="+447700900001",
                    last_seen_at=None,
                    capabilities=dict(protocol=2, accounts=dict(instagram="@our_shop"), installed=["instagram"]),
                )
            ]
        elif path == f"/api/mobile/tasks/{TASK}/preview":
            data = dict(
                preview_hash="mock-hash",
                payload=dict(
                    channel="instagram",
                    action=body["action"],
                    target="https://instagram.com/mock_shop",
                    sender="@our_shop",
                    body="Simulated message only",
                    lead_name="Mock Restaurant",
                ),
            )
        elif path == f"/api/mobile/tasks/{TASK}/confirm":
            assert body["action"] == "message_request"
            job = dict(
                id="job",
                status="queued",
                error=None,
                finished_at=None,
                snapshot=dict(
                    channel="instagram",
                    action="message_request",
                    target="https://instagram.com/mock_shop",
                    sender="@our_shop",
                    body="Simulated message only",
                    lead_name="Mock Restaurant",
                ),
            )
            data = job
        elif path == f"/api/mobile/tasks/{TASK}":
            data = job
        elif path == "/api/outreach-identity":
            data = dict(sender_identity="Tester", opt_out_text="Please let us know.")
        else:
            data = {}
        await route.fulfill(content_type="application/json", body=json.dumps(data))

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport=dict(width=1600, height=1000))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.route("**/api/**", handle)
        await page.goto(f"http://localhost:3001/tasks?lead={LEAD}")
        await page.get_by_role("button", name="查看手机回复", exact=True).click()
        await expect(page.get_by_text("Please share the details.", exact=True)).to_be_visible()
        Path("data/devchecks/mobile").mkdir(parents=True, exist_ok=True)
        await page.screenshot(path="data/devchecks/mobile/notifications-pending-mock.png", full_page=True)
        await page.locator("div.ant-select[aria-label='关联回复门店']").click()
        await page.get_by_title("Mock Restaurant · https://instagram.com/mock_shop", exact=True).click()
        await page.get_by_role("button", name="确认客户回复并回填", exact=True).click()
        await expect(page.get_by_text("暂无待关联手机通知", exact=True)).to_be_visible()
        await page.get_by_role("tab", name="已回填", exact=False).click()
        await expect(page.get_by_role("button", name="查看沟通", exact=True)).to_be_visible()
        out = Path("data/devchecks/mobile")
        out.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out / "notifications-inbox-mock.png"), full_page=True)
        assert not errors, errors
        assert not any(path.endswith("/send") for path, _ in calls)
        await browser.close()
    print("PASS: notification inbox, explicit conversation association, linked reply; no sends")


asyncio.run(main())
