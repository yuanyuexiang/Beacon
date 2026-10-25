"""全 API 模拟：销售摘要、回复理解、独立按钮状态与草稿保存，不调用真实 AI 或发送。"""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
import verify_detail_workspace_ui as fixture


async def main():
    calls = []
    failures = []
    async def handle(route):
        path = urlsplit(route.request.url).path
        calls.append((path, route.request.method))
        if path.endswith('/sales-brief'):
            result = None if route.request.method == 'GET' else dict(summary='示例咖啡馆，尚未核对菜单。', approach='先询问负责人与菜单。', gaps=['当前菜单'], citations=[dict(document_id='store', quote='Sample Cafe')])
            data = dict(result=result, stale=False)
        elif path.endswith('/reply-advice'):
            await asyncio.sleep(0.4)
            data = dict(event_id='reply1', intent='quote', summary='客户询问报价，需确认数量。', suggested_reply='Could you share the required quantity?', citations=[dict(document_id='reply', quote='Please send a quote')])
        elif path.endswith('/reply-confirm'):
            data = dict(intent='quote')
        elif path.endswith('/reply-draft'):
            assert route.request.post_data_json['sender_identity'] == 'Example Company'
            data = dict(id='followup1')
        else:
            return await fixture.handle(route)
        await route.fulfill(content_type='application/json', body=json.dumps(data))
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='chrome', headless=True)
        page = await browser.new_page(viewport=dict(width=1500, height=1050))
        page.on('pageerror', lambda error: failures.append(str(error)))
        await page.route('**/api/**', handle)
        await page.goto(f'http://localhost:3000/leads/{fixture.ID}')
        await page.get_by_role('button', name='生成销售摘要', exact=True).click()
        await expect(page.get_by_text('示例咖啡馆，尚未核对菜单。', exact=True)).to_be_visible()
        await page.get_by_text('理解客户回复与准备跟进', exact=True).click()
        await page.get_by_placeholder('只粘贴本次客户回复，尽量去掉历史引用和签名').fill('Please send a quote')
        await page.get_by_role('button', name='记录回复并由 AI 分析', exact=True).click()
        await expect(page.get_by_role('button', name=re.compile('更新销售摘要'))).to_be_enabled()
        await expect(page.get_by_text('客户询问报价，需确认数量。', exact=True)).to_be_visible()
        await page.get_by_role('button', name='确认意向并回填统计', exact=True).click()
        await page.get_by_label('跟进发送身份', exact=True).fill('Example Company')
        await page.get_by_role('button', name='保存为待确认文案', exact=True).click()
        await expect(page.get_by_text('跟进草稿已保存，请在下方文案区核对并确认', exact=True)).to_be_visible()
        Path('data/devchecks').mkdir(parents=True, exist_ok=True)
        await page.screenshot(path='data/devchecks/sales-assistance.png', full_page=True)
        assert not failures, failures
        assert not any(path.endswith('/send') for path, method in calls)
        assert sum(path.endswith('/sales-brief') and method == 'POST' for path, method in calls) == 1
        await browser.close()
    print('PASS: grounded brief, reply suggestions, independent loading, confirmed metrics, draft only')


asyncio.run(main())
