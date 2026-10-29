"""AI settings: immutable revisions, concurrency protection and encrypted write-only credentials."""

import copy
import os
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai.models import AIConfiguration

PRESETS = [
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "protocol": "chat",
        "base_url": "https://api.deepseek.com",
        "docs": "https://api-docs.deepseek.com/",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "protocol": "responses",
        "base_url": "https://api.openai.com/v1",
        "docs": "https://developers.openai.com/api/docs/",
    },
    {
        "id": "anthropic",
        "label": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "docs": "https://platform.claude.com/docs/",
    },
    {
        "id": "gemini",
        "label": "Google Gemini",
        "protocol": "chat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "docs": "https://ai.google.dev/gemini-api/docs/openai",
    },
    {
        "id": "qwen",
        "label": "通义千问（阿里云百炼）",
        "protocol": "chat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "docs": "https://help.aliyun.com/zh/model-studio/",
    },
    {
        "id": "doubao",
        "label": "豆包（火山方舟）",
        "protocol": "chat",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "docs": "https://www.volcengine.com/docs/82379",
    },
    {
        "id": "kimi",
        "label": "Kimi",
        "protocol": "chat",
        "base_url": "https://api.moonshot.ai/v1",
        "docs": "https://platform.kimi.ai/docs/",
    },
    {
        "id": "zhipu",
        "label": "智谱 GLM",
        "protocol": "chat",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "docs": "https://docs.bigmodel.cn/",
    },
    {"id": "custom", "label": "自定义兼容接口", "protocol": "chat", "base_url": "", "docs": ""},
]
PURPOSES = {"research": "资料理解", "vision": "菜单识别", "writing": "文案生成"}


def latest(db: Session) -> AIConfiguration | None:
    return db.scalar(
        select(AIConfiguration).order_by(AIConfiguration.created_at.desc(), AIConfiguration.id.desc()).limit(1)
    )


def cipher() -> Fernet:
    path = get_settings().data_dir / "ai" / "encryption.key"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        # Atomic creation: never expose an empty/partial key to another worker.
        import tempfile

        fd, filename = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(Fernet.generate_key())
                output.flush()
                os.fsync(output.fileno())
            with suppress(FileExistsError):
                os.link(filename, path)
        finally:
            Path(filename).unlink(missing_ok=True)
    return Fernet(path.read_bytes())


def encrypt(key: str) -> str:
    return cipher().encrypt(key.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        raise ValueError("AI 密钥无法解密，请恢复数据卷中的 ai/encryption.key 或重新填写密钥") from None


def validate_url(value: str) -> str:
    from app.integrations.fetcher import FetchBlocked, check_url

    try:
        u = urlsplit(value)
        if u.scheme != "https" or u.username or u.password or u.query or u.fragment:
            raise ValueError()
        check_url(value, resolve=False)
    except (ValueError, FetchBlocked):
        raise ValueError("接口地址需为公网 HTTPS Base URL，不能包含账号、查询参数或片段") from None
    return value.rstrip("/")


def environment() -> dict | None:
    s = get_settings()
    if s.llm_provider not in {"deepseek", "anthropic"}:
        return None
    key = (
        (s.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY"))
        if s.llm_provider == "deepseek"
        else (s.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    )
    if not key:
        return None
    return {
        "id": "environment",
        "label": "服务器环境配置",
        "provider": s.llm_provider,
        "protocol": "chat" if s.llm_provider == "deepseek" else "anthropic",
        "base_url": s.deepseek_base_url if s.llm_provider == "deepseek" else "https://api.anthropic.com/v1",
        "model": s.llm_model or ("deepseek-flash" if s.llm_provider == "deepseek" else "claude-opus-5-5"),
        "vision": True,
        "json_mode": True,
        "enabled": True,
        "timeout": 180,
        "key": key,
    }


def public(row: AIConfiguration | None) -> dict:
    data = copy.deepcopy(row.data) if row else {"connections": [], "routes": {}}
    for connection in data["connections"]:
        connection["key_configured"] = bool(connection.pop("encrypted_key", None))
    env = environment()
    if env:
        env.pop("key")
        env["key_configured"] = True
    return {
        **data,
        "version": str(row.id) if row else None,
        "environment": env,
        "source": "managed" if row else "environment",
        "presets": PRESETS,
        "purposes": PURPOSES,
    }


def save(db: Session, body: dict) -> AIConfiguration:
    db.execute(text("SELECT pg_advisory_xact_lock(178001)"))
    old = latest(db)
    if body.get("version") != (str(old.id) if old else None):
        raise HTTPException(409, "AI 配置已被其他管理员修改，请重新加载后再保存")
    previous = {c["id"]: c for c in old.data["connections"]} if old else {}
    connections = []
    for submitted in body["connections"]:
        item = dict(submitted)
        key = item.pop("key", None)
        prior = previous.get(item["id"], {})
        item["base_url"] = validate_url(item["base_url"])
        if prior and any(prior.get(k) != item.get(k) for k in ("base_url", "provider")) and not (key and key.strip()):
            raise ValueError("更换供应商或接口地址时请重新填写对应的 API Key")
        item["encrypted_key"] = encrypt(key.strip()) if key and key.strip() else prior.get("encrypted_key")
        if not item["encrypted_key"]:
            raise ValueError("请为新增连接填写 API Key")
        if all(
            item.get(k) == prior.get(k)
            for k in ("provider", "protocol", "base_url", "model", "vision", "json_mode", "timeout", "encrypted_key")
        ):
            item["test"] = prior.get("test")
        connections.append(item)
    ids = [c["id"] for c in connections]
    if len(set(ids)) != len(ids):
        raise ValueError("连接 ID 不能重复")
    routes = body["routes"]
    enabled = {c["id"] for c in connections if c["enabled"]}
    for value in routes.values():
        if value is not None and value not in enabled:
            raise ValueError("所选模型连接已删除或停用，请调整用途分配")
    if any(routes.get(p) for p in PURPOSES) and not routes.get("default"):
        raise ValueError("请先选择默认模型连接")
    by_id = {c["id"]: c for c in connections}
    vision = routes.get("vision")
    if vision and not by_id[vision]["vision"]:
        raise ValueError("菜单识别连接需启用图片输入能力")
    row = AIConfiguration(data={"connections": connections, "routes": routes})
    db.add(row)
    db.flush()
    return row
