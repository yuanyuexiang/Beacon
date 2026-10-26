"""D8/D9：准入、人工任务、事件与抑制。核心规则：
- eligibility=allowed 必须有证据与规则版本，且由操作者写入；unknown/blocked 不生成可执行任务。
- 任务创建、打开、记录发送三个时点都重新检查：准入、联系可用、审批有效、抑制、复核到期。
- 打开只记录打开；记录发送需操作者与实际发生时间；系统不调用任何发送 API。
- 事件按 event_key 幂等；回复→暂停；拒绝/退订→抑制并取消；退信→该渠道联系失效。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.content import service as content_service
from app.modules.content.models import ContentPiece
from app.modules.leads.models import Lead
from app.modules.sales.models import (
    Channel,
    ChannelEligibility,
    ContactUsable,
    Eligibility,
    Event,
    EventKind,
    ManualTask,
    Suppression,
    SuppressionScope,
    TaskStatus,
)

OPEN_STATUSES = (TaskStatus.pending, TaskStatus.opened, TaskStatus.paused)


class SalesError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


# ---------- 准入 ----------


def upsert_eligibility(db: Session, lead_id: uuid.UUID, data: dict, by: str) -> ChannelEligibility:
    db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
    if (data.get("rule_version") or "").startswith("ai-admission:"):
        raise SalesError("AI 准入规则版本由系统写入，不能用于人工审核")
    elig = Eligibility(data["eligibility"])
    if elig == Eligibility.allowed and (not (data.get("evidence") or "").strip() or not data.get("rule_version")):
        raise SalesError("eligibility=allowed 必须提供证据与规则版本")
    contact_ref = (data.get("contact_ref") or "").strip() or None
    row = db.scalar(
        select(ChannelEligibility).where(
            ChannelEligibility.lead_id == lead_id,
            ChannelEligibility.channel == Channel(data["channel"]),
            ChannelEligibility.contact_ref.is_(None)
            if contact_ref is None
            else ChannelEligibility.contact_ref == contact_ref,
        )
    )
    if row is None:
        row = ChannelEligibility(lead_id=lead_id, channel=Channel(data["channel"]), contact_ref=contact_ref)
        db.add(row)
    row.contact_source = data.get("contact_source")
    row.contact_collected_at = data.get("contact_collected_at")
    row.contact_usable = ContactUsable(data.get("contact_usable") or "unknown")
    row.eligibility = elig
    row.rule_version = data.get("rule_version")
    row.evidence = data.get("evidence")
    row.review_due_at = data.get("review_due_at")
    row.reviewed_by = by
    row.reviewed_at = now()
    db.commit()
    db.refresh(row)
    return row


def is_suppressed(db: Session, lead_id: uuid.UUID, contact_ref: str | None) -> Suppression | None:
    conds = [(Suppression.scope == SuppressionScope.lead) & (Suppression.lead_id == lead_id)]
    if contact_ref:
        conds.append((Suppression.scope == SuppressionScope.contact) & (Suppression.contact_ref == contact_ref))
    return db.scalar(select(Suppression).where(or_(*conds)).limit(1))


def email_recipient_confirmed(db: Session, elig: ChannelEligibility, piece: ContentPiece) -> bool:
    from app.modules.content.models import Approval, ApprovalDecision

    if elig.channel.value != "email":
        return False
    approval = db.scalar(
        select(Approval).where(Approval.content_id == piece.id).order_by(Approval.decided_at.desc()).limit(1)
    )
    return bool(
        approval
        and approval.decision == ApprovalDecision.approved
        and approval.content_hash == piece.content_hash
        and approval.note == f"recipient-confirmed:{elig.id}:{elig.contact_ref}"
    )


def check_can_contact(
    db: Session, elig: ChannelEligibility, content: ContentPiece, *, require_approval: bool = True
) -> None:
    """三个时点共用的复核；任一不满足抛 SalesError。"""
    if (elig.rule_version or "").startswith("ai-admission:"):
        db.scalar(
            select(Lead).where(Lead.id == elig.lead_id).with_for_update().execution_options(populate_existing=True)
        )
        db.refresh(elig)
    if elig.lead_id != content.lead_id:
        raise SalesError("准入记录与内容不属于同一线索")
    if (content.spec or {}).get("channel") and (content.spec or {})["channel"] != elig.channel.value:
        raise SalesError("消息生成渠道与所选联系方式不一致，请为当前渠道重新起草")
    if (content.spec or {}).get("recipient_id") and (content.spec or {})["recipient_id"] != str(elig.id):
        raise SalesError("消息面向的联系人已变化，请为当前联系人重新起草")
    confirmed_email = email_recipient_confirmed(db, elig, content)
    if elig.conditions and not confirmed_email:
        from app.modules.sales import channel_conditions

        gaps = channel_conditions.missing(elig.channel.value, elig.conditions)
        gaps += channel_conditions.content_missing(elig.conditions, str(content.id), content.content_hash)
        if gaps:
            raise SalesError("；".join(gaps))
    if elig.eligibility != Eligibility.allowed and (not confirmed_email or elig.eligibility == Eligibility.blocked):
        raise SalesError(f"渠道准入为 {elig.eligibility}，不能生成或执行任务")
    if not confirmed_email and (elig.rule_version or "").startswith("ai-admission:"):
        from app.modules.sales import admission

        lead = db.get(Lead, elig.lead_id)
        why = admission.stale_reason(db, lead, elig) if lead else "门店不存在"
        if why:
            raise SalesError(why)
        spec = content.spec or {}
        body = content.body_text or ""
        if any(
            not isinstance(spec.get(key), str) or not spec[key].strip() or spec[key].strip() not in body
            for key in ("sender_identity", "opt_out_text")
        ):
            raise SalesError("自动准入邮件仍需明确的发送身份与退出说明")
    if elig.contact_usable == ContactUsable.invalid:
        raise SalesError("联系方式已标记无效")
    if not confirmed_email and elig.review_due_at and elig.review_due_at < now():
        raise SalesError("准入复核已到期，需重新审核")
    ok, why = (
        content_service.approval_valid(db, content)
        if require_approval
        else content_service.source_still_valid(db, content)
    )
    if not ok:
        raise SalesError(f"内容审批无效：{why}")
    sup = is_suppressed(db, elig.lead_id, elig.contact_ref)
    if sup is not None:
        raise SalesError(f"已在抑制名单（{sup.reason}，{sup.created_at:%Y-%m-%d}）")


# ---------- 任务 ----------


def create_task(
    db: Session, lead_id: uuid.UUID, eligibility_id: uuid.UUID, content_id: uuid.UUID, by: str, *, commit: bool = True
) -> ManualTask:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
    if lead is None:
        raise SalesError("门店不存在或无访问权限")
    elig = db.get(ChannelEligibility, eligibility_id)
    content = db.get(ContentPiece, content_id)
    if elig is None or content is None or elig.lead_id != lead_id:
        raise SalesError("准入记录或内容不存在，或不属于该线索")
    check_can_contact(db, elig, content)
    dup = db.scalar(
        select(ManualTask).where(
            ManualTask.lead_id == lead_id,
            ManualTask.eligibility_id == elig.id,
            ManualTask.content_id == content.id,
            ManualTask.status.in_(OPEN_STATUSES),
        )
    )
    if dup is not None:
        raise SalesError("同一准入与内容已有未完成任务")
    t = ManualTask(
        lead_id=lead_id,
        channel=elig.channel,
        eligibility_id=elig.id,
        content_id=content.id,
        content_hash=content.content_hash,
        status=TaskStatus.pending,
        created_by=by,
        assigned_to=lead.assigned_to or by,
    )
    db.add(t)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(t)
    return t


def check_member_owner(db: Session, lead_id: uuid.UUID, username: str | None) -> None:
    from app.core.models import Operator

    member = db.scalar(select(Operator).where(Operator.username == username))
    lead = db.scalar(select(Lead).where(Lead.id == lead_id))
    if member and (not member.is_active or member.role not in {"admin", "director", "member"}):
        raise SalesError("负责人已停用或无业务权限，请重新分配")
    if not lead or (member and member.role == "member" and lead.assigned_to != username):
        raise SalesError("任务负责人已无门店权限，请由销售总监重新分配")


def check_task_owner(db: Session, task: ManualTask) -> None:
    check_member_owner(db, task.lead_id, task.assigned_to or task.created_by)


def _recheck_or_pause(db: Session, t: ManualTask) -> None:
    elig = db.get(ChannelEligibility, t.eligibility_id)
    content = db.get(ContentPiece, t.content_id)
    assert elig is not None and content is not None
    try:
        check_task_owner(db, t)
        check_can_contact(db, elig, content)
        if content.content_hash != t.content_hash:
            raise SalesError("内容已变化，与任务创建时不一致")
    except SalesError as e:
        t.status = TaskStatus.paused
        t.status_reason = f"复核未通过：{e}"
        db.commit()
        raise


def open_task(db: Session, t: ManualTask, by: str) -> ManualTask:
    db.scalar(select(Lead).where(Lead.id == t.lead_id).with_for_update())
    db.refresh(t, with_for_update=True)
    check_gmail_in_flight(db, t)
    if t.status not in (TaskStatus.pending, TaskStatus.opened):
        raise SalesError(f"任务状态为 {t.status}，不能打开")
    _recheck_or_pause(db, t)
    t.status = TaskStatus.opened
    t.opened_at = t.opened_at or now()
    t.opened_by = by
    db.commit()
    db.refresh(t)
    return t


def check_gmail_in_flight(db: Session, t: ManualTask) -> None:
    from app.modules.gmail.models import EmailDelivery
    from app.modules.outreach.models import OutreachDelivery

    social = db.scalar(select(OutreachDelivery).where(OutreachDelivery.task_id == t.id))
    if social and social.status in {"ready", "queued", "sending", "unknown", "sent"}:
        raise SalesError("已有社媒消息排队、发送中或结果待确认；请在社媒记录中处理")

    row = db.scalar(select(EmailDelivery).where(EmailDelivery.task_id == t.id))
    if row and row.status in {"ready", "queued", "queued_paused", "sending", "unknown", "sent"}:
        raise SalesError("已有 Gmail 邮件排队、发送中或结果待确认；请在邮件记录中处理")


def record_sent(db: Session, t: ManualTask, sent_at: datetime, by: str, notes: str | None) -> ManualTask:
    db.scalar(select(Lead).where(Lead.id == t.lead_id).with_for_update())
    db.refresh(t, with_for_update=True)
    check_gmail_in_flight(db, t)
    if t.status != TaskStatus.opened:
        raise SalesError(f"任务状态为 {t.status}，只有已打开的任务可记录发送")
    if sent_at > now():
        raise SalesError("发送时间不能晚于现在")
    _recheck_or_pause(db, t)
    t.status = TaskStatus.sent_manual
    t.sent_at = sent_at
    t.sent_recorded_at = now()
    t.sent_by = by
    t.notes = notes
    db.commit()
    db.refresh(t)
    return t


def cancel_task(db: Session, t: ManualTask, reason: str) -> ManualTask:
    db.scalar(select(Lead).where(Lead.id == t.lead_id).with_for_update())
    db.refresh(t, with_for_update=True)
    check_gmail_in_flight(db, t)
    if t.status in (TaskStatus.sent_manual, TaskStatus.sent_email, TaskStatus.sent_social):
        raise SalesError("已记录发送的任务不能取消")
    t.status = TaskStatus.cancelled
    t.status_reason = reason
    db.commit()
    db.refresh(t)
    return t


def resume_task(db: Session, t: ManualTask, by: str, reason: str) -> ManualTask:
    """暂停后由负责人明确决定恢复；恢复时重新复核。"""
    db.scalar(select(Lead).where(Lead.id == t.lead_id).with_for_update())
    db.refresh(t, with_for_update=True)
    if t.status != TaskStatus.paused:
        raise SalesError("只有暂停的任务可恢复")
    t.status = TaskStatus.pending
    t.status_reason = f"恢复：{reason}（{by}）"
    db.commit()
    _recheck_or_pause(db, t)
    db.refresh(t)
    return t


# ---------- 事件与抑制 ----------


def record_event(db: Session, lead_id: uuid.UUID, data: dict, by: str) -> tuple[Event, bool]:
    db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
    existing = db.scalar(select(Event).where(Event.event_key == data["event_key"]))
    if existing is not None:
        if existing.lead_id != lead_id:
            raise SalesError("事件键已用于其他客户，请重新生成事件键")
        return existing, False
    kind = EventKind(data["kind"])
    channel = Channel(data["channel"]) if data.get("channel") else None
    ev = Event(
        lead_id=lead_id,
        channel=channel,
        event_key=data["event_key"],
        kind=kind,
        occurred_at=data.get("occurred_at"),
        recorded_at=now(),
        recorded_by=by,
        payload=data.get("payload") or {},
        actions=[],
    )
    db.add(ev)
    db.flush()
    actions: list[dict] = []
    open_tasks = db.scalars(
        select(ManualTask).where(ManualTask.lead_id == lead_id, ManualTask.status.in_(OPEN_STATUSES))
    ).all()
    if kind == EventKind.reply:
        for t in open_tasks:
            if t.status != TaskStatus.paused:
                t.status, t.status_reason = TaskStatus.paused, f"收到人工回复（事件 {ev.event_key}），等待负责人决定"
                actions.append({"action": "pause_task", "task_id": str(t.id)})
    elif kind in (EventKind.reject, EventKind.unsubscribe):
        sup = Suppression(
            lead_id=lead_id,
            scope=SuppressionScope.lead,
            reason=kind.value,
            source_event_id=ev.id,
            created_at=now(),
            created_by=by,
        )
        db.add(sup)
        actions.append({"action": "suppress_lead", "reason": kind.value})
        cref = (ev.payload or {}).get("contact_ref")
        if cref:
            db.add(
                Suppression(
                    lead_id=lead_id,
                    scope=SuppressionScope.contact,
                    contact_ref=cref,
                    reason=kind.value,
                    source_event_id=ev.id,
                    created_at=now(),
                    created_by=by,
                )
            )
            actions.append({"action": "suppress_contact", "contact_ref": cref})
        for t in open_tasks:
            t.status, t.status_reason = TaskStatus.cancelled, f"{kind.value}（事件 {ev.event_key}）"
            actions.append({"action": "cancel_task", "task_id": str(t.id)})
    elif kind == EventKind.bounce:
        cref = (ev.payload or {}).get("contact_ref")
        q = select(ChannelEligibility).where(ChannelEligibility.lead_id == lead_id)
        if channel:
            q = q.where(ChannelEligibility.channel == channel)
        if cref:
            q = q.where(ChannelEligibility.contact_ref == cref)
        for e in db.scalars(q).all():
            e.contact_usable = ContactUsable.invalid
            actions.append({"action": "contact_invalid", "eligibility_id": str(e.id)})
        for t in open_tasks:
            if channel is None or t.channel == channel:
                t.status, t.status_reason = TaskStatus.cancelled, f"退信/无效（事件 {ev.event_key}）"
                actions.append({"action": "cancel_task", "task_id": str(t.id)})
    ev.actions = actions
    db.commit()
    db.refresh(ev)
    return ev, True
