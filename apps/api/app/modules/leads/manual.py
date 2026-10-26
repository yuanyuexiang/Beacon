"""Manual leads share the same memberships, ownership and contact records as imported leads."""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.integrations import website_contacts as wc
from app.modules.leads import workflows
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.sales.contacts import record_contacts
from app.modules.sales.models import ChannelEligibility

router = APIRouter(prefix="/leads/manual", tags=["leads"])


def website_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    u = urlsplit(value)
    if u.scheme not in {"http", "https"} or not u.hostname or "." not in u.hostname or u.username or u.password:
        raise ValueError("请输入有效的 http/https 网站地址")
    return value


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    channel: str
    contact_ref: str = Field(min_length=1, max_length=512)

    @field_validator("channel")
    @classmethod
    def channel_valid(cls, v):
        if v not in {"email", "phone", "facebook", "instagram", "linkedin", "tiktok", "whatsapp", "contact_form"}:
            raise ValueError("不支持的联系方式")
        return v


class ManualIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: uuid.UUID
    name: str = Field(min_length=1, max_length=256)
    address: str | None = Field(default=None, max_length=1000)
    postcode: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, max_length=128)
    website: str | None = Field(default=None, max_length=512)
    contact_name: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    batch_key: str | None = Field(default=None, max_length=64)
    assigned_to: str | None = Field(default=None, max_length=64)
    contacts: list[ContactIn] = Field(default_factory=list, max_length=15)
    allow_duplicate: bool = False

    @field_validator("website")
    @classmethod
    def website_valid(cls, v):
        return website_url(v) if v else None


def contact_values(body: ManualIn) -> list[dict]:
    values = []
    for c in body.contacts:
        ref = c.contact_ref
        if c.channel == "email":
            if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", ref):
                raise HTTPException(422, "请输入有效邮箱地址")
            ref = ref.lower()
        elif c.channel in {"phone", "whatsapp"}:
            normalized = wc.normalize_uk_phone(ref)
            if not normalized:
                raise HTTPException(422, "请输入有效联系电话，国际号码请带国家区号")
            ref = normalized
        else:
            try:
                ref = website_url(ref)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            if c.channel != "contact_form":
                match = wc.classify_link(ref)
                if not match or match[0] != c.channel:
                    raise HTTPException(422, "社媒地址与所选平台不一致")
        values.append({"channel": c.channel, "contact_ref": ref, "contact_source": "用户手动录入"})
    return values


def duplicates(db: Session, body: ManualIn, contacts: list[dict]) -> list[dict]:
    tests = [func.lower(Lead.name) == body.name.lower()]
    host = (urlsplit(body.website).hostname or "").removeprefix("www.") if body.website else ""
    if host:
        tests.append(Lead.website.ilike("%" + host.replace("%", "\\%").replace("_", "\\_") + "%"))
    if contacts:
        tests.append(
            Lead.id.in_(
                select(ChannelEligibility.lead_id).where(
                    func.lower(ChannelEligibility.contact_ref).in_([c["contact_ref"].lower() for c in contacts])
                )
            )
        )
    out = []
    for lead in db.scalars(select(Lead).where(or_(*tests)).order_by(Lead.created_at.desc()).limit(20)):
        reasons = []
        if lead.name.lower() == body.name.lower():
            reasons.append("名称相同")
        if host and (urlsplit(lead.website or "").hostname or "").removeprefix("www.") == host:
            reasons.append("官网域名相同（可能是不同分店）")
        if contacts and db.scalar(
            select(ChannelEligibility.id)
            .where(
                ChannelEligibility.lead_id == lead.id,
                func.lower(ChannelEligibility.contact_ref).in_([c["contact_ref"].lower() for c in contacts]),
            )
            .limit(1)
        ):
            reasons.append("联系方式相同")
        if not reasons:
            continue
        out.append(
            {
                "id": str(lead.id),
                "name": lead.name,
                "address": lead.address,
                "postcode": lead.postcode,
                "reasons": reasons,
            }
        )
    return out


@router.post("/check")
def check(body: ManualIn, db: Session = Depends(get_db)):
    return {"duplicates": duplicates(db, body, contact_values(body))}


@router.post("", status_code=201)
def create(body: ManualIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    values = contact_values(body)
    # Serialise manual create/retry, including the first personal list creation.
    db.execute(text("select pg_advisory_xact_lock(73190217)"))
    key = f"manual:{op.id}:{body.request_id}"
    fingerprint = hashlib.sha256(
        json.dumps(body.model_dump(mode="json", exclude={"allow_duplicate"}), sort_keys=True).encode()
    ).hexdigest()
    existing = db.scalar(select(Lead).where(Lead.source_key == key))
    if existing:
        if (existing.raw or {}).get("manual_entry", {}).get("request_hash") != fingerprint:
            raise HTTPException(409, "此保存请求已用于其他内容，请打开已保存的门店")
        batch = db.scalar(select(Batch).join(BatchLead).where(BatchLead.lead_id == existing.id))
        return {"id": str(existing.id), "batch_key": batch.batch_key if batch else None, "reused": True}
    if db.scalar(select(Lead.__table__.c.id).where(Lead.__table__.c.source_key == key)):
        raise HTTPException(409, "门店已保存且归属已变化，请联系销售总监查看")
    assignee = body.assigned_to or op.username
    if op.role == "member" and assignee != op.username:
        raise HTTPException(403, "业务成员新增门店只能分配给自己")
    if not db.scalar(
        select(Operator.id).where(
            Operator.username == assignee,
            Operator.is_active.is_(True),
            Operator.role.in_(["admin", "director", "member"]),
        )
    ):
        raise HTTPException(422, "请选择有效的业务负责人")
    matches = duplicates(db, body, values)
    if matches and not body.allow_duplicate:
        raise HTTPException(409, {"message": "发现可能已有的门店，请核对后选择仍然新建", "duplicates": matches})
    if body.batch_key:
        batch = db.scalar(select(Batch).where(Batch.batch_key == body.batch_key))
        if not batch or (
            op.role == "member" and not db.scalar(select(BatchLead.id).where(BatchLead.batch_id == batch.id))
        ):
            raise HTTPException(404, "名单不存在或无权使用")
    else:
        list_key = f"手动录入-{op.username[:30]}-{str(op.id)[:8]}"
        batch = db.scalar(select(Batch).where(Batch.batch_key == list_key))
        if not batch:
            batch = Batch(batch_key=list_key, country="GB", source_name="manual", source_version=str(op.id))
            db.add(batch)
            db.flush()
    with workflows.lock(db, batch):
        workflows.ensure_idle(db, batch)
        lead = Lead(
            source_key=key,
            source_name="manual",
            name=body.name,
            address=body.address,
            postcode=body.postcode.upper() if body.postcode else None,
            website=body.website,
            website_source="用户手动录入（人工）" if body.website else None,
            assigned_to=assignee,
            raw={
                "website_manual": bool(body.website),
                "manual_entry": {
                    "created_by": op.username,
                    "created_at": datetime.now(UTC).isoformat(),
                    "region": body.region,
                    "contact_name": body.contact_name,
                    "notes": body.notes,
                    "request_hash": fingerprint,
                },
            },
        )
        db.add(lead)
        db.flush()
        db.add(BatchLead(batch_id=batch.id, lead_id=lead.id))
        record_contacts(db, lead.id, values)
        audit.record(
            db,
            op,
            "create_manual_lead",
            "lead",
            lead.id,
            after={"batch_key": batch.batch_key, "assigned_to": assignee, "duplicate_confirmed": body.allow_duplicate},
        )
        db.commit()
        return {"id": str(lead.id), "batch_key": batch.batch_key, "reused": False}
