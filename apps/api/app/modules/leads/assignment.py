"""门店负责人跨批次唯一；预览后显式分配，交接冻结待发动作并保留历史。"""

import uuid
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator, lock_current
from app.core.db import get_db
from app.core.models import AuditLog, Operator
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.sales.models import Event, ManualTask, TaskStatus
from app.modules.sales.preparation import Preparation

router = APIRouter(tags=["lead-assignment"])


def manager(op: Operator = Depends(current_operator)) -> Operator:
    if op.role not in {"admin", "director"}:
        raise HTTPException(403, "分配门店需要销售总监或管理员权限")
    return op


class Selection(BaseModel):
    lead_ids: list[uuid.UUID] | None = Field(default=None, max_length=5000)
    batch_key: str | None = None
    q: str | None = None
    assigned_to: str | None = None
    view: str = "all"
    screening_class: str | None = None
    business_type_id: int | None = None


class AssignIn(BaseModel):
    # 预览返回的门店及原负责人。并发转交后拒绝覆盖，用户须重新预览。
    expected: dict[uuid.UUID, str | None] = Field(min_length=1, max_length=5000)
    assigned_to: str | None = Field(default=None, min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)


@router.get("/assignment/members")
def members(db: Session = Depends(get_db), op: Operator = Depends(manager)):
    rows = db.scalars(
        select(Operator).where(Operator.role == "member", Operator.is_active.is_(True)).order_by(Operator.username)
    ).all()
    result = []
    for p in rows:
        open_tasks = (
            select(func.count())
            .select_from(ManualTask)
            .where(
                ManualTask.assigned_to == p.username,
                ManualTask.status.in_([TaskStatus.pending, TaskStatus.opened, TaskStatus.paused]),
            )
        )
        recent = db.scalar(
            select(func.max(Event.recorded_at))
            .join(Lead, Lead.id == Event.lead_id)
            .where(Lead.assigned_to == p.username)
        )
        sent = db.scalar(
            select(func.max(ManualTask.sent_at))
            .join(Lead, Lead.id == ManualTask.lead_id)
            .where(Lead.assigned_to == p.username)
        )
        touched = [at for at in (recent, sent) if at is not None]
        recent = max(touched) if touched else None
        result.append(
            {
                "username": p.username,
                "display_name": p.display_name,
                "leads": db.scalar(select(func.count()).select_from(Lead).where(Lead.assigned_to == p.username)),
                "open_tasks": db.scalar(open_tasks),
                "drafts": db.scalar(
                    select(func.count())
                    .select_from(Preparation)
                    .where(Preparation.assigned_to == p.username, Preparation.status == "draft")
                ),
                "followups_due": db.scalar(open_tasks.where(ManualTask.follow_up_at <= datetime.now(UTC))),
                "last_communication_at": recent,
            }
        )
    return result


@router.post("/assignment/preview")
def preview(body: Selection, db: Session = Depends(get_db), op: Operator = Depends(manager)):
    query = select(Lead).order_by(Lead.id)
    if body.lead_ids is not None:
        query = query.where(Lead.id.in_(body.lead_ids))
    if body.batch_key:
        query = (
            query.join(BatchLead, BatchLead.lead_id == Lead.id)
            .join(Batch, Batch.id == BatchLead.batch_id)
            .where(Batch.batch_key == body.batch_key)
        )
    if body.q:
        query = query.where(or_(Lead.name.ilike(f"%{body.q}%"), Lead.postcode.ilike(f"%{body.q}%")))
    if body.view == "unassigned":
        query = query.where(Lead.assigned_to.is_(None))
    if body.view == "mine":
        query = query.where(Lead.assigned_to == op.username)
    if body.assigned_to:
        query = query.where(Lead.assigned_to == body.assigned_to)
    if body.screening_class:
        query = query.where(Lead.screening_class == body.screening_class)
    if body.business_type_id:
        query = query.where(Lead.raw["BusinessTypeID"].as_integer() == body.business_type_id)
    rows = db.scalars(query.limit(5001)).all()
    if len(rows) > 5000:
        raise HTTPException(422, "单次最多分配 5000 家，请缩小筛选范围")
    return {
        "count": len(rows),
        "names": {str(p.id): p.name for p in rows},
        "owners": dict(Counter(p.assigned_to or "未分配" for p in rows)),
        "expected": {str(p.id): p.assigned_to for p in rows},
    }


def transfer(db: Session, lead: Lead, target: str | None, by: Operator, reason: str) -> None:
    from app.modules.gmail.models import EmailDelivery
    from app.modules.outreach.models import OutreachDelivery

    tasks = list(db.scalars(select(ManualTask).where(ManualTask.lead_id == lead.id).with_for_update()))
    deliveries: list[EmailDelivery | OutreachDelivery] = []
    deliveries.extend(
        db.scalars(
            select(EmailDelivery).where(EmailDelivery.task_id.in_([t.id for t in tasks])).with_for_update()
        ).all()
    )
    deliveries.extend(
        db.scalars(
            select(OutreachDelivery).where(OutreachDelivery.task_id.in_([t.id for t in tasks])).with_for_update()
        ).all()
    )
    if any(d.status in {"sending", "unknown"} for d in deliveries):
        raise HTTPException(409, "该门店有发送中或结果未知记录，完成对账后才能交接")
    before = lead.assigned_to
    for d in deliveries:
        if d.status in {"preview", "ready", "queued", "blocked", "expired"}:
            d.status, d.approval_token = "cancelled", None
    for t in tasks:
        if t.status in {TaskStatus.pending, TaskStatus.opened, TaskStatus.paused}:
            t.assigned_to, t.status = target, TaskStatus.paused
            t.status_reason = "门店交接，须由新负责人复核后恢复"
    for draft in db.scalars(
        select(Preparation).where(Preparation.lead_id == lead.id, Preparation.status == "draft").with_for_update()
    ):
        draft.assigned_to = target
    lead.assigned_to = target
    audit.record(
        db,
        by,
        "lead_assigned",
        "lead",
        lead.id,
        before={"assigned_to": before},
        after={"assigned_to": target, "reason": reason},
    )


@router.post("/assignment/apply")
def assign(body: AssignIn, db: Session = Depends(get_db), op: Operator = Depends(manager)):
    # 与两个发送 worker 同序锁定，避免交接与发送确认交错。
    for key in (470012, 480012):
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    if not body.reason.strip():
        raise HTTPException(422, "请填写分配或转交原因")
    lock_current(db, op)
    if op.role not in {"admin", "director"}:
        raise HTTPException(403, "分配权限已变化")
    if body.assigned_to:
        target = db.scalar(select(Operator).where(Operator.username == body.assigned_to).with_for_update())
        if not target or not target.is_active or target.role != "member":
            raise HTTPException(422, "接收人必须为有效业务成员")
    output = []
    for identity, expected in sorted(body.expected.items()):
        try:
            with db.begin_nested():
                lead = db.scalar(
                    select(Lead).where(Lead.id == identity).with_for_update().execution_options(populate_existing=True)
                )
                if lead is None:
                    raise HTTPException(404, "门店不存在")
                if lead.assigned_to != expected:
                    raise HTTPException(409, "门店负责人已变化，请重新预览")
                changed = lead.assigned_to != body.assigned_to
                if changed:
                    transfer(db, lead, body.assigned_to, op, body.reason.strip())
                db.flush()
                output.append({"lead_id": str(identity), "assigned_to": body.assigned_to, "changed": changed})
        except HTTPException as exc:
            output.append({"lead_id": str(identity), "error": exc.detail})
    db.commit()
    return {"items": output}


@router.get("/leads/{lead_id}/assignment-history")
def history(lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    if db.get(Lead, lead_id) is None:
        raise HTTPException(404, "门店不存在")
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "lead_assigned", AuditLog.entity_id == str(lead_id))
        .order_by(AuditLog.at.desc())
    ).all()
    result = []
    for p in rows:
        actor = db.get(Operator, p.operator_id) if p.operator_id else None
        result.append(
            {
                "at": p.at,
                "operator": (actor.display_name or actor.username) if actor else "历史用户",
                "before": p.before,
                "after": p.after,
            }
        )
    return result
