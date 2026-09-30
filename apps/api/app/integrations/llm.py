"""可替换的模型接口。业务只依赖 MenuProvider 协议；FakeProvider 返回预置结果供测试；
AnthropicProvider 用结构化输出转录菜单（文本或图片），结果一律进入人工核对（needs_review）。
模型不得修改审批、准入或销售状态；不推断过敏原/成分/利润；每条观察都必须带位置。"""

import base64
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.core.config import get_settings


@dataclass
class ProviderResult:
    engine: str
    engine_version: str
    items: list[dict] = field(default_factory=list)  # 与规则引擎相同结构
    issues: list[dict] = field(default_factory=list)
    notes: str | None = None
    usage: dict | None = None


class MenuProvider(Protocol):
    name: str

    def analyze_text(self, text: str, meta: dict) -> ProviderResult: ...

    def analyze_image(self, image: bytes, meta: dict) -> ProviderResult: ...


class FakeProvider:
    """测试/无密钥环境：不产生任何事实，只返回空结果并注明未做模型分析。"""

    name = "fake"

    def __init__(self, canned: ProviderResult | None = None) -> None:
        self._canned = canned

    def analyze_text(self, text: str, meta: dict) -> ProviderResult:
        return self._canned or ProviderResult(engine="fake", engine_version="0", notes="FakeProvider：未调用真实模型")

    def analyze_image(self, image: bytes, meta: dict) -> ProviderResult:
        return self._canned or ProviderResult(engine="fake", engine_version="0", notes="FakeProvider：图片未做视觉分析")


class ProviderUnavailable(RuntimeError):
    pass


# ---------- Anthropic ----------


class _Item(BaseModel):
    name: str = Field(description="Dish name exactly as printed")
    price_text: str = Field(description="Price exactly as printed, e.g. '£12.50' or '12'; empty if no price shown")
    section: str | None = Field(default=None, description="Menu section heading if any")
    region: str = Field(description="Where on the page/image this appears, e.g. 'left column, Starters, 3rd line'")


class _Observation(BaseModel):
    issue_code: str = Field(
        description="One of: text_overlap, missing_spaces, low_resolution, price_format_mixed_decimals, "
        "price_format_mixed_symbol, small_text, inconsistent_capitalisation, typo, other"
    )
    fact: str = Field(description="A verifiable statement about what is visible, in English, no opinions")
    region: str = Field(description="Where it is visible")
    severity: str = Field(default="candidate", description="info | candidate | blocking")


class MenuTranscription(BaseModel):
    is_menu: bool = Field(description="False if the content is not a menu (photo, wine shop, age gate, etc.)")
    language: str | None = None
    items: list[_Item]
    observations: list[_Observation]
    notes: str | None = Field(default=None, description="Anything the reviewer should know, e.g. unreadable areas")


SYSTEM = (
    "You transcribe restaurant menus for a design review. Copy dish names and prices exactly as printed; do not "
    "normalise, translate or complete them. Record only what is visible. Never infer allergens, dietary suitability, "
    "ingredients that are not printed, profitability, or the restaurant's intent. Observations must be facts a "
    "reviewer can check at the stated region (overlapping text, missing spaces, low resolution, inconsistent price "
    "formatting, very small text, typos). If the content is not a menu, set is_menu=false and return no items."
)


def _decimals(num: str) -> int:
    return len(num.split(".")[1]) if "." in num else 0


def _to_result(t: MenuTranscription, engine_version: str, usage: dict | None, kind: str) -> ProviderResult:
    import re

    items: list[dict] = []
    for i, it in enumerate(t.items):
        m = re.search(r"(£|€|\$)?\s?(\d{1,3}(?:[.,]\d{1,2})?)", it.price_text or "")
        num = m.group(2).replace(",", ".") if m else None
        items.append(
            {
                "name": it.name.strip(),
                "price_text": it.price_text.strip(),
                "price": float(num) if num else None,
                "currency_symbol": m.group(1) if m else None,
                "decimals": _decimals(num) if num else None,
                "section": it.section,
                "evidence": {"source": kind, "region": it.region, "index": i, "transcribed_by": "model"},
            }
        )
    issues = [
        {
            "issue_code": o.issue_code,
            "fact": o.fact,
            "fact_zh": None,
            "evidence": {"source": kind, "region": o.region, "observed_by": "model"},
            "severity": o.severity,
            "confirmed": None,
            "confirmed_by": None,
            "confirmed_at": None,
            "note": None,
        }
        for o in t.observations
    ]
    note = t.notes or ""
    if not t.is_menu:
        note = ("模型判断内容不是菜单。" + note).strip()
    return ProviderResult(
        engine="anthropic", engine_version=engine_version, items=items, issues=issues, notes=note or None, usage=usage
    )


class AnthropicProvider:
    """Anthropic Messages API + 结构化输出。未经真实调用验证前，结果只作人工核对输入。"""

    name = "anthropic"

    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        s = get_settings()
        self.model = model or s.llm_model or "claude-opus-5-5"
        if client is None:
            if not (
                os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or s.anthropic_api_key
            ):
                raise ProviderUnavailable("未配置 ANTHROPIC_API_KEY（或 BEACON_ANTHROPIC_API_KEY）")
            import anthropic

            client = anthropic.Anthropic(api_key=s.anthropic_api_key) if s.anthropic_api_key else anthropic.Anthropic()
        self._client = client

    def _call(self, content: list[Any], kind: str) -> ProviderResult:
        import anthropic

        output_config: Any = {"effort": get_settings().llm_effort}

        try:
            resp = self._client.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": content}],
                output_format=MenuTranscription,
                output_config=output_config,
            )
        except anthropic.AuthenticationError as e:
            raise ProviderUnavailable(f"Anthropic 认证失败：{e}") from e
        except anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic 限流：{e}") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Anthropic API 错误 {e.status_code}：{e.message}") from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic 网络错误：{e}") from e
        usage = None
        if getattr(resp, "usage", None) is not None:
            usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        if getattr(resp, "stop_reason", None) == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            return ProviderResult(
                engine="anthropic", engine_version=self.model, notes=f"模型拒绝处理（{cat}）", usage=usage
            )
        parsed = getattr(resp, "parsed_output", None)
        if parsed is None:
            return ProviderResult(
                engine="anthropic", engine_version=self.model, notes="模型未返回结构化结果", usage=usage
            )
        return _to_result(parsed, self.model, usage, kind)

    def analyze_text(self, text: str, meta: dict) -> ProviderResult:
        return self._call([{"type": "text", "text": "Transcribe this menu text:\n\n" + text[:60000]}], "text")

    def analyze_image(self, image: bytes, meta: dict) -> ProviderResult:
        media = meta.get("media_type") or _sniff_media(image)
        if media == "application/pdf":
            block: dict = {
                "type": "document",
                "source": {"type": "base64", "media_type": media, "data": base64.standard_b64encode(image).decode()},
            }
        else:
            block = {
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": base64.standard_b64encode(image).decode()},
            }
        return self._call(
            [block, {"type": "text", "text": "Transcribe this menu and list visible layout/typography observations."}],
            "image",
        )


def _sniff_media(b: bytes) -> str:
    if b.startswith(b"%PDF"):
        return "application/pdf"
    if b.startswith(b"\x89PNG"):
        return "image/png"
    if b.startswith(b"GIF8"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


# ---------- DeepSeek（OpenAI 兼容接口） ----------

JSON_INSTRUCTIONS = (
    "Respond with a single json object exactly in this shape (no markdown):\n"
    '{"is_menu": true, "language": "en", '
    '"items": [{"name": "Dish name as printed", "price_text": "£12.50", "section": "Starters", '
    '"region": "left column, 3rd line"}], '
    '"observations": [{"issue_code": "text_overlap", "fact": "What is visible", "region": "where", '
    '"severity": "candidate"}], '
    '"notes": null}\n'
    "issue_code must be one of: text_overlap, missing_spaces, low_resolution, price_format_mixed_decimals, "
    "price_format_mixed_symbol, small_text, inconsistent_capitalisation, typo, other. "
    "Include every dish with its printed price; leave price_text empty if none is printed."
)


class DeepSeekProvider:
    """DeepSeek chat completions（OpenAI 兼容），JSON 模式。deepseek-flash 支持图片；图片 PDF 先转页图。"""

    name = "deepseek"

    def __init__(self, model: str | None = None, transport: Any | None = None) -> None:
        s = get_settings()
        self.model = model or s.llm_model or "deepseek-flash"
        self.base_url = s.deepseek_base_url.rstrip("/")
        self.key = s.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.thinking = s.llm_thinking
        self._transport = transport
        if not self.key:
            raise ProviderUnavailable("未配置 DEEPSEEK_API_KEY（或 BEACON_DEEPSEEK_API_KEY）")

    def _call(self, content: list[Any], kind: str) -> ProviderResult:
        import httpx

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
            "messages": [
                {"role": "system", "content": SYSTEM + "\n\n" + JSON_INSTRUCTIONS},
                {"role": "user", "content": content},
            ],
        }
        try:
            with httpx.Client(base_url=self.base_url, timeout=180, transport=self._transport) as c:
                r = c.post("/chat/completions", json=body, headers={"Authorization": f"Bearer {self.key}"})
        except httpx.HTTPError as e:
            raise RuntimeError(f"DeepSeek 网络错误：{e.__class__.__name__}: {e}") from e
        if r.status_code in (401, 403):
            raise ProviderUnavailable(f"DeepSeek 认证失败：HTTP {r.status_code}")
        if r.status_code == 429:
            raise RuntimeError("DeepSeek 限流：HTTP 429")
        if r.status_code >= 400:
            raise RuntimeError(f"DeepSeek API 错误 {r.status_code}：{r.text[:300]}")
        d = r.json()
        choice = (d.get("choices") or [{}])[0]
        u = d.get("usage") or {}
        usage = {
            "input_tokens": u.get("prompt_tokens"),
            "output_tokens": u.get("completion_tokens"),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "cache_hit_tokens": u.get("prompt_cache_hit_tokens"),
        }
        if choice.get("finish_reason") == "length":
            return ProviderResult(
                engine="deepseek", engine_version=self.model, notes="输出被 max_tokens 截断，未解析", usage=usage
            )
        text = (choice.get("message") or {}).get("content") or ""
        try:
            parsed = MenuTranscription.model_validate_json(text)
        except Exception as e:
            return ProviderResult(
                engine="deepseek",
                engine_version=self.model,
                notes=f"模型返回无法解析为约定 JSON：{e.__class__.__name__}",
                usage=usage,
            )
        res = _to_result(parsed, self.model, usage, kind)
        res.engine = "deepseek"
        return res

    def analyze_text(self, text: str, meta: dict) -> ProviderResult:
        return self._call([{"type": "text", "text": "Transcribe this menu text into json:\n\n" + text[:60000]}], "text")

    def analyze_image(self, image: bytes, meta: dict) -> ProviderResult:
        media = meta.get("media_type") or _sniff_media(image)
        images: list[tuple[str, bytes]] = []
        if media == "application/pdf":
            images = [("image/png", b) for b in _pdf_pages_png(image, max_pages=4)]
            if not images:
                return ProviderResult(engine="deepseek", engine_version=self.model, notes="PDF 无法渲染为图片")
        else:
            images = [(media, image)]
        content: list[Any] = [
            {"type": "image_url", "image_url": {"url": f"data:{m};base64,{base64.standard_b64encode(b).decode()}"}}
            for m, b in images
        ]
        content.append(
            {"type": "text", "text": "Transcribe this menu into json and list visible layout/typography observations."}
        )
        return self._call(content, "image")


def _pdf_pages_png(data: bytes, max_pages: int = 4, resolution: int = 110) -> list[bytes]:
    from io import BytesIO

    import pdfplumber

    out: list[bytes] = []
    with pdfplumber.open(BytesIO(data)) as pdf:
        for page in pdf.pages[:max_pages]:
            buf = BytesIO()
            page.to_image(resolution=resolution).original.save(buf, format="PNG")
            out.append(buf.getvalue())
    return out


def get_provider() -> MenuProvider:
    name = get_settings().llm_provider
    if name == "fake":
        return FakeProvider()
    if name == "anthropic":
        return AnthropicProvider()
    if name == "deepseek":
        return DeepSeekProvider()
    raise ProviderUnavailable(f"未实现或未配置的模型 provider：{name}（可用：fake、anthropic、deepseek）")
