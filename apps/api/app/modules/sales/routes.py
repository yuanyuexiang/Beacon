import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.sales import channel_conditions, contacts, service, summary
from app.modules.sales.models import (
    Channel,
    ChannelEligibility,
    ContactUsable,
    CostCategory,
    CostEntry,
    Eligibility,
    Event,
    EventKind,
    ManualTask,
    Suppression,
    SuppressionScope,
    TaskStatus,
)

router = APIRouter(tags=["sales"])


class EligibilityIn(BaseModel):
    channel: Channel
    contact_ref: str | None = None
    contact_source: str | None = None
    contact_collected_at: datetime | None = None
    contact_usable: ContactUsable = ContactUsable.unknown
    eligibility: Eligibility = Eligibility.unknown
    rule_version: str | None = None
    evidence: str | None = None
    review_due_at: datetime | None = None


class EligibilityOut(EligibilityIn):
    id: uuid.UUID
    lead_id: uuid.UUID
    reviewed_by: str | None
    reviewed_at: datetime | None
    recommendation: dict | None = None
    auto_admission: dict | None = None
    contact_conditions: dict | None = None

    model_config = {"from_attributes": True}


class TaskIn(BaseModel):
    eligibility_id: uuid.UUID
    content_id: uuid.UUID


class TaskOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    channel: Channel
    eligibility_id: uuid.UUID
    content_id: uuid.UUID
    content_hash: str
    status: TaskStatus
    status_reason: str | None
    source_batch_id: uuid.UUID | None = None
    assigned_to: str | None = None
    execution_mode: str = "manual"
    follow_up_at: datetime | None = None
    created_by: str | None
    opened_at: datetime | None
    opened_by: str | None
    sent_at: datetime | None
    sent_recorded_at: datetime | None
    sent_by: str | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SentIn(BaseModel):
    sent_at: datetime
    notes: str | None = None


class ReasonIn(BaseModel):
    reason: str


class EventIn(BaseModel):
    event_key: str
    kind: EventKind
    channel: Channel | None = None
    occurred_at: datetime | None = None
    payload: dict[str, Any] | None = None


class EventOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    channel: Channel | None
    event_key: str
    kind: EventKind
    occurred_at: datetime | None
    recorded_at: datetime
    recorded_by: str | None
    payload: dict | None
    actions: list | None
    duplicate: bool = False

    model_config = {"from_attributes": True}


class SuppressionOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID | None
    scope: SuppressionScope
    contact_ref: str | None
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


def _lead(db: Session, lead_id: uuid.UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    return lead


def _task(db: Session, task_id: uuid.UUID) -> ManualTask:
    t = db.get(ManualTask, task_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return t


@router.post("/leads/{lead_id}/eligibility", response_model=EligibilityOut)
def upsert_eligibility(
    lead_id: uuid.UUID, body: EligibilityIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    _lead(db, lead_id)
    try:
        row = service.upsert_eligibility(db, lead_id, body.model_dump(), op.username)
    except service.SalesError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    audit.record(db, op, "eligibility", "channel_eligibility", row.id, after=body.model_dump(mode="json"))
    db.commit()
    return row


@router.get("/leads/{lead_id}/eligibility", response_model=list[EligibilityOut])
def list_eligibility(lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    from app.modules.sales import admission, contact_ranking

    lead = _lead(db, lead_id)
    rows = list(db.scalars(select(ChannelEligibility).where(ChannelEligibility.lead_id == lead_id)).all())
    return [
        {
            **EligibilityOut.model_validate(row).model_dump(),
            "recommendation": contact_ranking.stored(lead, row.channel.value, row.contact_ref),
            "auto_admission": admission.public(db, lead, row),
            "contact_conditions": channel_conditions.public(row),
        }
        for row in rows
    ]


class ContactItem(BaseModel):
    channel: Channel
    contact_ref: str = Field(min_length=1, max_length=256)
    contact_source: str | None = Field(default=None, max_length=256)


class ContactsIn(BaseModel):
    items: list[ContactItem] = Field(min_length=1, max_length=50)


@router.get("/leads/{lead_id}/contact-candidates")
def contact_candidates(
    lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """从官网页面与已存的 Overture 数据找联系方式（邮箱、电话、WhatsApp、社媒、联系表单），供人工核对。只读。"""
    return contacts.find_contacts(db, _lead(db, lead_id))


@router.post("/leads/{lead_id}/contact-review")
def review_contacts(
    lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    try:
        result = contacts.review_contacts(db, _lead(db, lead_id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(db, op, "review_contact_candidates", "lead", lead_id, after=result["ai"])
    db.commit()
    return result


@router.post("/leads/{lead_id}/auto-admission")
def auto_admission(
    lead_id: uuid.UUID, refresh: bool = True, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    try:
        if refresh:
            result = contacts.review_contacts(db, _lead(db, lead_id))
        else:
            from app.modules.sales import admission

            result = {"admission": admission.apply(db, _lead(db, lead_id)), "ai": None}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(db, op, "run_auto_admission", "lead", lead_id, after=result.get("admission"))
    db.commit()
    return {"summary": result.get("admission"), "ai": result["ai"]}


class ContactConfirmationIn(BaseModel):
    recommendation: Literal["recommended", "backup", "not_recommended", "review"]
    affiliation: Literal["target", "group", "other", "unknown"]
    owner: str = Field(max_length=150)
    purpose: Literal[
        "business", "general", "booking", "media", "recruitment", "complaints", "support", "other", "unknown"
    ]
    reason: str = Field(min_length=5, max_length=1500)
    source_url: HttpUrl | None = None
    contact_usable: ContactUsable = ContactUsable.unknown

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("请填写实际核对依据，不能只填空白")
        return value

    @model_validator(mode="after")
    def supported(self):
        if self.recommendation == "recommended" and (
            not self.owner.strip() or self.affiliation != "target" or self.purpose not in {"business", "general"}
        ):
            raise ValueError("优先推荐需确认目标门店归属及商务／通用用途")
        return self


@router.post("/leads/{lead_id}/contacts/{contact_id}/confirm")
def confirm_contact(
    lead_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: ContactConfirmationIn,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> dict:
    from app.modules.sales import contact_ranking

    lead = db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update().execution_options(populate_existing=True))
    row = db.scalar(
        select(ChannelEligibility)
        .where(ChannelEligibility.id == contact_id, ChannelEligibility.lead_id == lead_id)
        .with_for_update()
    )
    if lead is None or row is None:
        raise HTTPException(404, "门店或联系方式不存在")
    before = contact_ranking.stored(lead, row.channel.value, row.contact_ref)
    assessment = {
        **body.model_dump(mode="json", exclude={"source_url", "contact_usable"}),
        "method": "manual",
        "confirmed_by": op.username,
        "confirmed_at": service.now().isoformat(),
        "citations": [
            {"url": str(body.source_url) if body.source_url else None, "quote": body.reason, "document_id": "manual"}
        ],
    }
    records = dict((lead.raw or {}).get("contact_confirmations") or {})
    records[contact_ranking.candidate_id(row.channel.value, row.contact_ref or "")] = {
        "website": lead.website,
        "assessment": assessment,
    }
    lead.raw = {**(lead.raw or {}), "contact_confirmations": records}
    row.contact_usable = body.contact_usable
    audit.record(db, op, "confirm_contact_facts", "channel_eligibility", row.id, before=before, after=assessment)
    db.commit()
    return assessment


@router.post("/leads/{lead_id}/contacts")
def record_contacts(
    lead_id: uuid.UUID, body: ContactsIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """记录人工勾选的联系方式：可用性与准入均为 unknown；已存在的跳过，不覆盖审核结果。"""
    _lead(db, lead_id)
    items = [i.model_dump(mode="json") for i in body.items]
    result = contacts.record_contacts(db, lead_id, items)
    from app.modules.sales import admission

    lead = _lead(db, lead_id)
    admission.apply(db, lead)
    audit.record(db, op, "record_contacts", "lead", lead_id, after={**result, "items": items})
    db.commit()
    return result


@router.post("/leads/{lead_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(
    lead_id: uuid.UUID, body: TaskIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    _lead(db, lead_id)
    try:
        t = service.create_task(db, lead_id, body.eligibility_id, body.content_id, op.username)
    except service.SalesError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(
        db, op, "create_task", "manual_task", t.id, after={"channel": t.channel, "content_hash": t.content_hash}
    )
    db.commit()
    return t


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    status_: TaskStatus | None = None,
    lead_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
):
    q = select(ManualTask).order_by(ManualTask.created_at)
    if status_ is not None:
        q = q.where(ManualTask.status == status_)
    if lead_id is not None:
        q = q.where(ManualTask.lead_id == lead_id)
    return list(db.scalars(q).all())


@router.post("/tasks/{task_id}/open", response_model=TaskOut)
def open_task(task_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    t = _task(db, task_id)
    try:
        t = service.open_task(db, t, op.username)
    except service.SalesError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(db, op, "open_task", "manual_task", t.id)
    db.commit()
    return t


@router.post("/tasks/{task_id}/sent", response_model=TaskOut)
def record_sent(
    task_id: uuid.UUID, body: SentIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    """销售人工发送后回填。不调用任何发送 API。"""
    t = _task(db, task_id)
    try:
        t = service.record_sent(db, t, body.sent_at, op.username, body.notes)
    except service.SalesError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(db, op, "record_sent", "manual_task", t.id, after={"sent_at": body.sent_at.isoformat()})
    db.commit()
    return t


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(
    task_id: uuid.UUID, body: ReasonIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    t = _task(db, task_id)
    try:
        t = service.cancel_task(db, t, body.reason)
    except service.SalesError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(db, op, "cancel_task", "manual_task", t.id, after={"reason": body.reason})
    db.commit()
    return t


@router.post("/tasks/{task_id}/resume", response_model=TaskOut)
def resume_task(
    task_id: uuid.UUID, body: ReasonIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    t = _task(db, task_id)
    try:
        t = service.resume_task(db, t, op.username, body.reason)
    except service.SalesError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(db, op, "resume_task", "manual_task", t.id, after={"reason": body.reason})
    db.commit()
    return t


@router.post("/leads/{lead_id}/events", response_model=EventOut)
def record_event(
    lead_id: uuid.UUID, body: EventIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    _lead(db, lead_id)
    try:
        ev, created = service.record_event(db, lead_id, body.model_dump(), op.username)
    except (service.SalesError, IntegrityError):
        db.rollback()
        raise HTTPException(409, "事件键冲突，请核对当前客户或重新生成事件键") from None
    if created:
        audit.record(db, op, "event", "event", ev.id, after={"kind": ev.kind, "actions": ev.actions})
        db.commit()
    out = EventOut.model_validate(ev)
    out.duplicate = not created
    return out


@router.get("/leads/{lead_id}/events", response_model=list[EventOut])
def list_events(lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    return list(db.scalars(select(Event).where(Event.lead_id == lead_id).order_by(Event.recorded_at)).all())


@router.get("/suppressions", response_model=list[SuppressionOut])
def list_suppressions(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    query = select(Suppression).order_by(Suppression.created_at)
    if op.role == "member":
        from app.modules.leads.models import Lead

        query = query.where(Suppression.lead_id.in_(select(Lead.id)))
    return list(db.scalars(query).all())


class CostIn(BaseModel):
    batch_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    category: CostCategory
    currency: str | None = None
    amount: Decimal | None = None
    minutes: int | None = None
    basis: str | None = None
    occurred_at: datetime


class CostOut(CostIn):
    id: uuid.UUID
    recorded_by: str | None

    model_config = {"from_attributes": True}


@router.post("/costs", response_model=CostOut, status_code=201)
def add_cost(body: CostIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    if body.amount is None and body.minutes is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "amount 与 minutes 至少填一项")
    if op.role == "member" and body.lead_id is None:
        raise HTTPException(403, "业务成员只能记录自己门店的成本")
    if body.amount is not None and not body.currency:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "有金额必须填币种")
    if body.batch_id is None and body.lead_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "batch_id 与 lead_id 至少填一项")
    if body.lead_id is not None and body.batch_id is None:
        m = db.scalar(select(BatchLead).where(BatchLead.lead_id == body.lead_id).limit(1))
        if m is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不属于任何批次")
        body.batch_id = m.batch_id
    c = CostEntry(**body.model_dump(), recorded_by=op.username)
    db.add(c)
    db.flush()
    audit.record(db, op, "cost", "cost_entry", c.id, after=body.model_dump(mode="json"))
    db.commit()
    db.refresh(c)
    return c


@router.get("/batches/{batch_key}/summary")
def batch_summary(batch_key: str, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> dict:
    b = db.scalar(select(Batch).where(Batch.batch_key == batch_key))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    return summary.summarize(db, b)


@router.get("/batches/{batch_key}/export.csv")
def batch_export(batch_key: str, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> Response:
    b = db.scalar(select(Batch).where(Batch.batch_key == batch_key))
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    return Response(
        summary.export_csv(db, b),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{batch_key}.csv"'},
    )


@router.post("/leads/{lead_id}/contacts/{contact_id}/conditions")
def review_conditions(
    lead_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: channel_conditions.Review,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
):
    _lead(db, lead_id)
    db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
    row = db.get(ChannelEligibility, contact_id)
    if not row or row.lead_id != lead_id:
        raise HTTPException(404, "联系方式不存在")
    record = {
        **body.model_dump(mode="json"),
        "version": channel_conditions.VERSION,
        "reviewed_by": op.username,
        "reviewed_at": service.now().isoformat(),
    }
    if body.purpose == "requested_reply" and body.decision == "allowed":
        from app.modules.content import service as content_service
        from app.modules.content.models import ContentKind, ContentPiece

        piece = db.get(ContentPiece, body.content_id) if body.content_id else None
        if not piece or piece.lead_id != lead_id or piece.kind != ContentKind.message_short:
            raise HTTPException(422, "请选择本门店的回复消息")
        valid, why = content_service.source_still_valid(db, piece)
        if not valid:
            raise HTTPException(422, "回复来源已变化：" + (why or "请重新起草"))
        if (piece.spec or {}).get("channel") and (piece.spec or {})["channel"] != row.channel.value:
            raise HTTPException(422, "回复消息渠道不匹配")
        record["content_hash"] = piece.content_hash
    errors = channel_conditions.missing(row.channel.value, record)
    if body.decision == "allowed":
        if not body.confirmed:
            errors.append("请确认已核对真实依据")
        if service.is_suppressed(db, lead_id, row.contact_ref):
            errors.append("客户或联系方式已拒收，不能允许联系")
        if row.contact_usable == ContactUsable.invalid:
            errors.append("联系方式无效")
        if errors:
            raise HTTPException(422, "；".join(errors))
    before = {"conditions": row.conditions, "eligibility": row.eligibility.value}
    row.conditions = record
    row.eligibility = Eligibility(body.decision)
    row.rule_version = channel_conditions.VERSION
    row.evidence = body.note
    row.reviewed_by, row.reviewed_at = op.username, service.now()
    row.review_due_at = min((e.expires_at for e in body.evidence if e.expires_at), default=None)
    audit.record(db, op, "channel_conditions", "channel_eligibility", row.id, before=before, after=record)
    db.commit()
    return channel_conditions.public(row)


@router.get("/leads/{lead_id}/contacts/{contact_id}/conditions")
def get_conditions(lead_id: uuid.UUID, contact_id: uuid.UUID, db: Session = Depends(get_db)):
    _lead(db, lead_id)
    row = db.get(ChannelEligibility, contact_id)
    if not row or row.lead_id != lead_id:
        raise HTTPException(404, "联系方式不存在")
    return channel_conditions.public(row)
