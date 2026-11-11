"""AI execution feedback and alternate-contact UI use simulated APIs only."""

import asyncio
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright, expect

LEAD = "11111111-1111-4111-8111-111111111111"
TASK = "22222222-2222-4222-8222-222222222222"


async def main():
    errors, calls = [], []
    job = None

    async def handle(route):
        nonlocal job
        path = urlsplit(route.request.url).path
        body = route.request.post_data_json if route.request.post_data else {}
        calls.append((path, body))
        if path.endswith("/screenshot"):
            picture = io.BytesIO()
            Image.new("RGB", (200, 400), "white").save(picture, "JPEG")
            await route.fulfill(content_type="image/jpeg", body=picture.getvalue())
            return
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
        elif path == f"/api/communication/conversations/{LEAD}":
            data = {
                "items": [
                    dict(
                        id="contact",
                        channel="instagram",
                        contact_ref="https://instagram.com/mock_shop",
                        unread=0,
                        messages=[
                            dict(
                                id="message",
                                direction="outbound",
                                at="2026-11-11T08:00:00Z",
                                body="Simulated message only",
                                status="pending",
                                source="mobile",
                                deliveries=[],
                                task_id=TASK,
                            )
                        ],
                    )
                ]
            }
        elif path == f"/api/communication/activity/{LEAD}":
            data = dict(timeline=[], deliveries=[], conversations=[])
        elif path == "/api/mobile/notifications":
            data = []
        elif path == "/api/mobile/devices":
            data = [
                dict(
                    id="device",
                    label="模拟手机",
                    status="ready",
                    online=True,
                    account="+447700900001",
                    last_seen_at=None,
                    capabilities=dict(protocol=3, accounts=dict(instagram="@our_shop"), installed=["instagram"]),
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
        elif path == f"/api/mobile/tasks/{TASK}/alternate":
            assert body == {"contact_ref": "+447700900123"}
            data = dict(lead_id=LEAD, contact_id="alternate-contact", channel="whatsapp")
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
        await page.get_by_text("执行详情／截图", exact=True).click()
        await page.get_by_role("button", name="手机执行／查看结果", exact=True).click()
        await expect(page.get_by_text("Instagram 手机执行", exact=True)).to_be_visible()
        await page.locator("div.ant-select[aria-label='手机联系动作']").click()
        await page.get_by_title("提交消息请求", exact=True).click()
        await page.get_by_role("button", name="预览消息", exact=True).click()
        await expect(page.get_by_role("dialog").get_by_text("Simulated message only", exact=True)).to_be_visible()
        await page.get_by_role("button", name="确认交给手机执行", exact=True).click()
        await expect(page.get_by_text("等待手机领取", exact=True)).to_be_visible()
        # A completed navigation failure keeps the message and its diagnostic steps.
        job.update(
            status="needs_action",
            error="未找到私信入口",
            reason_code="entry_not_found",
            finished_at="2026-11-09T08:00:00Z",
            screenshot_url=f"/api/mobile/tasks/{TASK}/screenshot",
            navigation_history=["open_more:更多:页面无明显变化"],
        )
        await page.reload()
        await page.get_by_text("执行详情／截图", exact=True).click()
        await page.get_by_role("button", name="手机执行／查看结果", exact=True).click()
        await expect(page.get_by_text("未找到私信入口", exact=True)).to_be_visible()
        await page.get_by_text("查看执行步骤", exact=True).click()
        await expect(page.get_by_text("open_more:更多:页面无明显变化", exact=True)).to_be_visible()
        await expect(page.get_by_role("dialog").get_by_text("Simulated message only", exact=True)).to_be_visible()
        await page.get_by_text("查看执行截图", exact=True).click()
        await expect(page.get_by_alt_text("手机执行结果截图")).to_be_visible()
        job.update(
            engine="ai-agent-v1",
            alternate_contact=dict(
                channel="whatsapp", label="WhatsApp", source="https://instagram.com/mock_shop", target="+447700900123"
            ),
            agent_history=[dict(step=1, action="alternate", detail="发现 WhatsApp 联系入口", model="mock-model")],
        )
        await page.reload()
        await page.get_by_text("执行详情／截图", exact=True).click()
        await page.get_by_role("button", name="手机执行／查看结果", exact=True).click()
        await page.get_by_text("AI 执行过程 · 1 步", exact=True).click()
        await expect(page.get_by_text("发现 WhatsApp 联系入口", exact=False)).to_be_visible()
        await page.get_by_role("button", name="转用此渠道", exact=True).click()
        await expect(page.get_by_role("textbox", name="其他渠道联系方式")).to_have_value("+447700900123")
        await expect(page.get_by_role("button", name="保存并准备消息", exact=True)).to_be_visible()
        out = Path("data/devchecks/mobile")
        out.mkdir(parents=True, exist_ok=True)
        await page.wait_for_timeout(300)  # Wait for the modal transition before visual QA.
        await page.screenshot(path=str(out / "ai-alternate-mock.png"), full_page=True)
        await page.route(
            f"http://localhost:3001/leads/{LEAD}?**",
            lambda route: route.fulfill(
                content_type="text/html", body="<html><body>Preparing alternate contact</body></html>"
            ),
        )
        await page.get_by_role("button", name="保存并准备消息", exact=True).click()
        await expect(page).to_have_url(f"http://localhost:3001/leads/{LEAD}?contact=alternate-contact&section=contacts")
        assert any(path.endswith("/alternate") and body == {"contact_ref": "+447700900123"} for path, body in calls)
        assert not errors, errors
        assert not any(path.endswith("/send") for path, _ in calls)
        await browser.close()
    print("PASS: AI trace, screenshot and alternate-contact form; simulated APIs only, no sends")


asyncio.run(main())
