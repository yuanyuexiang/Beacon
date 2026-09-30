"""配置：来自环境变量或 apps/api/.env。缺少必要配置时在启动/首次访问时明确报错。"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BEACON_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(description="SQLAlchemy URL，例如 postgresql+psycopg://user:pass@host:5433/beacon")
    test_database_url: str | None = None
    data_dir: Path = Field(description="受控文件目录（绝对路径），存放菜单证据与样稿")
    secret_key: str = Field(min_length=32, description="会话签名密钥")
    bootstrap_operator: str | None = None
    bootstrap_password: str | None = None
    max_asset_bytes: int = 20 * 1024 * 1024
    fetch_timeout_seconds: int = 30
    # 按解析出的 IP 阻断内网目标。若本机解析器把所有域名映射到代理地址（如 198.18.0.0/15），可显式关闭；
    # 关闭后仍阻断字面量的本机/内网地址与非 http(s) 协议。
    fetch_ip_check: bool = True
    fetch_user_agent: str = "Mozilla/5.0 (Macintosh) BeaconResearch/0.1 (+research use)"
    llm_provider: str = "fake"  # fake | anthropic | deepseek
    llm_model: str | None = None  # 为空时按 provider 取默认：anthropic→claude-opus-5-5，deepseek→deepseek-flash
    llm_thinking: bool = False  # 转录任务默认关闭思考（省 token、避免截断）；DeepSeek 生效
    llm_effort: str = "medium"  # low | medium | high | xhigh | max
    anthropic_api_key: str | None = None  # 或用环境变量 ANTHROPIC_API_KEY
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    templates_dir: Path = Path(__file__).resolve().parents[4] / "templates"  # <repo>/templates
    chrome_path: Path | None = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")  # 容器内设为空

    @field_validator("chrome_path", mode="before")
    @classmethod
    def _empty_chrome(cls, v):
        return None if v in ("", None) else v

    @field_validator("data_dir")
    @classmethod
    def _abs(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError("BEACON_DATA_DIR 必须是绝对路径")
        return v


class ConfigError(RuntimeError):
    pass


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as e:  # pydantic ValidationError
        raise ConfigError(f"配置缺失或无效（检查 BEACON_* 环境变量或 apps/api/.env）：{e}") from e
