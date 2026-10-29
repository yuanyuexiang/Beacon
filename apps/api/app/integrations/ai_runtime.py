"""One runtime for all business AI calls; explicit routing, no provider failover."""

import base64
import copy
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps

import httpx
from pydantic import BaseModel

from app.core.db import get_sessionmaker
from app.integrations.llm import ProviderUnavailable
from app.modules.ai import configuration as config
from app.modules.ai.models import AIConfiguration

_revision: ContextVar[str | None] = ContextVar("ai_revision", default=None)


def revision(db) -> str:
    if _revision.get():
        return _revision.get() or "environment"
    row = config.latest(db)
    return str(row.id) if row else "environment"


@contextmanager
def scope(value: str | None):
    token = _revision.set(value)
    try:
        yield
    finally:
        _revision.reset(token)


def call_scope(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with get_sessionmaker()() as db:
            frozen = revision(db)
        with scope(frozen):
            return fn(*args, **kwargs)

    return wrapped


def workflow_scope(fn):
    @wraps(fn)
    def wrapped(db, batch, task, *args, **kwargs):
        if not task.params.get("ai_revision"):
            task.params = {**task.params, "ai_revision": revision(db)}
            db.commit()
        with scope(task.params["ai_revision"]):
            return fn(db, batch, task, *args, **kwargs)

    return wrapped


def selected(purpose: str = "research") -> dict | None:
    with get_sessionmaker()() as db:
        frozen = _revision.get()
        row = db.get(AIConfiguration, uuid.UUID(frozen)) if frozen and frozen != "environment" else None
        if not frozen:
            row = config.latest(db)
        if frozen and frozen != "environment" and row is None:
            raise ProviderUnavailable("任务使用的 AI 配置版本不存在，请恢复配置记录")
        if row is None:
            return config.environment()
        routes = row.data["routes"]
        key = routes.get(purpose) or routes.get("default")
        value = next((c for c in row.data["connections"] if c["id"] == key), None)
        if not value:
            return None
        # Latest disable/removal is an immediate stop, even for an older task snapshot.
        current = config.latest(db)
        if current:
            live = next((c for c in current.data["connections"] if c["id"] == key), None)
            if not live or not live["enabled"]:
                raise ProviderUnavailable("任务使用的 AI 连接已停用，请调整配置后新建任务")
        value = copy.deepcopy(value)
        value["configuration_version"] = str(row.id)
    value["key"] = config.decrypt(value.pop("encrypted_key"))
    return value


def managed() -> bool:
    with get_sessionmaker()() as db:
        return config.latest(db) is not None


def safe_usage(raw: dict) -> dict:
    result = {
        k: raw[k]
        for k in (
            "input_tokens",
            "output_tokens",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
        if type(raw.get(k)) is int and raw[k] >= 0
    }
    return result


def available(purpose: str = "research") -> bool:
    try:
        value = selected(purpose)
        return bool(value and value.get("key") and (purpose != "vision" or value.get("vision")))
    except (ProviderUnavailable, ValueError):
        return False


def metadata(client) -> dict:
    return {"provider": client.name, "connection_id": client.connection_id, "configuration_version": client.version}


def strict_schema(schema: dict) -> dict:
    result = copy.deepcopy(schema)

    def visit(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(result)
    return result


def check_endpoint(url: str) -> None:
    """Known HTTPS suppliers may resolve through Clash's synthetic address range."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    from app.integrations.fetcher import FetchBlocked, check_url

    config.validate_url(url)
    host = urlsplit(url).hostname
    known = {urlsplit(p["base_url"]).hostname for p in config.PRESETS if p["base_url"]}
    if host not in known:
        check_url(url)
        return
    try:
        addresses = {ipaddress.ip_address(str(a[4][0]).split("%")[0]) for a in socket.getaddrinfo(host, 443)}
    except socket.gaierror:
        raise ProviderUnavailable("AI 接口域名解析失败，请检查服务所在环境的 DNS 与网络") from None
    fake_range = ipaddress.ip_network("198.18.0.0/15")
    if not addresses or any(
        (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast)
        and not (ip.version == 4 and ip in fake_range)
        for ip in addresses
    ):
        raise FetchBlocked("供应商域名解析到了非公网地址")


@dataclass
class Completion:
    text: str
    usage: dict


class Client:
    def __init__(self, value: dict, transport=None):
        self.value = value
        self.name, self.model = value["provider"], value["model"]
        self.connection_id = value.get("id", "environment")
        self.version = value.get("configuration_version", "environment")
        self._transport = transport

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = self.value["base_url"].rstrip("/") + "/" + path.lstrip("/")
        if self._transport is None:
            from app.integrations.fetcher import FetchBlocked

            try:
                check_endpoint(url)
            except FetchBlocked as exc:
                reason = (
                    "域名解析失败" if "无法解析" in str(exc) else "地址校验未通过（解析到非公网地址或端口不受支持）"
                )
                raise ProviderUnavailable(f"AI 接口{reason}，请检查接口地址及服务所在环境的 DNS／网络") from None
            except ValueError:
                raise ProviderUnavailable("AI 接口地址需为公网 HTTPS Base URL") from None
        headers = {"Authorization": "Bearer " + self.value["key"]}
        if self.value["protocol"] == "anthropic":
            headers = {"x-api-key": self.value["key"], "anthropic-version": "2023-06-01"}
        try:
            with (
                httpx.Client(
                    timeout=self.value.get("timeout", 90),
                    transport=self._transport,
                    follow_redirects=False,
                    trust_env=True,
                ) as http,
                http.stream(method, url, headers=headers, json=body) as response,
            ):
                if not response.is_success:
                    code = response.status_code
                    reason = {
                        401: "密钥无效",
                        403: "权限或地区受限",
                        404: "模型或接口地址不存在",
                        429: "供应商限流或额度不足",
                    }.get(code, "供应商请求失败")
                    raise ProviderUnavailable(
                        f"AI {reason}（HTTP {code}）；连接 {self.connection_id}，模型 {self.model}"
                    )
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ProviderUnavailable("AI 响应超过大小上限，请减少单次输入")
            return json.loads(raw)
        except httpx.TimeoutException:
            raise ProviderUnavailable("AI 请求超时，请检查网络或调整超时时间；可重试此项") from None
        except httpx.HTTPError:
            raise ProviderUnavailable("AI 网络连接失败，请检查服务到供应商的网络") from None
        except (ValueError, TypeError):
            raise ProviderUnavailable("AI 接口未返回有效 JSON，请核对 Base URL 和接口协议") from None

    def complete(self, messages: list[dict], schema: type[BaseModel], max_tokens: int = 2500) -> Completion:
        protocol = self.value["protocol"]
        has_image = any(
            isinstance(m.get("content"), list) and any(c.get("type") == "image_url" for c in m["content"])
            for m in messages
        )
        if has_image and not self.value.get("vision"):
            raise ProviderUnavailable("当前连接未配置图片输入能力，请在 AI 模型设置中指定菜单识别模型")
        if protocol == "anthropic":
            system = "\n".join(m["content"] for m in messages if m["role"] == "system")
            converted = []
            for m in messages:
                if m["role"] == "system":
                    continue
                content = m["content"]
                if isinstance(content, list):
                    blocks = []
                    for block in content:
                        if block["type"] == "image_url":
                            media, encoded = block["image_url"]["url"].split(";base64,", 1)
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media.removeprefix("data:"),
                                        "data": encoded,
                                    },
                                }
                            )
                        else:
                            blocks.append(block)
                    content = blocks
                converted.append({"role": m["role"], "content": content})
            data = self.request(
                "POST",
                "messages",
                {
                    "model": self.model,
                    "system": system,
                    "messages": converted,
                    "max_tokens": max_tokens,
                    "tools": [
                        {
                            "name": "structured_result",
                            "description": "Return the requested structured result",
                            "input_schema": schema.model_json_schema(),
                        }
                    ],
                    "tool_choice": {"type": "tool", "name": "structured_result"},
                },
            )
            if data.get("stop_reason") not in {"tool_use", "end_turn"}:
                raise ProviderUnavailable("AI 输出被截断或未完成，请调整输出长度后重试")
            block = next(
                (
                    b
                    for b in data.get("content", [])
                    if b.get("type") == "tool_use" and b.get("name") == "structured_result"
                ),
                None,
            )
            if not block:
                raise ProviderUnavailable("AI 未返回结构化结果，请检查模型能力")
            return Completion(json.dumps(block["input"]), safe_usage(data.get("usage") or {}))
        if protocol == "responses":
            inputs = []
            for m in messages:
                content = m["content"]
                if isinstance(content, str):
                    content = [{"type": "input_text", "text": content}]
                else:
                    content = [
                        {"type": "input_image", "image_url": b["image_url"]["url"]}
                        if b["type"] == "image_url"
                        else {"type": "input_text", "text": b["text"]}
                        for b in content
                    ]
                inputs.append({"role": m["role"], "content": content})
            body = {"model": self.model, "input": inputs, "max_output_tokens": max_tokens, "store": False}
            if self.value.get("json_mode", True):
                body["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "structured_result",
                        "strict": True,
                        "schema": strict_schema(schema.model_json_schema()),
                    }
                }
            data = self.request("POST", "responses", body)
            if data.get("status") != "completed":
                raise ProviderUnavailable("AI 输出未完成或被截断，请检查模型及输出长度")
            texts = [
                b["text"]
                for m in data.get("output", [])
                for b in m.get("content", [])
                if b.get("type") == "output_text"
            ]
            if not texts:
                raise ProviderUnavailable("AI 未返回文本结果，可能拒绝了本次输入")
            return Completion("".join(texts), safe_usage(data.get("usage") or {}))
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens}
        if self.value.get("json_mode", True):
            body["response_format"] = {"type": "json_object"}
        if self.name == "deepseek":
            body["thinking"] = {"type": "disabled"}
        data = self.request("POST", "chat/completions", body)
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") != "stop":
            raise ProviderUnavailable("AI 输出未完成或被截断，请检查模型及输出长度")
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str) or not content:
            raise ProviderUnavailable("AI 未返回有效文本结果，请检查模型能力")
        return Completion(content, safe_usage(data.get("usage") or {}))


def client(purpose: str = "research", transport=None) -> Client:
    value = selected(purpose)
    if not value:
        raise ProviderUnavailable("尚未配置真实 AI，请到设置 → AI 模型添加连接并选择默认模型")
    return Client(value, transport)


class MenuProvider:
    def __init__(self):
        self.client = client("vision")
        self.name, self.model = self.client.name, self.client.model

    def _call(self, content, kind):
        from app.integrations.ai_observation import observe
        from app.integrations.llm import JSON_INSTRUCTIONS, SYSTEM, MenuTranscription, _to_result

        with observe("menu_" + kind, self.model, "menu-ai-2") as record:
            record.update(metadata(self.client))
            result = self.client.complete(
                [
                    {"role": "system", "content": SYSTEM + "\n" + JSON_INSTRUCTIONS},
                    {"role": "user", "content": content},
                ],
                MenuTranscription,
                16000,
            )
            record["usage"] = result.usage
            parsed = MenuTranscription.model_validate_json(result.text)
            output = _to_result(parsed, self.model, result.usage, kind)
            output.engine = self.name
            return output

    def analyze_text(self, text, meta):
        return self._call([{"type": "text", "text": "Transcribe this menu into JSON:\n" + text[:60000]}], "text")

    def analyze_image(self, image: bytes, meta: dict):
        from app.integrations.llm import _pdf_pages_png, _sniff_media

        media = meta.get("media_type") or _sniff_media(image)
        images = [("image/png", b) for b in _pdf_pages_png(image)] if media == "application/pdf" else [(media, image)]
        if not images:
            raise ProviderUnavailable("PDF 无法渲染为图片")
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{m};base64,{base64.b64encode(b).decode()}"}}
            for m, b in images
        ]
        content.append({"type": "text", "text": "Transcribe menu and visible layout facts into JSON."})
        return self._call(content, "image")
