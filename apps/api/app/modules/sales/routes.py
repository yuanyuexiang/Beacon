import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.sales import contacts, service, summary
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
    _lead(db, lead_id)
    return list(db.scalars(select(ChannelEligibility).where(ChannelEligibility.lead_id == lead_id)).all())


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


@router.post("/leads/{lead_id}/contacts")
def record_contacts(
    lead_id: uuid.UUID, body: ContactsIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """记录人工勾选的联系方式：可用性与准入均为 unknown；已存在的跳过，不覆盖审核结果。"""
    _lead(db, lead_id)
    items = [i.model_dump(mode="json") for i in body.items]
    result = contacts.record_contacts(db, lead_id, items)
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
    ev, created = service.record_event(db, lead_id, body.model_dump(), op.username)
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
    return list(db.scalars(select(Suppression).order_by(Suppression.created_at)).all())


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
