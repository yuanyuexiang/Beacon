"""Exa MCP 单次网页搜索。只请求搜索工具，不执行返回内容或读取候选 URL。"""

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.integrations.fetcher import FetchBlocked, check_url

ENDPOINT = "https://mcp.exa.ai/mcp"
MAX_BYTES = 512 * 1024


class SearchError(ValueError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _result(body: str) -> dict[str, Any]:
    try:
        if body.lstrip().startswith("{"):
            message = json.loads(body)
        else:
            message = None
            # SSE 事件可以有多行 data；忽略 keepalive 等没有 result/error 的事件。
            for event in body.replace("\r\n", "\n").split("\n\n"):
                data = "\n".join(line[5:].lstrip() for line in event.splitlines() if line.startswith("data:"))
                if data:
                    obj = json.loads(data)
                    if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                        message = obj
                        break
        if not isinstance(message, dict) or "error" in message or not isinstance(message.get("result"), dict):
            raise ValueError
        return message["result"]
    except (ValueError, TypeError) as e:
        raise SearchError("搜索服务返回格式异常，请稍后重试") from e


def parse_candidates(result: dict[str, Any]) -> list[dict[str, str]]:
    content = result.get("content")
    if not isinstance(content, list) or any(
        not isinstance(c, dict) or c.get("type") == "text" and not isinstance(c.get("text"), str) for c in content
    ):
        raise SearchError("搜索服务返回格式异常，请稍后重试")
    text = "\n\n".join(c.get("text", "") for c in content if c.get("type") == "text")
    meta = result.get("_meta")
    if isinstance(meta, dict) and meta.get("ai.exa/rateLimited") or "free MCP rate limit" in text:
        raise SearchError("Exa 免费搜索额度已用尽，请稍后重试或配置 BEACON_EXA_API_KEY", 429)
    if result.get("isError"):
        raise SearchError("搜索服务未能完成检索，请稍后重试")
    if not text.strip() or "no results" in text.lower() and not re.search(r"(?m)^URL:", text):
        return []
    blocks = re.split(r"(?m)^Title:\s*", text)[1:]
    if not blocks:
        raise SearchError("搜索结果格式已变化，不能解析为官网候选")
    found: dict[str, dict[str, str]] = {}
    for block in blocks:
        match = re.search(r"(?m)^URL:\s*(\S+)", block)
        if not match:
            continue
        url = match.group(1)
        try:
            check_url(url, resolve=False)
        except (FetchBlocked, ValueError):
            continue
        parsed = urlparse(url)
        if len(url) > 512 or parsed.username or parsed.password:
            continue
        # 摘录只是搜索索引内容，不表示实时抓取成功，也不是确认的菜单证据。
        excerpt = re.split(r"(?m)^(?:Highlights|Text|Content):\s*", block, maxsplit=1)
        found.setdefault(
            url,
            {
                "title": block.splitlines()[0].strip()[:256],
                "url": url,
                "excerpt": (excerpt[1] if len(excerpt) == 2 else "").strip().removesuffix("---").strip()[:1500],
            },
        )
    return list(found.values())[:5]


def search(
    query: str, api_key: str | None = None, *, transport: httpx.BaseTransport | None = None
) -> list[dict[str, str]]:
    headers = {"accept": "application/json, text/event-stream", "user-agent": "BeaconResearch/0.1"}
    if api_key:
        headers["x-api-key"] = api_key
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "web_search_exa", "arguments": {"query": query, "numResults": 5}},
    }
    try:
        with (
            httpx.Client(timeout=30, transport=transport, follow_redirects=False) as client,
            client.stream("POST", ENDPOINT, headers=headers, json=payload) as response,
        ):
            if response.status_code == 429:
                raise SearchError("Exa 搜索限流，请稍后重试或配置 BEACON_EXA_API_KEY", 429)
            if response.status_code in (401, 403):
                raise SearchError("搜索服务拒绝访问，请检查网络或 BEACON_EXA_API_KEY", 503)
            if response.status_code != 200:
                raise SearchError("搜索服务暂不可用，请稍后重试")
            buf = bytearray()
            for chunk in response.iter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise SearchError("搜索响应超过大小上限")
        return parse_candidates(_result(buf.decode("utf-8")))
    except httpx.TimeoutException as e:
        raise SearchError("搜索超时，请稍后重试", 504) from e
    except (httpx.HTTPError, UnicodeError) as e:
        raise SearchError("搜索服务连接失败，请稍后重试") from e
