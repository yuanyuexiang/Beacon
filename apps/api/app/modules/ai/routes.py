"""Administrator-managed AI connections and synthetic capability tests."""

import copy
import io
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.integrations import ai_runtime as runtime
from app.integrations.ai_observation import observe, recent
from app.integrations.llm import ProviderUnavailable
from app.modules.ai import configuration as config


def admin(op: Operator = Depends(current_operator)) -> Operator:
    if op.role != "admin":
        raise HTTPException(403, "AI 连接由管理员维护")
    return op


router = APIRouter(prefix="/ai", tags=["ai-settings"], dependencies=[Depends(admin)])


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    label: str = Field(min_length=1, max_length=100)
    provider: Literal["deepseek", "openai", "anthropic", "gemini", "qwen", "doubao", "kimi", "zhipu", "custom"]
    protocol: Literal["chat", "responses", "anthropic"] = "chat"
    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=160)
    key: str | None = Field(default=None, max_length=8192, repr=False)
    enabled: bool = True
    vision: bool = False
    json_mode: bool = True
    timeout: int = Field(default=90, ge=10, le=300)


class Routing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default: str | None = None
    research: str | None = None
    vision: str | None = None
    writing: str | None = None


class ConfigurationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str | None = None
    connections: list[Connection] = Field(max_length=30)
    routes: Routing


class VersionIn(BaseModel):
    version: str | None = None


@router.get("/settings")
def settings(db: Session = Depends(get_db)):
    return config.public(config.latest(db))


@router.put("/settings")
def save(body: ConfigurationIn, db: Session = Depends(get_db), op: Operator = Depends(admin)):
    try:
        row = config.save(db, body.model_dump())
        audit.record(
            db,
            op,
            "ai_settings_saved",
            "ai_configuration",
            row.id,
            after={"connection_ids": [c.id for c in body.connections], "routes": body.routes.model_dump()},
        )
        db.commit()
        return config.public(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None


@router.post("/import-environment")
def import_environment(body: VersionIn, db: Session = Depends(get_db), op: Operator = Depends(admin)):
    env = config.environment()
    if not env:
        raise HTTPException(409, "服务器没有可导入的真实 AI 环境配置")
    old = config.latest(db)
    data = {"connections": [], "routes": {}} if not old else copy.deepcopy(old.data)
    data["connections"] = [
        {k: v for k, v in c.items() if k not in {"encrypted_key", "test"}} for c in data["connections"]
    ]
    env["id"] = "imported-" + uuid.uuid4().hex[:12]
    data["connections"].append(env)
    data["routes"]["default"] = data["routes"].get("default") or env["id"]
    return save(ConfigurationIn.model_validate({**data, "version": body.version}), db, op)


def connection(db, key, version):
    row = config.latest(db)
    if not row or str(row.id) != version:
        raise HTTPException(409, "配置已变化，请刷新后再测试")
    item = next((c for c in row.data["connections"] if c["id"] == key), None)
    if not item:
        raise HTTPException(404, "模型连接不存在")
    value = copy.deepcopy(item)
    value["key"] = config.decrypt(value.pop("encrypted_key"))
    value["configuration_version"] = str(row.id)
    return row, runtime.Client(value)


class Probe(BaseModel):
    value: str


@router.post("/connections/{key}/test")
def test(key: str, body: VersionIn, db: Session = Depends(get_db), op: Operator = Depends(admin)):
    row, client = connection(db, key, body.version)
    reports: dict = {}
    content: object
    for capability in ["text", "structured"] + (["vision"] if client.value["vision"] else []):
        start = time.monotonic()
        try:
            if capability == "vision":
                import base64

                image = Image.new("RGB", (240, 100), "white")
                ImageDraw.Draw(image).text((25, 20), "27", fill="black", font_size=52)
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                content = [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()},
                    },
                    {"type": "text", "text": 'Read the digits in the image. Return JSON {"value":"digits"}.'},
                ]
                expected = "27"
            else:
                content = "What is twelve plus fifteen? Put only the numeric answer as a string in the value field."
                expected = "27"
            with observe("connection_test_" + capability, client.model, "test-1") as record:
                record.update(runtime.metadata(client))
                response = client.complete(
                    [
                        {
                            "role": "system",
                            "content": "Respond with a JSON object containing a string field named value.",
                        },
                        {"role": "user", "content": content},
                    ],
                    Probe,
                    1000,
                )
                record["usage"] = response.usage
                if Probe.model_validate_json(response.text).value != expected:
                    raise ProviderUnavailable("接口已连通，但模型未正确完成测试任务；请重试或选择其他模型")
            reports[capability] = {"status": "passed"}
        except (ProviderUnavailable, ValueError, KeyError, TypeError):
            # Persist only controlled errors; never provider body or validation input.
            import sys

            exc = sys.exception()
            reports[capability] = {
                "status": "failed",
                "error": str(exc)
                if isinstance(exc, ProviderUnavailable)
                else "结构化结果解析失败，请检查模型及 JSON 模式",
            }
        reports[capability]["duration_ms"] = round((time.monotonic() - start) * 1000)
    result = {
        "at": datetime.now(UTC).isoformat(),
        "checks": reports,
        "status": "passed" if all(r["status"] == "passed" for r in reports.values()) else "failed",
    }
    # Do not hold a config lock during remote calls, and never attach a result to an edited connection.
    db.rollback()
    db.execute(text("SELECT pg_advisory_xact_lock(178001)"))
    current = config.latest(db)
    if not current or current.id != row.id:
        raise HTTPException(409, "测试期间配置已变化，测试结果未采用，请重新测试")
    data = copy.deepcopy(current.data)
    next(c for c in data["connections"] if c["id"] == key)["test"] = result
    current.data = data
    audit.record(db, op, "ai_connection_tested", "ai_configuration", current.id, after={"connection_id": key, **result})
    db.commit()
    return result


class ModelListIn(Connection):
    id: str = "draft"
    label: str = "模型列表"
    model: str = ""
    version: str | None = None
    saved_id: str | None = None


def model_list(client):
    try:
        data = client.request("GET", "models")
        rows = data.get("data", [])
        ids = sorted({r["id"] for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)})[:300]
        return {"models": ids, "note": "列表只说明账号可见模型；结构化与图片能力需单独测试。"}
    except ProviderUnavailable as exc:
        raise HTTPException(409, str(exc) + "；可直接手动填写模型 ID") from None


@router.post("/models")
def draft_models(body: ModelListIn, db: Session = Depends(get_db)):
    try:
        config.validate_url(body.base_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    value = body.model_dump(exclude={"version", "saved_id"})
    if not body.key:
        if not body.saved_id:
            raise HTTPException(422, "请先填写 API Key，再获取模型")
        _, saved = connection(db, body.saved_id, body.version)
        if any(value[k] != saved.value[k] for k in ("provider", "protocol", "base_url")):
            raise HTTPException(422, "供应商或接口已改变，请填写对应的 API Key")
        value["key"] = saved.value["key"]
    return model_list(runtime.Client(value))


@router.post("/connections/{key}/models")
def models(key: str, body: VersionIn, db: Session = Depends(get_db)):
    _, client = connection(db, key, body.version)
    return model_list(client)


@router.get("/calls")
def calls():
    return recent()
