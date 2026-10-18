"""客户沟通工作台：仅准备和定位，不触发外部发送。"""

import uuid
from datetime import timedelta
from typing import Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.integrations.fetcher import FetchBlocked, check_url
from app.modules.content import service as content_service
from app.modules.content.models import ContentKind, ContentPiece
from app.modules.gmail.models import EmailDelivery
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.menus.models import MenuAnalysis, MenuAsset
from app.modules.outreach.models import ChannelAccount, Conversation, OutreachDelivery
from app.modules.sales import service
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
from app.modules.sales.preparation import Preparation

router = APIRouter(prefix="/communication", tags=["communication"])
Mode = Literal["manual", "gmail", "social"]
SENT = (TaskStatus.sent_manual, TaskStatus.sent_email, TaskStatus.sent_social)


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    channel: Channel = Channel.email
    execution_mode: Mode = "manual"
    batch_key: str | None = Field(default=None, max_length=64)
    assigned_to: str | None = Field(default=None, max_length=64)
    purpose: Literal["initial", "followup"] = "initial"


class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    eligibility_id: uuid.UUID | None = None
    content_id: uuid.UUID | None = None
    assigned_to: str | None = Field(default=None, max_length=64)
    execution_mode: Mode | None = None
    follow_up_at: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=1500)


class ActivateIn(BaseModel):
    draft_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    group_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class TaskPatch(BaseModel):
    assigned_to: str | None = Field(default=None, max_length=64)
    execution_mode: Mode | None = None
    follow_up_at: AwareDatetime | None = None


def lead_or_404(db: Session, identity: uuid.UUID, lock: bool = False) -> Lead:
    q = select(Lead).where(Lead.id == identity)
    lead = db.scalar(q.with_for_update().execution_options(populate_existing=True) if lock else q)
    if lead is None:
        raise HTTPException(404, "客户不存在")
    return lead


def owner(db: Session, username: str | None) -> None:
    if username and not db.scalar(
        select(Operator.id).where(
            Operator.username == username, Operator.is_active.is_(True), Operator.role.in_(["admin", "member"])
        )
    ):
        raise HTTPException(422, "负责人必须为有效管理员或业务成员")


def check_mode(channel: str, mode: str) -> None:
    if (mode == "gmail" and channel != "email") or (mode == "social" and channel not in {"facebook", "instagram"}):
        raise HTTPException(422, "该渠道不支持所选接口执行方式，请选择人工执行")


def manual_target(channel: str, value: str | None) -> str | None:
    import re

    value = (value or "").strip()
    if channel == "email":
        return (
            "mailto:" + quote(value, safe="@.+") if re.fullmatch(r"[^\s@?&#]+@[^\s@?&#]+\.[^\s@?&#]+", value) else None
        )
    if channel in {"phone", "whatsapp"}:
        number = re.sub(r"[\s()-]", "", value)
        if not re.fullmatch(r"\+?[0-9]{8,16}", number):
            return None
        return "tel:" + number if channel == "phone" else "https://wa.me/" + number.lstrip("+")
    try:
        u = urlsplit(value)
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
            return None
        domains = {
            "facebook": ("facebook.com", "fb.com", "fb.me"),
            "instagram": ("instagram.com",),
            "tiktok": ("tiktok.com",),
            "linkedin": ("linkedin.com",),
        }
        if channel in domains and not any(
            u.hostname.lower() == d or u.hostname.lower().endswith("." + d) for d in domains[channel]
        ):
            return None
        check_url(value, resolve=False)
        return value
    except (ValueError, FetchBlocked):
        return None


def tasks_for(db: Session, lead_id: uuid.UUID) -> list[ManualTask]:
    return list(
        db.scalars(
            select(ManualTask)
            .where(ManualTask.lead_id == lead_id)
            .order_by(ManualTask.created_at.desc(), ManualTask.id.desc())
        )
    )


def task_public(task: ManualTask) -> dict:
    return {
        "id": str(task.id),
        "lead_id": str(task.lead_id),
        "eligibility_id": str(task.eligibility_id),
        "content_id": str(task.content_id),
        "channel": task.channel.value,
        "status": task.status.value,
        "status_reason": task.status_reason,
        "execution_mode": task.execution_mode,
        "preparation_group_id": str(task.preparation_group_id) if task.preparation_group_id else None,
        "assigned_to": task.assigned_to or task.created_by,
        "follow_up_at": task.follow_up_at,
        "sent_at": task.sent_at,
        "source_batch_id": str(task.source_batch_id) if task.source_batch_id else None,
    }


def progress(db: Session, identities: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    result: dict[uuid.UUID, dict] = {
        i: {"status": "not_started", "task_id": None, "draft_id": None} for i in identities
    }
    if not identities:
        return result
    tasks = list(
        db.scalars(select(ManualTask).where(ManualTask.lead_id.in_(identities)).order_by(ManualTask.created_at.desc()))
    )
    drafts = list(
        db.scalars(
            select(Preparation)
            .where(Preparation.lead_id.in_(identities), Preparation.status == "draft")
            .order_by(Preparation.created_at.desc())
        )
    )
    events = list(db.scalars(select(Event).where(Event.lead_id.in_(identities)).order_by(Event.recorded_at.desc())))
    suppressed = set(
        db.scalars(
            select(Suppression.lead_id).where(
                Suppression.lead_id.in_(identities), Suppression.scope == SuppressionScope.lead
            )
        )
    )
    conversation_ids = set(db.scalars(select(Conversation.lead_id).where(Conversation.lead_id.in_(identities))))
    for identity in identities:
        ts = [t for t in tasks if t.lead_id == identity]
        ds = [d for d in drafts if d.lead_id == identity]
        reply = next((e for e in events if e.lead_id == identity and e.kind == EventKind.reply), None)
        sent = next((t for t in ts if t.status in SENT), None)
        active = next((t for t in ts if t.status in service.OPEN_STATUSES), None)
        state = "not_started"
        if identity in suppressed:
            state = "suppressed"
        elif reply and (not sent or reply.recorded_at > (sent.sent_recorded_at or sent.created_at)):
            state = "replied"
        elif active:
            state = "paused" if active.status == TaskStatus.paused else "pending"
        elif sent:
            state = "waiting_reply"
        elif ds:
            state = "preparing"
        elif ts or identity in conversation_ids or any(e.lead_id == identity for e in events):
            state = "recorded"
        selected_task = active or sent
        result[identity] = {
            "status": state,
            "task_id": str(selected_task.id) if selected_task else None,
            "draft_id": str(ds[0].id) if ds else None,
        }
    return result


def context(db: Session, lead: Lead) -> dict:
    from app.modules.sales import admission, contact_ranking

    contacts = list(
        db.scalars(
            select(ChannelEligibility)
            .where(ChannelEligibility.lead_id == lead.id)
            .order_by(ChannelEligibility.created_at)
        )
    )
    pieces = list(
        db.scalars(
            select(ContentPiece)
            .where(ContentPiece.lead_id == lead.id, ContentPiece.kind == ContentKind.message_short)
            .order_by(ContentPiece.version.desc())
            .limit(10)
        )
    )
    analyses = list(
        db.scalars(
            select(MenuAnalysis)
            .join(MenuAsset, MenuAnalysis.asset_id == MenuAsset.id)
            .where(MenuAsset.lead_id == lead.id)
            .order_by(MenuAnalysis.created_at.desc())
        )
    )
    seen: set[uuid.UUID] = set()
    verified = []
    for a in analyses:
        if a.asset_id in seen:
            continue
        seen.add(a.asset_id)
        facts = [i.get("fact", "") for i in (a.issues or []) if i.get("confirmed") is True and not i.get("deleted")]
        if a.review_state == "reviewed" and facts:
            verified.append({"id": str(a.id), "version": a.version, "facts": facts})
    return {
        "lead": {
            "id": str(lead.id),
            "name": lead.name,
            "website": lead.website,
            "address": lead.address,
            "postcode": lead.postcode,
        },
        "contacts": [
            {
                "id": str(e.id),
                "channel": e.channel.value,
                "contact_ref": e.contact_ref,
                "recommendation": contact_ranking.stored(lead, e.channel.value, e.contact_ref),
                "auto_admission": admission.public(db, lead, e),
                "contact_source": e.contact_source,
                "contact_usable": e.contact_usable.value,
                "eligibility": e.eligibility.value,
                "rule_version": e.rule_version,
                "evidence": e.evidence,
                "review_due_at": e.review_due_at,
                "suppressed": bool(service.is_suppressed(db, lead.id, e.contact_ref)),
            }
            for e in contacts
        ],
        "contents": [
            {
                "id": str(p.id),
                "version": p.version,
                "body_text": p.body_text,
                "approved": content_service.approval_valid(db, p)[0],
                "reason": content_service.approval_valid(db, p)[1],
            }
            for p in pieces
        ],
        "analyses": verified,
        "tasks": [task_public(t) for t in tasks_for(db, lead.id)],
        "progress": progress(db, [lead.id])[lead.id],
    }


def assess(db: Session, draft: Preparation) -> list[str]:
    blockers = []
    if draft.assigned_to and not db.scalar(
        select(Operator.id).where(
            Operator.username == draft.assigned_to, Operator.is_active.is_(True), Operator.role.in_(["admin", "member"])
        )
    ):
        blockers.append("负责人已停用或无业务权限，请重新分配")
    elig = db.get(ChannelEligibility, draft.eligibility_id) if draft.eligibility_id else None
    piece = db.get(ContentPiece, draft.content_id) if draft.content_id else None
    if service.is_suppressed(db, draft.lead_id, elig.contact_ref if elig else None):
        blockers.append("客户或联系方式已被抑制，不能触达")
    if not elig:
        blockers.append("尚未选择联系方式")
    else:
        if elig.lead_id != draft.lead_id or elig.channel.value != draft.channel:
            blockers.append("联系方式与客户或渠道不一致")
        if elig.eligibility != Eligibility.allowed:
            from app.modules.sales import admission

            lead = db.get(Lead, draft.lead_id)
            auto = admission.public(db, lead, elig) if lead else None
            blockers.append((auto or {}).get("reason") or "渠道准入尚未允许，请运行 AI 自动准入或补充证据")
        if elig.contact_usable == ContactUsable.invalid:
            blockers.append("联系方式无效")
        if elig.review_due_at and elig.review_due_at < service.now():
            blockers.append("渠道准入复核已到期")
        if draft.execution_mode == "manual" and not manual_target(draft.channel, elig.contact_ref):
            blockers.append("缺少有效邮箱、电话或该平台的 HTTPS 主页链接")
    if not piece:
        blockers.append("尚未准备已审批文案")
    elif piece.lead_id != draft.lead_id or piece.kind != ContentKind.message_short:
        blockers.append("文案与客户不一致或不是短文案")
    else:
        valid, why = content_service.approval_valid(db, piece)
        if not valid:
            blockers.append("文案审批无效：" + (why or "待审批"))
    if elig and piece and (elig.rule_version or "").startswith("ai-admission:"):
        try:
            service.check_can_contact(db, elig, piece)
        except service.SalesError as exc:
            if str(exc) not in blockers:
                blockers.append(str(exc))
    if draft.execution_mode == "social":
        found = db.scalar(
            select(Conversation.id)
            .join(ChannelAccount, Conversation.account_id == ChannelAccount.id)
            .where(
                Conversation.lead_id == draft.lead_id,
                Conversation.eligibility_id == draft.eligibility_id,
                Conversation.last_inbound_at > service.now() - timedelta(hours=24),
                ChannelAccount.platform == draft.channel,
                ChannelAccount.connected.is_(True),
                ChannelAccount.sending_enabled.is_(True),
            )
        )
        if not found:
            blockers.append("没有已授权、准入匹配且处于回复窗口的社媒会话；可改为人工执行")
    return blockers


def draft_public(db: Session, d: Preparation) -> dict:
    lead = lead_or_404(db, d.lead_id)
    return {
        "id": str(d.id),
        "lead_id": str(d.lead_id),
        "channel": d.channel,
        "execution_mode": d.execution_mode,
        "eligibility_id": str(d.eligibility_id) if d.eligibility_id else None,
        "content_id": str(d.content_id) if d.content_id else None,
        "assigned_to": d.assigned_to,
        "follow_up_at": d.follow_up_at,
        "purpose": d.purpose,
        "notes": d.notes,
        "status": d.status,
        "task_id": str(d.task_id) if d.task_id else None,
        "blockers": assess(db, d) if d.status == "draft" else [],
        "context": context(db, lead),
    }


@router.get("/assignees")
def assignees(db: Session = Depends(get_db)):
    return [
        {"username": o.username, "display_name": o.display_name}
        for o in db.scalars(
            select(Operator)
            .where(Operator.is_active.is_(True), Operator.role.in_(["admin", "member"]))
            .order_by(Operator.username)
        )
    ]


@router.get("/leads/{lead_id}")
def lead_context(lead_id: uuid.UUID, db: Session = Depends(get_db)):
    lead = lead_or_404(db, lead_id)
    data = context(db, lead)
    data["drafts"] = [
        draft_public(db, d)
        for d in db.scalars(select(Preparation).where(Preparation.lead_id == lead.id, Preparation.status == "draft"))
    ]
    return data


@router.get("/overview")
def overview(
    batch_key: str | None = None,
    channel: Channel | None = None,
    assigned_to: str | None = None,
    q: str = "",
    preparation_group: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    page, page_size = max(page, 1), min(max(page_size, 1), 100)
    task_leads = select(ManualTask.lead_id)
    event_leads = select(Event.lead_id)
    conversation_leads = select(Conversation.lead_id).join(ChannelAccount, Conversation.account_id == ChannelAccount.id)
    if channel:
        task_leads = task_leads.where(ManualTask.channel == channel)
        event_leads = event_leads.where(Event.channel == channel)
        conversation_leads = conversation_leads.where(ChannelAccount.platform == channel.value)
    if assigned_to:
        task_leads = task_leads.where(func.coalesce(ManualTask.assigned_to, ManualTask.created_by) == assigned_to)
        membership = or_(Lead.id.in_(task_leads))
    else:
        membership = or_(Lead.id.in_(task_leads), Lead.id.in_(event_leads), Lead.id.in_(conversation_leads))
    query = select(Lead).where(membership)
    if batch_key:
        batch = db.scalar(select(Batch).where(Batch.batch_key == batch_key))
        if not batch:
            raise HTTPException(404, "名单不存在")
        query = query.where(Lead.id.in_(select(BatchLead.lead_id).where(BatchLead.batch_id == batch.id)))
    if q.strip():
        query = query.where(or_(Lead.name.ilike(f"%{q.strip()}%"), Lead.postcode.ilike(f"%{q.strip()}%")))
    if preparation_group:
        query = query.where(
            Lead.id.in_(select(ManualTask.lead_id).where(ManualTask.preparation_group_id == preparation_group))
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(db.scalars(query.order_by(Lead.name, Lead.id).offset((page - 1) * page_size).limit(page_size)))
    states = progress(db, [lead.id for lead in rows])
    return {
        "total": total,
        "items": [
            {"id": str(lead.id), "name": lead.name, "postcode": lead.postcode, "progress": states[lead.id]}
            for lead in rows
        ],
    }


@router.post("/prepare")
def prepare(body: PrepareIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    owner(db, body.assigned_to)
    check_mode(body.channel.value, body.execution_mode)
    batch = db.scalar(select(Batch).where(Batch.batch_key == body.batch_key)) if body.batch_key else None
    if body.batch_key and not batch:
        raise HTTPException(404, "名单不存在")
    output = []
    for identity in dict.fromkeys(body.lead_ids):
        try:
            with db.begin_nested():
                lead = lead_or_404(db, identity, lock=True)
                if batch and not db.scalar(
                    select(BatchLead.lead_id).where(BatchLead.batch_id == batch.id, BatchLead.lead_id == identity)
                ):
                    raise HTTPException(422, "客户不属于来源名单")
                if service.is_suppressed(db, identity, None):
                    raise HTTPException(409, "客户已被抑制，不能准备触达")
                prior = next(
                    (
                        t
                        for t in tasks_for(db, identity)
                        if t.channel == body.channel
                        and (t.status in service.OPEN_STATUSES or (body.purpose == "initial" and t.status in SENT))
                    ),
                    None,
                )
                if prior:
                    output.append(
                        {
                            "lead_id": str(identity),
                            "name": lead.name,
                            "existing_task": task_public(prior),
                            "draft": None,
                        }
                    )
                    continue
                d = db.scalar(
                    select(Preparation).where(
                        Preparation.lead_id == identity,
                        Preparation.channel == body.channel.value,
                        Preparation.status == "draft",
                    )
                )
                if d is None:
                    contacts = list(
                        db.scalars(
                            select(ChannelEligibility).where(
                                ChannelEligibility.lead_id == identity, ChannelEligibility.channel == body.channel
                            )
                        )
                    )
                    content = db.scalar(
                        select(ContentPiece)
                        .where(ContentPiece.lead_id == identity, ContentPiece.kind == ContentKind.message_short)
                        .order_by(ContentPiece.version.desc())
                        .limit(1)
                    )
                    from app.modules.sales import contact_ranking

                    suitable = [
                        e
                        for e in contacts
                        if not service.is_suppressed(db, identity, e.contact_ref)
                        and (contact_ranking.stored(lead, e.channel.value, e.contact_ref) or {}).get(
                            "recommendation", "recommended"
                        )
                        == "recommended"
                    ]
                    d = Preparation(
                        lead_id=identity,
                        source_batch_id=batch.id if batch else None,
                        channel=body.channel.value,
                        execution_mode=body.execution_mode,
                        eligibility_id=suitable[0].id if len(suitable) == 1 else None,
                        content_id=content.id if content else None,
                        assigned_to=body.assigned_to or op.username,
                        purpose=body.purpose,
                        status="draft",
                        created_by=op.username,
                    )
                    db.add(d)
                    db.flush()
                    audit.record(
                        db,
                        op,
                        "prepare_communication",
                        "communication_draft",
                        d.id,
                        after={"channel": d.channel, "batch_id": str(batch.id) if batch else None},
                    )
                output.append(
                    {"lead_id": str(identity), "name": lead.name, "draft": draft_public(db, d), "existing_task": None}
                )
            db.commit()
        except HTTPException as exc:
            output.append({"lead_id": str(identity), "error": str(exc.detail), "draft": None})
    return {"items": output}


@router.patch("/drafts/{draft_id}")
def patch_draft(
    draft_id: uuid.UUID, body: DraftPatch, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    d = db.get(Preparation, draft_id)
    if not d:
        raise HTTPException(404, "准备草稿不存在")
    lead_or_404(db, d.lead_id, lock=True)
    db.refresh(d)
    if d.status != "draft":
        raise HTTPException(409, "该草稿已转换任务或结束，请查看现有任务")
    changes = body.model_dump(exclude_unset=True)
    if "assigned_to" in changes:
        owner(db, body.assigned_to)
    if changes.get("execution_mode") is None and "execution_mode" in changes:
        raise HTTPException(422, "执行方式不能为空")
    check_mode(d.channel, body.execution_mode or d.execution_mode)
    if changes.get("eligibility_id"):
        eligibility = db.get(ChannelEligibility, changes["eligibility_id"])
        if eligibility is None or eligibility.lead_id != d.lead_id or eligibility.channel.value != d.channel:
            raise HTTPException(422, "联系方式不属于该客户或渠道")
    if changes.get("content_id"):
        content = db.get(ContentPiece, changes["content_id"])
        if content is None or content.lead_id != d.lead_id or content.kind != ContentKind.message_short:
            raise HTTPException(422, "所选短文案不属于该客户")
    for key, value in changes.items():
        setattr(d, key, value)
    audit.record(
        db,
        op,
        "update_communication_draft",
        "communication_draft",
        d.id,
        after={k: str(v) if v is not None else None for k, v in changes.items()},
    )
    db.commit()
    return draft_public(db, d)


@router.post("/activate")
def activate(body: ActivateIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    output = []
    for identity in dict.fromkeys(body.draft_ids):
        try:
            with db.begin_nested():
                d = db.get(Preparation, identity)
                if d is None:
                    raise HTTPException(404, "准备草稿不存在")
                lead_or_404(db, d.lead_id, lock=True)
                db.refresh(d)
                if d.status == "cancelled":
                    raise HTTPException(409, "准备草稿已结束")
                if d.task_id:
                    output.append({"draft_id": str(d.id), "task_id": str(d.task_id), "reused": True})
                    continue
                existing = next(
                    (
                        t
                        for t in tasks_for(db, d.lead_id)
                        if t.channel.value == d.channel
                        and (t.status in service.OPEN_STATUSES or (d.purpose == "initial" and t.status in SENT))
                    ),
                    None,
                )
                if existing:
                    d.task_id, d.status = existing.id, "converted"
                    output.append({"draft_id": str(d.id), "task_id": str(existing.id), "reused": True})
                else:
                    blockers = assess(db, d)
                    if blockers:
                        raise HTTPException(409, "；".join(blockers))
                    assert d.eligibility_id and d.content_id
                    t = service.create_task(db, d.lead_id, d.eligibility_id, d.content_id, op.username, commit=False)
                    t.preparation_group_id = body.group_id
                    t.source_batch_id, t.assigned_to, t.execution_mode, t.follow_up_at = (
                        d.source_batch_id,
                        d.assigned_to,
                        d.execution_mode,
                        d.follow_up_at,
                    )
                    d.task_id, d.status = t.id, "converted"
                    audit.record(
                        db,
                        op,
                        "activate_communication",
                        "manual_task",
                        t.id,
                        after={"draft_id": str(d.id), "mode": t.execution_mode},
                    )
                    output.append({"draft_id": str(d.id), "task_id": str(t.id), "reused": False})
            db.commit()
        except (HTTPException, service.SalesError) as exc:
            output.append(
                {"draft_id": str(identity), "error": str(exc.detail) if isinstance(exc, HTTPException) else str(exc)}
            )
    return {"items": output}


@router.patch("/tasks/{task_id}")
def patch_task(
    task_id: uuid.UUID, body: TaskPatch, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    t = db.get(ManualTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    lead_or_404(db, t.lead_id, lock=True)
    db.refresh(t, with_for_update=True)
    try:
        service.check_gmail_in_flight(db, t)
    except service.SalesError as exc:
        raise HTTPException(409, str(exc)) from exc
    if t.status not in service.OPEN_STATUSES:
        raise HTTPException(409, "已完成任务不能调整")
    changes = body.model_dump(exclude_unset=True)
    if "assigned_to" in changes:
        owner(db, body.assigned_to)
    if "execution_mode" in changes:
        check_mode(t.channel.value, body.execution_mode or "")
        if body.execution_mode is None:
            raise HTTPException(422, "执行方式不能为空")
    for key, value in changes.items():
        setattr(t, key, value)
    audit.record(
        db,
        op,
        "assign_communication_task",
        "manual_task",
        t.id,
        after={k: str(v) if v is not None else None for k, v in changes.items()},
    )
    db.commit()
    return task_public(t)


@router.post("/tasks/{task_id}/manual-open")
def manual_open(task_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    t = db.get(ManualTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    lead_or_404(db, t.lead_id, lock=True)
    db.refresh(t)
    if t.execution_mode != "manual":
        raise HTTPException(409, "请使用所选接口完整预览发送，或先明确改为人工执行")
    elig = db.get(ChannelEligibility, t.eligibility_id)
    target = manual_target(t.channel.value, elig.contact_ref if elig else None)
    if not target:
        raise HTTPException(409, "没有有效的平台主页或联系入口，请先核对联系方式")
    try:
        service.open_task(db, t, op.username)
    except service.SalesError as exc:
        raise HTTPException(409, str(exc)) from exc
    piece = db.get(ContentPiece, t.content_id)
    return {"task_id": str(t.id), "url": target, "text": piece.body_text if piece else None, "channel": t.channel.value}


@router.get("/activity/{lead_id}")
def activity(lead_id: uuid.UUID, db: Session = Depends(get_db)):
    lead_or_404(db, lead_id)
    items: list[dict] = []
    ts = tasks_for(db, lead_id)
    ids = [t.id for t in ts]
    for t in ts:
        if t.status in SENT:
            items.append(
                {
                    "id": "task:" + str(t.id),
                    "direction": "outbound",
                    "channel": t.channel.value,
                    "at": t.sent_at or t.created_at,
                    "summary": t.notes or "已记录发送",
                    "status": t.status.value,
                    "source": "manual"
                    if t.status == TaskStatus.sent_manual
                    else "gmail"
                    if t.status == TaskStatus.sent_email
                    else "meta",
                    "task_id": str(t.id),
                }
            )
    for e in db.scalars(select(Event).where(Event.lead_id == lead_id)):
        source = "gmail" if e.event_key.startswith("gmail") else "meta" if e.event_key.startswith("meta") else "manual"
        items.append(
            {
                "id": "event:" + str(e.id),
                "direction": "inbound" if e.kind != EventKind.note else "note",
                "channel": e.channel.value if e.channel else None,
                "at": e.occurred_at or e.recorded_at,
                "summary": (e.payload or {}).get("summary") or (e.payload or {}).get("intent") or e.kind.value,
                "status": e.kind.value,
                "source": source,
                "actions": e.actions or [],
            }
        )
    deliveries = []
    records: list[EmailDelivery | OutreachDelivery] = [
        *db.scalars(select(EmailDelivery).where(EmailDelivery.task_id.in_(ids))),
        *db.scalars(select(OutreachDelivery).where(OutreachDelivery.task_id.in_(ids))),
    ]
    for d in records:
        task = next(t for t in ts if t.id == d.task_id)
        deliveries.append(
            {
                "id": str(d.id),
                "task_id": str(d.task_id),
                "channel": task.channel.value,
                "status": d.status,
                "source": "gmail" if isinstance(d, EmailDelivery) else "meta",
                "at": d.sent_at or d.created_at,
                "error": d.last_error,
                "message_id": d.gmail_message_id if isinstance(d, EmailDelivery) else d.platform_message_id,
            }
        )
    conversations = [
        {
            "id": str(c.id),
            "channel": account.platform,
            "at": c.last_inbound_at,
            "summary": c.last_message or "已收到平台消息",
            "source": "meta",
        }
        for c, account in db.execute(
            select(Conversation, ChannelAccount)
            .join(ChannelAccount, Conversation.account_id == ChannelAccount.id)
            .where(Conversation.lead_id == lead_id)
        )
    ]
    return {"timeline": sorted(items, key=lambda x: x["at"]), "deliveries": deliveries, "conversations": conversations}
