"""版本化筛选策略；配置变更以审计事件保存，任务冻结配置快照。"""

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import AuditLog, Operator
from app.modules.leads.models import Lead, ScreeningClass

router = APIRouter(tags=["lead-policy"])
Action = Literal["keep", "review", "exclude"]


def default_chains() -> list[str]:
    from app.modules.leads.service import CHAIN_NAMES

    return CHAIN_NAMES.copy()


class Policy(BaseModel):
    version: str = "default-v3"
    chain_action: Action = "review"
    institution_action: Action = "review"
    cafe_action: Action = "keep"
    pub_action: Action = "keep"
    brand_action: Literal["keep", "review"] = "review"
    chain_names: list[str] = Field(default_factory=default_chains)
    institution_words: list[str] = Field(
        default_factory=lambda: ["school", "college", "hospital", "community", "canteen", "staff"]
    )
    google_mode: Literal["off", "needed", "all"] = "needed"
    google_request_limit: int = Field(default=20, ge=1, le=200)
    stale_days: int = Field(default=90, ge=1, le=365)

    @field_validator("chain_names", "institution_words")
    @classmethod
    def words(cls, values: list[str]) -> list[str]:
        if len(values) > 200 or any(not v.strip() or len(v) > 100 for v in values):
            raise ValueError("最多 200 项，每项 1～100 字")
        return list(dict.fromkeys(v.strip() for v in values))


def current(db: Session) -> Policy:
    row = db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "lead_policy_saved")
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    return Policy.model_validate(row.after) if row else Policy()


@router.get("/lead-policy", response_model=Policy)
def get_policy(db: Session = Depends(get_db)) -> Policy:
    return current(db)


@router.put("/lead-policy", response_model=Policy)
def save_policy(body: Policy, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> Policy:
    import uuid

    db.execute(text("SELECT pg_advisory_xact_lock(70931247)"))
    old = current(db)
    if old.version != body.version:
        raise HTTPException(409, "策略已被修改，请刷新后重新保存")
    body.version = uuid.uuid4().hex
    audit.record(db, op, "lead_policy_saved", "lead_policy", "global", before=old.model_dump(), after=body.model_dump())
    db.flush()
    row = db.scalar(
        select(AuditLog).where(AuditLog.action == "lead_policy_saved", AuditLog.after["version"].astext == body.version)
    )
    assert row is not None
    row.at = datetime.now(UTC)
    db.commit()
    return body


def contains(name: str, words: list[str]) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", name, re.I) for w in words)


def evaluate(lead: Lead, policy: Policy) -> tuple[ScreeningClass, str, list[str]]:
    from app.modules.leads.service import CAFE_WORDS, PUB_WORDS

    matches: list[tuple[Action, str, ScreeningClass]] = []
    name = lead.name or ""
    operation = (lead.raw or {}).get("operating_type") or {}
    category = operation.get("category") if operation.get("citations") else None
    known = category not in (None, "unknown")
    for hit, action, reason, cls in (
        (
            contains(name, policy.chain_names),
            policy.chain_action,
            "名称匹配连锁清单（尚未核实经营归属）",
            ScreeningClass.excluded_chain,
        ),
        (
            bool(((lead.raw or {}).get("overture") or {}).get("brand")),
            policy.brand_action,
            "Overture 有品牌信息，不能据此确定为连锁",
            ScreeningClass.excluded_chain,
        ),
        (
            category == "institution" or (not known and contains(name, policy.institution_words)),
            policy.institution_action,
            "官网原文识别为机构餐饮" if known else "名称含机构词（可能是店名）",
            ScreeningClass.excluded_institution,
        ),
        (
            category == "cafe" or (not known and bool(CAFE_WORDS.search(name))),
            "review"
            if category == "cafe"
            and "food_service" in operation.get("services", [])
            and policy.cafe_action == "exclude"
            else policy.cafe_action,
            (
                "官网原文识别为咖啡馆（供应餐食，混合经营）"
                if "food_service" in operation.get("services", [])
                else "官网原文识别为咖啡馆"
            )
            if known
            else "名称含咖啡馆／面包店／Deli 词",
            ScreeningClass.excluded_cafe,
        ),
        (
            category == "pub" or (not known and bool(PUB_WORDS.search(name))),
            "review"
            if category == "pub" and "food_service" in operation.get("services", []) and policy.pub_action == "exclude"
            else policy.pub_action,
            (
                "官网原文识别为 Pub／酒吧（供应餐食，混合经营）"
                if "food_service" in operation.get("services", [])
                else "官网原文识别为 Pub／酒吧"
            )
            if known
            else "名称含 Pub／Inn 等词",
            ScreeningClass.excluded_pub,
        ),
    ):
        if hit:
            matches.append((action, reason, cls))
    excluded = next((m for m in matches if m[0] == "exclude"), None)
    cls = excluded[2] if excluded else ScreeningClass.unchecked
    reasons = [f"{action}: {reason}" for action, reason, _ in matches]
    return cls, f"策略 {policy.version}: " + ("；".join(reasons) or "未命中规则，待识别"), reasons
