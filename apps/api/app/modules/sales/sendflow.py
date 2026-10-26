"""One explicit final confirmation; existing delivery workers remain responsible for sending."""

import hashlib
import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator, may_send
from app.core.db import get_db
from app.core.models import Operator
from app.modules.content import service as content
from app.modules.content.models import ApprovalDecision, ContentPiece
from app.modules.gmail import client as gmail_client
from app.modules.gmail import service as gmail
from app.modules.outreach import service as social
from app.modules.outreach.client import ProviderError
from app.modules.outreach.models import ChannelAccount, Conversation
from app.modules.sales import service, workbench
from app.modules.sales.models import ChannelEligibility
from app.modules.sales.preparation import Preparation

router = APIRouter(prefix="/communication/drafts", tags=["communication"])


def load(db: Session, identity: uuid.UUID, lock: bool = False) -> Preparation:
    d = db.get(Preparation, identity)
    if not d:
        raise HTTPException(404, "草稿不存在")
    workbench.lead_or_404(db, d.lead_id, lock=lock)
    db.refresh(d)
    return d


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_id: uuid.UUID
    body_text: str = Field(min_length=1, max_length=20000)
    subject: str = Field(default="", max_length=200)


@router.put("/{identity}/message")
def save_message(
    identity: uuid.UUID, body: MessageIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    d = load(db, identity, True)
    if d.status != "draft" or d.content_id != body.content_id:
        raise HTTPException(409, "消息版本已变化，请刷新后核对；你的编辑尚未覆盖新版本")
    piece = db.get(ContentPiece, d.content_id)
    assert piece is not None
    if piece.body_text != body.body_text or (piece.spec or {}).get("subject", "") != body.subject:
        try:
            revised = content.revise_message(db, piece, body.body_text, op.username, body.subject, commit=False)
        except content.ContentError as exc:
            raise HTTPException(409, str(exc)) from None
        d.content_id = revised.id
        audit.record(db, op, "autosave_message", "communication_draft", d.id, after={"content_id": str(revised.id)})
        db.commit()
    return workbench.draft_public(db, d)


def snapshot(db: Session, d: Preparation) -> dict:
    gaps = workbench.assess(db, d, require_approval=False, confirm_email=True)
    piece = db.get(ContentPiece, d.content_id) if d.content_id else None
    contact = db.get(ChannelEligibility, d.eligibility_id) if d.eligibility_id else None
    latest = content.latest_content(db, d.lead_id, piece.kind) if piece else None
    if piece and latest and latest.id != piece.id:
        gaps.append("已有更新的消息，请选择最新版本")
    if piece and not (piece.body_text or "").strip():
        gaps.append("请先起草消息")
    social_context = None
    sender, conversation_id, recipient = "", None, contact.contact_ref if contact else None
    if d.channel == "email" and piece and not (piece.spec or {}).get("subject", "").strip():
        gaps.append("请填写邮件主题")
    if d.execution_mode == "gmail":
        try:
            status = gmail_client.call("GET", "/auth/status")
            policy = gmail_client.call("GET", "/policy")
            sender = status.get("email", "")
            if not status.get("connected") or not status.get("send_authorized") or not sender:
                gaps.append("请先连接 Gmail 发件邮箱")
            elif not policy.get("sending_enabled"):
                gaps.append("Gmail 发送已暂停，请在设置中开启")
        except gmail_client.GmailServiceError:
            gaps.append("Gmail 服务暂不可用，请稍后重试")
    elif d.execution_mode == "social":
        matches = list(
            db.execute(
                select(Conversation, ChannelAccount)
                .join(ChannelAccount)
                .where(
                    Conversation.lead_id == d.lead_id,
                    Conversation.eligibility_id == d.eligibility_id,
                    ChannelAccount.platform == d.channel,
                    ChannelAccount.connected.is_(True),
                    ChannelAccount.sending_enabled.is_(True),
                    Conversation.last_inbound_at > service.now() - timedelta(hours=24),
                )
            )
        )
        if len(matches) != 1:
            gaps.append("请在沟通页选择唯一的已连接社媒会话")
        else:
            conv, account = matches[0]
            conversation_id, sender, recipient = str(conv.id), account.label, conv.recipient_id
            social_context = {
                "account_id": str(account.id),
                "sender_id": account.sender_id,
                "auth_version": account.auth_version,
                "mapping_version": conv.mapping_version,
            }
    payload = {
        "draft_id": str(d.id),
        "content_id": str(d.content_id),
        "content_hash": piece.content_hash if piece else "",
        "contact_id": str(d.eligibility_id),
        "to": recipient,
        "subject": (piece.spec or {}).get("subject", "") if piece else "",
        "body": piece.body_text if piece else "",
        "mode": d.execution_mode,
        "from": sender,
        "conversation_id": conversation_id,
        "social_context": social_context,
        "assigned_to": d.assigned_to,
        "follow_up_at": d.follow_up_at.isoformat() if d.follow_up_at else None,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"payload": payload, "preview_hash": fingerprint, "issues": list(dict.fromkeys(gaps))}


@router.post("/{identity}/preview")
def preview(identity: uuid.UUID, db: Session = Depends(get_db)):
    d = load(db, identity)
    if d.status != "draft":
        raise HTTPException(409, "已生成沟通记录，请查看发送状态")
    return snapshot(db, d)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_hash: str = Field(min_length=64, max_length=64)
    confirmed: bool


@router.post("/{identity}/confirm")
def confirm(
    identity: uuid.UUID, body: ConfirmIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    if not body.confirmed or not may_send(db, op.username):
        raise HTTPException(403, "请由有权限的用户确认完整消息")
    # Same lock ordering as the Gmail worker, before the per-lead lock.
    initial = load(db, identity)
    initial_mode = initial.execution_mode
    lock_key = social.LOCK_KEY if initial_mode == "social" else gmail.LOCK_KEY
    db.execute(text(f"select pg_advisory_xact_lock({lock_key})"))
    d = load(db, identity, True)
    if d.execution_mode != initial_mode:
        raise HTTPException(409, "执行方式已变化，请重新预览")
    if d.task_id:
        return {
            "task_id": str(d.task_id),
            "status": "existing",
            "message": "已有沟通记录，请查看实际结果，不会重复发送",
        }
    if d.status != "draft":
        raise HTTPException(409, "草稿已结束")
    if any(
        t.channel.value == d.channel
        and (t.status in service.OPEN_STATUSES or (d.purpose == "initial" and t.status in workbench.SENT))
        for t in workbench.tasks_for(db, d.lead_id)
    ):
        raise HTTPException(409, "已有该渠道的沟通任务，请查看记录，避免重复联系")
    check = snapshot(db, d)
    if check["preview_hash"] != body.preview_hash:
        raise HTTPException(409, "收件人、消息或发送账号已变化，请重新预览")
    if check["issues"]:
        raise HTTPException(409, "；".join(check["issues"]))
    piece = db.get(ContentPiece, d.content_id)
    assert piece is not None and d.eligibility_id is not None
    try:
        recipient = db.get(ChannelEligibility, d.eligibility_id)
        note = (
            f"recipient-confirmed:{recipient.id}:{recipient.contact_ref}"
            if recipient and d.channel == "email"
            else "用户确认完整发送预览"
        )
        content.decide(db, piece, ApprovalDecision.approved, op.username, note, commit=False)
        task = service.create_task(db, d.lead_id, d.eligibility_id, piece.id, op.username, commit=False)
        task.assigned_to, task.execution_mode, task.source_batch_id, task.follow_up_at = (
            d.assigned_to,
            d.execution_mode,
            d.source_batch_id,
            d.follow_up_at,
        )
        d.task_id, d.status = task.id, "converted"
        audit.record(
            db,
            op,
            "confirm_message",
            "communication_draft",
            d.id,
            after={"preview_hash": body.preview_hash, "task_id": str(task.id)},
        )
        if d.execution_mode == "gmail":
            delivery = gmail.preview(db, task.id, check["payload"]["subject"], op)
            gmail.approve(db, [delivery.id], op, False, {str(delivery.id): delivery.request_key})
            return {"task_id": str(task.id), "status": "ready", "message": "已提交发送，请在沟通记录查看结果"}
        if d.execution_mode == "social":
            delivery_social = social.preview(db, task.id, uuid.UUID(check["payload"]["conversation_id"]), op)
            social.approve(db, [delivery_social.id], {str(delivery_social.id): delivery_social.request_key}, False, op)
            return {"task_id": str(task.id), "status": "ready", "message": "已提交发送，请在沟通记录查看结果"}
        db.commit()
        return {"task_id": str(task.id), "status": "manual", "message": "已准备好，请打开联系入口并在完成后记录结果"}
    except (content.ContentError, service.SalesError, gmail_client.GmailServiceError, ProviderError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
