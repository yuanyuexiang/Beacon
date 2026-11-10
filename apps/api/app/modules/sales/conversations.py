"""Read models over existing sends and replies. No duplicate message storage or implicit sends."""

import uuid
from email.utils import parseaddr

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.modules.content.models import ContentPiece
from app.modules.gmail.models import EmailDelivery
from app.modules.mobile.models import Execution
from app.modules.outreach.models import Conversation, OutreachDelivery
from app.modules.sales import service, workbench
from app.modules.sales.models import ChannelEligibility, Event, EventKind
from app.modules.sales.preparation import ConversationRead

router = APIRouter(prefix="/communication", tags=["communication"])


def event_contact(db: Session, event: Event, contacts: list[ChannelEligibility], tasks: dict) -> str:
    payload = event.payload or {}
    candidates = {str(c.id): c for c in contacts if c.channel == event.channel}
    # Prefer stable bindings. A missing/deleted binding must not silently match a different address.
    if payload.get("eligibility_id"):
        return str(payload["eligibility_id"]) if str(payload["eligibility_id"]) in candidates else "unlinked"
    if payload.get("task_id"):
        task = tasks.get(str(payload["task_id"]))
        return str(task.eligibility_id) if task and str(task.eligibility_id) in candidates else "unlinked"
    if payload.get("conversation_id"):
        try:
            conv = db.get(Conversation, uuid.UUID(payload["conversation_id"]))
        except ValueError:
            conv = None
        return (
            str(conv.eligibility_id)
            if conv and conv.lead_id == event.lead_id and str(conv.eligibility_id) in candidates
            else "unlinked"
        )
    if payload.get("gmail_thread_id"):
        bound = {
            str(tasks[str(d.task_id)].eligibility_id)
            for d in db.scalars(
                select(EmailDelivery).where(
                    EmailDelivery.task_id.in_([t.id for t in tasks.values()]),
                    EmailDelivery.gmail_thread_id == payload["gmail_thread_id"],
                )
            )
        }
        if len(bound) == 1 and next(iter(bound)) in candidates:
            return next(iter(bound))
    value = payload.get("contact_ref") or (
        parseaddr(payload.get("from") or "")[1] if event.channel == "email" else None
    )
    matched = [
        key
        for key, c in candidates.items()
        if value and (c.contact_ref or "").strip().casefold() == value.strip().casefold()
    ]
    return matched[0] if len(matched) == 1 else "unlinked"


def project(db: Session, lead_id: uuid.UUID, operator: str) -> list[dict]:
    contacts = list(db.scalars(select(ChannelEligibility).where(ChannelEligibility.lead_id == lead_id)))
    rows: dict[str, dict] = {
        str(c.id): {
            "id": str(c.id),
            "channel": c.channel.value,
            "contact_ref": c.contact_ref,
            "messages": [],
            "unread": 0,
        }
        for c in contacts
    }
    rows["unlinked"] = {"id": "unlinked", "channel": None, "contact_ref": "未关联记录", "messages": [], "unread": 0}
    tasks = {str(t.id): t for t in workbench.tasks_for(db, lead_id)}
    history = workbench.activity(lead_id, db)
    deliveries: dict[str, list] = {}
    for d in history["deliveries"]:
        deliveries.setdefault(d["task_id"], []).append(d)
    read = {
        r.contact_key: r.read_through
        for r in db.scalars(
            select(ConversationRead).where(ConversationRead.lead_id == lead_id, ConversationRead.operator == operator)
        )
    }
    pieces = {
        str(p.id): p
        for p in db.scalars(select(ContentPiece).where(ContentPiece.id.in_([t.content_id for t in tasks.values()])))
    }
    email_rows = {
        str(d.task_id): d
        for d in db.scalars(select(EmailDelivery).where(EmailDelivery.task_id.in_([t.id for t in tasks.values()])))
    }
    social_rows = {
        str(d.task_id): d
        for d in db.scalars(
            select(OutreachDelivery).where(OutreachDelivery.task_id.in_([t.id for t in tasks.values()]))
        )
    }
    phone_rows = {
        str(d.task_id): d
        for d in db.scalars(select(Execution).where(Execution.task_id.in_([t.id for t in tasks.values()])))
    }
    for key, task in tasks.items():
        piece = pieces.get(str(task.content_id))
        contact_key = str(task.eligibility_id) if str(task.eligibility_id) in rows else "unlinked"
        records = sorted(deliveries.get(key, []), key=lambda d: d["at"])
        latest = records[-1] if records else None
        # Provider payloads are immutable sending snapshots; use them when available.
        body, subject = piece.body_text if piece else "", (piece.spec or {}).get("subject", "") if piece else ""
        email = email_rows.get(key)
        if email:
            body, subject = email.payload.get("body", body), email.payload.get("subject", subject)
        if key in social_rows:
            body = social_rows[key].payload.get("text", body)
        if key in phone_rows:
            body = phone_rows[key].snapshot.get("body", body)
        rows[contact_key]["messages"].append(
            {
                "id": "task:" + key,
                "task_id": key,
                "direction": "outbound",
                "channel": task.channel.value,
                "at": task.sent_at or task.created_at,
                "arrived_at": task.created_at,
                "body": body or task.notes or "消息内容未留存",
                "subject": subject,
                "status": latest["status"] if latest else task.status.value,
                "source": task.execution_mode,
                "error": (latest or {}).get("error") or task.status_reason,
                "deliveries": records,
            }
        )
    for event in db.scalars(select(Event).where(Event.lead_id == lead_id)):
        key = event_contact(db, event, contacts, tasks)
        payload = event.payload or {}
        incoming = event.kind != EventKind.note
        rows[key]["messages"].append(
            {
                "id": "event:" + str(event.id),
                "event_id": str(event.id),
                "direction": "inbound" if incoming else "note",
                "channel": event.channel.value if event.channel else None,
                "at": event.occurred_at or event.recorded_at,
                "arrived_at": event.recorded_at,
                "body": payload.get("summary") or payload.get("intent") or event.kind.value,
                "subject": payload.get("subject"),
                "status": event.kind.value,
                "source": payload.get("source") or event.recorded_by or "manual",
                "deliveries": [],
                "headers_only": bool(payload.get("gmail_message_id")),
            }
        )
        if incoming and (key not in read or event.recorded_at > read[key]):
            rows[key]["unread"] += 1
    for row in rows.values():
        row["messages"].sort(key=lambda m: (m["at"], m["id"]))
        row["read_through"] = max((m["arrived_at"] for m in row["messages"]), default=None)
    return [r for r in rows.values() if r["id"] != "unlinked" or r["messages"]]


@router.get("/conversations/{lead_id}")
def conversations(lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    workbench.lead_or_404(db, lead_id)
    return {"items": project(db, lead_id, op.username)}


class ReadIn(BaseModel):
    through: AwareDatetime


@router.put("/conversations/{lead_id}/{contact_key}/read")
def mark_read(
    lead_id: uuid.UUID,
    contact_key: str,
    body: ReadIn,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
):
    workbench.lead_or_404(db, lead_id, lock=True)
    # Only acknowledge the watermark actually returned to the client. A later-arriving reply stays unread.
    row = next((r for r in project(db, lead_id, op.username) if r["id"] == contact_key), None)
    if not row or not row["read_through"] or body.through > row["read_through"]:
        raise HTTPException(422, "已读位置无效，请刷新会话")
    receipt = db.scalar(
        select(ConversationRead).where(
            ConversationRead.lead_id == lead_id,
            ConversationRead.contact_key == contact_key,
            ConversationRead.operator == op.username,
        )
    )
    if receipt is None:
        db.add(
            ConversationRead(lead_id=lead_id, contact_key=contact_key, operator=op.username, read_through=body.through)
        )
    elif body.through > receipt.read_through:
        receipt.read_through = body.through
    db.commit()
    return {"ok": True}


class LinkIn(BaseModel):
    contact_id: uuid.UUID


@router.post("/conversations/{lead_id}/events/{event_id}/link")
def link_event(
    lead_id: uuid.UUID,
    event_id: uuid.UUID,
    body: LinkIn,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
):
    workbench.lead_or_404(db, lead_id, lock=True)
    event, contact = db.get(Event, event_id), db.get(ChannelEligibility, body.contact_id)
    if (
        not event
        or event.lead_id != lead_id
        or not contact
        or contact.lead_id != lead_id
        or contact.channel != event.channel
    ):
        raise HTTPException(422, "回复与所选联系方式不属于同一客户和渠道")
    event.payload = {**(event.payload or {}), "eligibility_id": str(contact.id)}
    audit.record(db, op, "link_reply_contact", "event", event.id, after={"eligibility_id": str(contact.id)})
    db.commit()
    return {"ok": True}


class ReplyIn(BaseModel):
    event_key: str = Field(min_length=1, max_length=256)
    kind: EventKind = EventKind.reply
    summary: str = Field(min_length=1, max_length=10000)
    occurred_at: AwareDatetime | None = None


@router.post("/conversations/{lead_id}/{contact_id}/reply")
def record_reply(
    lead_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: ReplyIn,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
):
    workbench.lead_or_404(db, lead_id, lock=True)
    contact = db.get(ChannelEligibility, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(404, "联系方式不存在")
    event, _ = service.record_event(
        db,
        lead_id,
        {
            "event_key": body.event_key,
            "kind": body.kind,
            "channel": contact.channel.value,
            "occurred_at": body.occurred_at,
            "payload": {
                "eligibility_id": str(contact.id),
                "contact_ref": contact.contact_ref,
                "summary": body.summary,
                "source": "manual",
            },
        },
        op.username,
    )
    db.commit()
    return {"id": str(event.id)}
