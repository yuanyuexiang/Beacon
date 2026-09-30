"""可替换的模型接口。业务只依赖 MenuProvider 协议；FakeProvider 返回预置结果供测试。
真实厂商适配器在拿到密钥并完成评测后再加入；模型不得修改审批、准入或销售状态。"""

from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import get_settings


@dataclass
class ProviderResult:
    engine: str
    engine_version: str
    items: list[dict] = field(default_factory=list)  # 与规则引擎相同结构
    issues: list[dict] = field(default_factory=list)
    notes: str | None = None


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


def get_provider() -> MenuProvider:
    name = get_settings().llm_provider
    if name == "fake":
        return FakeProvider()
    raise ProviderUnavailable(f"未实现或未配置的模型 provider：{name}（当前仅 fake；真实厂商待密钥与评测后接入）")
