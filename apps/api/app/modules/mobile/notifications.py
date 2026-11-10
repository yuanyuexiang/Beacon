"""Notification inbox: no fuzzy identity matching and no outbound actions."""

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.auth import current_operator, may_send
from app.core.db import get_db
from app.core.models import Operator
from app.modules.leads.models import Lead
from app.modules.mobile.channels import PLATFORMS
from app.modules.mobile.models import Device, Execution, ReplyNotification, ReplyThread
from app.modules.mobile.routes import Input, check_device_access, device_auth, lock
from app.modules.sales import service
from app.modules.sales.models import Event, EventKind, ManualTask

router = APIRouter(prefix="/mobile", tags=["mobile-replies"])
worker_router = APIRouter(prefix="/api/mobile/device", tags=["mobile-replies"])


class NoticeIn(Input):
    event_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    channel: str = Field(max_length=24)
    thread_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    occurred_at: AwareDatetime
    structured: bool = False
    source: Literal["notification", "foreground"] = "notification"
    execution_id: uuid.UUID | None = None
    verified_target: str | None = Field(default=None, max_length=2000)


class LinkIn(Input):
    execution_id: uuid.UUID
    remember: bool = True


def permitted(db: Session, j: Execution, d: Device | None) -> bool:
    if d is None:
        return False
    t, lead = db.get(ManualTask, j.task_id), db.get(Lead, j.lead_id)
    owner = db.scalar(select(Operator).where(Operator.username == d.owner))
    if not (
        t
        and lead
        and owner
        and d.status != "revoked"
        and j.device_id == d.id
        and j.status in {"sent", "request_submitted", "unknown"}
    ):
        return False
    if "task_owner" in j.snapshot and j.snapshot["task_owner"] != (t.assigned_to or t.created_by):
        return False
    try:
        check_device_access(db, j.lead_id, d, t.assigned_to or t.created_by, j.confirmed_by)
    except (HTTPException, service.SalesError):
        return False
    return True


def record(
    db: Session, n: ReplyNotification, j: Execution, d: Device, automatic: bool, source: str = "notification"
) -> None:
    if not permitted(db, j, d):
        raise HTTPException(409, "门店已交接或执行记录不可关联，请刷新")
    if automatic and n.body.strip() == j.snapshot.get("body", "").strip():
        raise HTTPException(409, "与本方消息相同，请核对通知，不会自动回填")
    t = db.get(ManualTask, j.task_id)
    assert t is not None
    # The same reply can arrive from the chat and its OS notification. Only collapse
    # cross-source copies within a short window; repeated replies on one source remain distinct.
    previous = db.scalars(
        select(Event).where(
            Event.lead_id == j.lead_id,
            Event.kind == EventKind.reply,
            Event.occurred_at >= n.occurred_at - timedelta(minutes=2),
            Event.occurred_at <= n.occurred_at + timedelta(minutes=2),
        )
    ).all()
    duplicate = next(
        (
            e
            for e in previous
            if (e.payload or {}).get("task_id") == str(j.task_id)
            and (e.payload or {}).get("summary", "").strip() == n.body.strip()
            and (e.payload or {}).get("source") in {"mobile_notification", "mobile_foreground"}
            and (e.payload or {}).get("source") != "mobile_" + source
        ),
        None,
    )
    if duplicate:
        n.status, n.execution_id, n.event_id = "linked", j.id, duplicate.id
        db.commit()
        return
    event, _ = service.record_event(
        db,
        j.lead_id,
        {
            "event_key": "mobile-notice:" + str(n.id),
            "kind": "reply",
            "channel": t.channel.value,
            "occurred_at": n.occurred_at,
            "payload": {
                "summary": n.body,
                "source": "mobile_" + source,
                "time_basis": "observed" if source == "foreground" else "platform",
                "task_id": str(j.task_id),
                "notification_id": str(n.id),
                "automatic": automatic,
                "confirmed_incoming": True,
            },
        },
        d.owner,
    )
    n.status, n.execution_id, n.event_id = "linked", j.id, event.id
    db.commit()


def clean(db: Session) -> None:
    now = service.now()
    db.execute(
        delete(ReplyNotification).where(
            ((ReplyNotification.status == "pending") & (ReplyNotification.created_at < now - timedelta(days=7)))
            | ((ReplyNotification.status != "pending") & (ReplyNotification.created_at < now - timedelta(days=30)))
        )
    )


@worker_router.post("/notifications")
def receive(body: NoticeIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    if body.channel not in PLATFORMS or not body.body.strip():
        raise HTTPException(422, "无效渠道或空通知")
    if not service.now() - timedelta(days=7) <= body.occurred_at <= service.now() + timedelta(minutes=5):
        raise HTTPException(422, "通知时间超出接收范围")
    prior = db.scalar(
        select(ReplyNotification).where(
            ReplyNotification.device_id == d.id, ReplyNotification.event_key == body.event_key
        )
    )
    if prior:
        return {"id": str(prior.id), "status": prior.status, "created": False}
    clean(db)
    foreground = None
    if body.source == "foreground":
        foreground = db.get(Execution, body.execution_id) if body.execution_id else None
        if (
            not foreground
            or not permitted(db, foreground, d)
            or foreground.snapshot.get("channel", "whatsapp") != body.channel
            or foreground.snapshot.get("target") != body.verified_target
            or not body.structured
            or body.body.strip() == foreground.snapshot.get("body", "").strip()
        ):
            raise HTTPException(409, "当前聊天与手机执行记录不一致，请重新检查")
    n = ReplyNotification(device_id=d.id, **body.model_dump(exclude={"source", "execution_id", "verified_target"}))
    db.add(n)
    db.flush()
    binding = (
        db.scalar(
            select(ReplyThread).where(
                ReplyThread.device_id == d.id, ReplyThread.channel == n.channel, ReplyThread.thread_key == n.thread_key
            )
        )
        if n.thread_key
        else None
    )
    j = foreground or (db.get(Execution, binding.execution_id) if binding else None)
    # Explicit incoming message + a previously confirmed stable conversation, never a title guess.
    if (
        j
        and body.structured
        and permitted(db, j, d)
        and n.occurred_at >= j.created_at
        and n.body.strip() != j.snapshot.get("body", "").strip()
    ):
        record(db, n, j, d, True, body.source)
    else:
        db.commit()
    return {"id": str(n.id), "status": n.status, "created": True}


def public(db: Session, n: ReplyNotification) -> dict:
    j = db.get(Execution, n.execution_id) if n.execution_id else None
    event = db.get(Event, n.event_id) if n.event_id else None
    payload = (event.payload or {}) if event else {}
    return {
        "source": payload.get("source", "mobile_notification"),
        "time_basis": payload.get("time_basis", "platform"),
        "id": str(n.id),
        "channel": n.channel,
        "title": n.title,
        "body": n.body,
        "occurred_at": n.occurred_at,
        "status": n.status,
        "stable_thread": bool(n.thread_key),
        "structured": n.structured,
        "read": bool(n.read_at),
        "lead_id": str(j.lead_id) if j else None,
        "lead_name": j.snapshot.get("lead_name") if j else None,
    }


@router.get("/notifications")
def inbox(
    status: Literal["pending", "linked", "ignored"] = "pending",
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
):
    clean(db)
    notices = list(
        db.scalars(
            select(ReplyNotification)
            .join(Device)
            .where(Device.owner == op.username, ReplyNotification.status == status)
            .order_by(ReplyNotification.created_at.desc())
            .limit(100)
        )
    )
    db.commit()
    return [public(db, n) for n in notices]


@router.get("/reply-targets")
def targets(q: str = "", db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    rows = db.scalars(
        select(Execution)
        .join(Device)
        .where(
            Device.owner == op.username,
            Execution.status.in_(["sent", "request_submitted", "unknown"]),
            Execution.snapshot["lead_name"].astext.ilike("%" + q[:200] + "%"),
        )
        .order_by(Execution.created_at.desc())
        .limit(300)
    )
    return [
        {
            "id": str(j.id),
            "channel": j.snapshot.get("channel", "whatsapp"),
            "lead_name": j.snapshot.get("lead_name"),
            "target": j.snapshot.get("target"),
        }
        for j in rows
        if permitted(db, j, db.get(Device, j.device_id))
    ][:100]


def own(db: Session, identity: uuid.UUID, op: Operator) -> ReplyNotification:
    if not may_send(db, op.username):
        raise HTTPException(403, "没有回复管理权限")
    lock(db)
    n = db.scalar(
        select(ReplyNotification)
        .join(Device)
        .where(ReplyNotification.id == identity, Device.owner == op.username)
        .with_for_update(of=ReplyNotification)
    )
    if not n:
        raise HTTPException(404, "通知不存在")
    return n


@router.post("/notifications/{identity}/link")
def link(identity: uuid.UUID, body: LinkIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    n = own(db, identity, op)
    if n.status != "pending":
        if n.status == "linked" and n.execution_id == body.execution_id:
            return public(db, n)
        raise HTTPException(409, "通知已处理，请刷新")
    j = db.get(Execution, body.execution_id)
    d = db.get(Device, n.device_id)
    if not d or not j or not permitted(db, j, d) or j.snapshot.get("channel", "whatsapp") != n.channel:
        raise HTTPException(409, "请关联当前负责的同渠道手机会话")
    if n.occurred_at < j.created_at:
        raise HTTPException(409, "通知早于本次联系记录，请核对会话")
    if body.remember and n.thread_key:
        binding = db.scalar(
            select(ReplyThread).where(
                ReplyThread.device_id == d.id, ReplyThread.channel == n.channel, ReplyThread.thread_key == n.thread_key
            )
        )
        if binding and binding.execution_id != j.id:
            raise HTTPException(409, "此会话已关联其他记录，请先解除会话关联")
        if not binding:
            db.add(ReplyThread(device_id=d.id, channel=n.channel, thread_key=n.thread_key, execution_id=j.id))
    n.read_at = service.now()
    record(db, n, j, d, False)
    return public(db, n)


@router.post("/notifications/{identity}/ignore")
def ignore(identity: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    n = own(db, identity, op)
    if n.status != "pending":
        raise HTTPException(409, "通知已处理")
    n.status = "ignored"
    n.body = "（已忽略）"
    db.commit()
    return public(db, n)


@router.post("/notification-threads/reset")
def reset(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    if not may_send(db, op.username):
        raise HTTPException(403, "没有回复管理权限")
    lock(db)
    db.execute(
        delete(ReplyThread).where(ReplyThread.device_id.in_(select(Device.id).where(Device.owner == op.username)))
    )
    db.commit()
    return {"ok": True}


@router.post("/notifications/{identity}/read")
def read_notice(identity: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    n = own(db, identity, op)
    n.read_at = service.now()
    db.commit()
    return {"ok": True}
