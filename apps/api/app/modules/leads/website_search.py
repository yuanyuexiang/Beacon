"""搜索只生成候选；人工确认官网时记录地址核对依据、来源、操作者与时间。"""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import Operator
from app.integrations import exa
from app.modules.leads.models import Lead

router = APIRouter(tags=["leads"])
CACHE_TTL = timedelta(days=7)
NOTICE = "搜索摘录未经实时核验；同名异店、目录、社媒和概念演示站都可能出现在结果中。请打开页面核对经营者与门店地址。"
SOCIAL = {"facebook.com", "instagram.com", "tiktok.com", "youtube.com", "x.com", "twitter.com", "linkedin.com"}
DIRECTORIES = {
    "exa.ai",
    "ratings.food.gov.uk",
    "sluurpy.co.uk",
    "wheree.com",
    "restaurantguru.com",
    "mymenuweb.com",
    "ubereats.com",
}


class SearchIn(BaseModel):
    query: str | None = Field(default=None, max_length=600)


class ConfirmIn(BaseModel):
    search_id: uuid.UUID
    candidate_id: str = Field(min_length=1, max_length=64)
    expected_website: str | None = Field(default=None, max_length=512)
    address_checked: bool
    official_checked: bool
    evidence: str = Field(min_length=1, max_length=1500)

    @field_validator("evidence")
    @classmethod
    def evidence_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("请输入核对依据")
        return v.strip()


def _lead(db: Session, lead_id: uuid.UUID, *, lock: bool = False) -> Lead:
    query = select(Lead).where(Lead.id == lead_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    lead = db.scalar(query)
    if lead is None:
        raise HTTPException(404, "线索不存在")
    return lead


def _compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _flags(candidate: dict[str, str], lead: Lead) -> dict:
    host = (urlparse(candidate["url"]).hostname or "").lower()

    def belongs(domains: set[str]) -> bool:
        return any(host == domain or host.endswith("." + domain) for domain in domains)

    flags = []
    if belongs(SOCIAL):
        flags.append("社媒页面，不是独立官网")
    if belongs(DIRECTORIES):
        flags.append("目录或第三方平台，需核对原始官网")
    if host.endswith(".lovable.app") or host.endswith(".vercel.app") or "concept" in host:
        flags.append("可能是演示站，请核对运营方")
    postcode_seen = bool(lead.postcode and _compact(lead.postcode) in _compact(candidate["excerpt"]))
    return {
        **candidate,
        "id": hashlib.sha256(candidate["url"].encode()).hexdigest()[:20],
        "postcode_seen": postcode_seen,
        "warnings": flags,
    }


@router.get("/leads/{lead_id}/website-search")
def get_search(
    lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict | None:
    """读取最近一次候选，不产生外部搜索请求。"""
    return (_lead(db, lead_id).raw or {}).get("website_search")


@router.post("/leads/{lead_id}/website-search")
def search_website(
    lead_id: uuid.UUID, body: SearchIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    lead = _lead(db, lead_id)
    query = (body.query or "").strip() or " ".join(
        x for x in (lead.name, lead.address, lead.postcode, "official restaurant website menu") if x
    )[:600]
    try:
        candidates = exa.search(query, get_settings().exa_api_key)
    except exa.SearchError as e:
        raise HTTPException(e.status, str(e)) from e
    # 网络请求后重新读取并锁定行，避免覆盖同时记录的 contacts_scan 等 raw 数据。
    lead = _lead(db, lead_id, lock=True)
    now = datetime.now(UTC)
    result = {
        "search_id": str(uuid.uuid4()),
        "provider": "exa",
        "query": query,
        "searched_at": now.isoformat(),
        "expires_at": (now + CACHE_TTL).isoformat(),
        "candidates": [_flags(c, lead) for c in candidates],
        "notice": NOTICE,
    }
    lead.raw = {**(lead.raw or {}), "website_search": result}
    audit.record(
        db,
        op,
        "search_website",
        "lead",
        lead.id,
        after={"search_id": result["search_id"], "provider": "exa", "candidate_count": len(candidates)},
    )
    db.commit()
    return result


@router.post("/leads/{lead_id}/website-confirm")
def confirm_website(
    lead_id: uuid.UUID, body: ConfirmIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    if not body.address_checked or not body.official_checked:
        raise HTTPException(400, "须核对门店地址并确认页面由该商家运营")
    lead = _lead(db, lead_id, lock=True)
    result = (lead.raw or {}).get("website_search") or {}
    if result.get("search_id") != str(body.search_id):
        raise HTTPException(409, "候选已更新，请重新打开最新搜索结果")
    if datetime.fromisoformat(result["expires_at"]) < datetime.now(UTC):
        raise HTTPException(409, "候选已超过七天，请重新搜索并核对")
    candidate = next((c for c in result["candidates"] if c["id"] == body.candidate_id), None)
    if candidate is None:
        raise HTTPException(400, "候选不存在")
    if lead.website != body.expected_website:
        raise HTTPException(409, "官网已被修改，请刷新后核对再确认")
    before = {"website": lead.website, "website_source": lead.website_source}
    confirmation = {
        "search_id": result["search_id"],
        "candidate_url": candidate["url"],
        "provider": "exa",
        "query": result["query"],
        "searched_at": result["searched_at"],
        "reviewed_at": datetime.now(UTC).isoformat(),
        "reviewed_by": op.username,
        "address_checked": True,
        "official_checked": True,
        "evidence": body.evidence,
    }
    lead.website = candidate["url"]
    lead.website_source = "Exa 搜索，人工核对"
    lead.raw = {**(lead.raw or {}), "website_confirmation": confirmation}
    audit.record(
        db,
        op,
        "confirm_website",
        "lead",
        lead.id,
        before=before,
        after={"website": lead.website, "website_source": lead.website_source, **confirmation},
    )
    db.commit()
    return {"website": lead.website, "website_source": lead.website_source}
