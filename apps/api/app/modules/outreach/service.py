"""Approved social execution and account-scoped inbound conversations."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import Operator
from app.modules.content.models import ContentKind, ContentPiece
from app.modules.leads.models import Lead
from app.modules.outreach import client
from app.modules.outreach.models import ChannelAccount, Conversation, ConversationEvent, OutreachDelivery
from app.modules.sales import service as sales
from app.modules.sales.models import ChannelEligibility, ManualTask, TaskStatus

LOCK_KEY = 480012
# Conservative first-release policy: ordinary replies only, no window exceptions or comment replies.
REPLY_WINDOW = timedelta(hours=24)


def now() -> datetime:
    return datetime.now(UTC)


def account_public(a: ChannelAccount) -> dict:
    return {
        "id": str(a.id),
        "platform": a.platform,
        "label": a.label,
        "auth_mode": a.auth_mode,
        "sender_id": a.sender_id,
        "page_id": a.page_id,
        "connected": a.connected,
        "sending_enabled": a.sending_enabled,
        "queue_enabled": a.queue_enabled,
        "daily_limit": a.daily_limit,
        "capabilities": a.capabilities,
    }


def sync_account(a: ChannelAccount, result: dict):
    a.connected = bool(result.get("verified"))
    a.auth_version = result.get("version")
    a.sending_enabled = bool(result.get("sending_enabled"))
    a.capabilities = result.get("capabilities") or []
    if not a.connected:
        a.queue_enabled = False


def conversation_public(c: Conversation) -> dict:
    return {
        "id": str(c.id),
        "account_id": str(c.account_id),
        "recipient_id": c.recipient_id,
        "lead_id": str(c.lead_id) if c.lead_id else None,
        "eligibility_id": str(c.eligibility_id) if c.eligibility_id else None,
        "last_inbound_at": c.last_inbound_at.isoformat(),
        "last_message": c.last_message,
        "window_expires_at": (c.last_inbound_at + REPLY_WINDOW).isoformat(),
        "window_open": c.last_inbound_at + REPLY_WINDOW > now(),
    }


def public(d: OutreachDelivery) -> dict:
    return {
        "id": str(d.id),
        "task_id": str(d.task_id),
        "account_id": str(d.account_id),
        "conversation_id": str(d.conversation_id),
        "status": d.status,
        "payload": d.payload,
        "preview_key": d.request_key,
        "expires_at": d.expires_at.isoformat(),
        "platform_message_id": d.platform_message_id,
        "last_error": d.last_error,
        "sent_at": d.sent_at.isoformat() if d.sent_at else None,
    }


def checked_task(db: Session, task_id: uuid.UUID, c: Conversation, a: ChannelAccount):
    t = db.scalar(
        select(ManualTask).where(ManualTask.id == task_id).with_for_update().execution_options(populate_existing=True)
    )
    if not t or t.channel.value != a.platform or t.status not in (TaskStatus.pending, TaskStatus.opened):
        raise sales.SalesError("请选择该平台的未发送、未暂停任务")
    if c.account_id != a.id or c.lead_id != t.lead_id or c.eligibility_id != t.eligibility_id:
        raise sales.SalesError("会话与任务的门店、准入或发送账号不一致")
    elig = db.scalar(
        select(ChannelEligibility)
        .where(ChannelEligibility.id == t.eligibility_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    content = db.scalar(
        select(ContentPiece)
        .where(ContentPiece.id == t.content_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert elig and content
    sales.check_task_owner(db, t)
    sales.check_can_contact(db, elig, content)
    if content.kind != ContentKind.message_short or content.content_hash != t.content_hash or not content.body_text:
        raise sales.SalesError("须使用当前已审批的短文案")
    if len(content.body_text) > 1000:
        raise sales.SalesError("首期文字回复最多 1000 字符")
    if c.last_inbound_at + REPLY_WINDOW <= now():
        raise sales.SalesError("普通回复窗口已过期，等待对方新消息或改用人工路径")
    if not a.connected or "text_reply" not in a.capabilities:
        raise sales.SalesError("发送账号未连接或不具备文字回复能力")
    return t, elig, content


def preview(db: Session, task_id: uuid.UUID, conversation_id: uuid.UUID, op: Operator) -> OutreachDelivery:
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    c = db.get(Conversation, conversation_id)
    if not c:
        raise sales.SalesError("会话不存在；公开主页 URL 不能直接发送")
    a = db.scalar(select(ChannelAccount).where(ChannelAccount.id == c.account_id).with_for_update())
    assert a
    sync_account(a, client.call("GET", f"/accounts/{a.id}"))
    t, elig, content = checked_task(db, task_id, c, a)
    old = db.scalar(select(OutreachDelivery).where(OutreachDelivery.task_id == task_id).with_for_update())
    if old and old.status not in {"preview", "blocked", "expired", "failed", "cancelled"}:
        raise sales.SalesError("任务已有发送或未知结果，请先处理发送记录")
    body = {
        "account_id": str(a.id),
        "recipient_id": c.recipient_id,
        "text": content.body_text,
        "request_key": uuid.uuid4().hex,
        "window_expires_at": int((c.last_inbound_at + REPLY_WINDOW).timestamp()),
    }
    result = client.call("POST", "/preview", body)
    if any(result.get(k) != v for k, v in body.items()) or result.get("version") != a.auth_version:
        raise sales.SalesError("服务预览与当前账号或内容不一致")
    d = old or OutreachDelivery(task_id=t.id)
    d.account_id, d.conversation_id = a.id, c.id
    d.status, d.payload = (
        "preview",
        {
            **body,
            "platform": a.platform,
            "sender_id": a.sender_id,
            "account_label": a.label,
            "contact_ref": elig.contact_ref,
        },
    )
    d.approval_token = result["approval_token"]
    assert a.auth_version is not None
    d.auth_version, d.mapping_version = a.auth_version, c.mapping_version
    d.request_key = body["request_key"]
    d.expires_at = min(datetime.fromtimestamp(result["expires_at"], UTC), c.last_inbound_at + REPLY_WINDOW)
    d.approved_by, d.approved_at, d.last_error = None, None, None
    db.add(d)
    db.flush()
    audit.record(db, op, "preview_social", "outreach_delivery", d.id, after={"task_id": str(t.id)})
    return d


def recheck(db: Session, d: OutreachDelivery) -> tuple[ManualTask, ChannelAccount]:
    from app.core.auth import may_send

    if d.status in {"ready", "queued", "sending"} and not may_send(db, d.approved_by):
        raise sales.SalesError("发送确认人的账号已停用、待改密或不再具有发送权限，请重新预览确认")
    a = db.scalar(
        select(ChannelAccount)
        .where(ChannelAccount.id == d.account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    c = db.scalar(
        select(Conversation)
        .where(Conversation.id == d.conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not a or not c:
        raise sales.SalesError("账号或会话已移除")
    sync_account(a, client.call("GET", f"/accounts/{a.id}"))
    t, elig, content = checked_task(db, d.task_id, c, a)
    if not a.sending_enabled:
        raise sales.SalesError("该账号发送已暂停")
    if d.auth_version != a.auth_version or d.mapping_version != c.mapping_version:
        raise sales.SalesError("授权或会话关联已变化，请重新预览")
    if d.payload["recipient_id"] != c.recipient_id or d.payload["text"] != content.body_text:
        raise sales.SalesError("收件人或文案已变化，请重新预览")
    if d.payload["contact_ref"] != elig.contact_ref or d.expires_at <= now():
        raise sales.SalesError("联系方式改变或预览已过期，请重新预览")
    return t, a


def approve(db: Session, ids: list[uuid.UUID], keys: dict[str, str], queued: bool, op: Operator) -> list[dict]:
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    rows = []
    for did in sorted(ids):
        d = db.scalar(select(OutreachDelivery).where(OutreachDelivery.id == did).with_for_update())
        if not d or d.status != "preview" or keys.get(str(d.id)) != d.request_key:
            raise sales.SalesError("预览已更新或不能确认，请核对最新内容")
        recheck(db, d)
        rows.append(d)
    for d in rows:
        d.status = "queued" if queued else "ready"
        d.approved_by, d.approved_at = op.username, now()
        audit.record(
            db, op, "approve_social", "outreach_delivery", d.id, after={"request_key": d.request_key, "queued": queued}
        )
    db.commit()
    return [public(d) for d in rows]


def apply_result(db: Session, d: OutreachDelivery, result: dict):
    if result.get("status") == "sent" and result.get("message_id"):
        d.status, d.platform_message_id = "sent", result["message_id"]
        d.sent_at = datetime.fromtimestamp(result.get("sent_at", now().timestamp()), UTC)
        d.last_error, d.approval_token = None, None
        t = db.get(ManualTask, d.task_id)
        assert t
        t.status, t.sent_at, t.sent_recorded_at, t.sent_by = TaskStatus.sent_social, d.sent_at, now(), d.approved_by
        audit.record(db, None, "social_sent", "outreach_delivery", d.id, after={"message_id": d.platform_message_id})
    else:
        d.status = "failed" if result.get("status") == "failed" else "unknown"
        d.last_error = result.get("reason") or "发送结果未知，请先查询或人工对账，不要重复发送"
    db.commit()


def send_one(db: Session, delivery_id: uuid.UUID) -> dict:
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    d = db.scalar(
        select(OutreachDelivery)
        .where(OutreachDelivery.id == delivery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not d or d.status not in {"ready", "queued"}:
        result = public(d) if d else {"status": "not_found"}
        db.commit()
        return result
    t = db.get(ManualTask, d.task_id)
    assert t
    db.scalar(select(Lead).where(Lead.id == t.lead_id).with_for_update())
    try:
        _, a = recheck(db, d)
        if d.status == "queued" and not a.queue_enabled:
            db.commit()
            return public(d)
        count = (
            db.scalar(
                select(func.count())
                .select_from(OutreachDelivery)
                .where(OutreachDelivery.account_id == a.id, OutreachDelivery.claimed_at > now() - timedelta(days=1))
            )
            or 0
        )
        if a.daily_limit and count >= a.daily_limit:
            db.commit()
            return public(d)
    except (sales.SalesError, client.ProviderError) as exc:
        d.status, d.last_error = "blocked", str(exc)
        db.commit()
        return public(d)
    d.status, d.claimed_at = "sending", now()
    db.commit()
    # Persist intent, then acquire lead lock and recheck before the one external submission.
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    db.scalar(select(Lead).where(Lead.id == t.lead_id).with_for_update())
    d = db.scalar(
        select(OutreachDelivery)
        .where(OutreachDelivery.id == delivery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert d
    try:
        _, a = recheck(db, d)
        result = client.call("POST", "/send", {"approval_token": d.approval_token})
    except sales.SalesError as exc:
        d.status, d.last_error = "blocked", str(exc)
        db.commit()
        return public(d)
    except client.ProviderError as exc:
        if exc.status_code in {401, 409, 422}:
            d.status, d.last_error = "blocked", str(exc)
            db.commit()
            return public(d)
        result = {"status": "unknown"}
    apply_result(db, d, result)
    return public(d)


def reconcile(db: Session, d: OutreachDelivery) -> dict:
    if d.status in {"unknown", "sending"}:
        db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
        db.refresh(d, with_for_update=True)
        if d.status in {"unknown", "sending"}:
            apply_result(db, d, client.call("GET", "/requests/" + d.request_key))
    return public(d)


def ingest(db: Session, events: list[dict]) -> int:
    count = 0
    for ev in events:
        a = db.scalar(
            select(ChannelAccount)
            .where(ChannelAccount.platform == ev["platform"], ChannelAccount.sender_id == ev["sender_id"])
            .with_for_update()
        )
        if not a:
            continue
        if db.scalar(
            select(ConversationEvent.id).where(
                ConversationEvent.account_id == a.id, ConversationEvent.message_id == ev["message_id"]
            )
        ):
            continue
        occurred = datetime.fromtimestamp(ev["occurred_at"], UTC)
        c = db.scalar(
            select(Conversation)
            .where(Conversation.account_id == a.id, Conversation.recipient_id == ev["recipient_id"])
            .with_for_update()
        )
        if not c:
            c = Conversation(
                account_id=a.id,
                recipient_id=ev["recipient_id"],
                mapping_version=uuid.uuid4().hex,
                last_inbound_at=occurred,
                last_message=ev["text"],
            )
            db.add(c)
            db.flush()
        elif occurred >= c.last_inbound_at:
            c.last_inbound_at, c.last_message = occurred, ev["text"]
        db.add(
            ConversationEvent(
                account_id=a.id,
                conversation_id=c.id,
                message_id=ev["message_id"],
                occurred_at=occurred,
                processed=False,
            )
        )
        db.flush()
        count += 1
    db.commit()
    return count


def process_events(db: Session):
    # Serialize worker/webhook processing; sales event keys make commit interruption idempotent.
    db.execute(text("select pg_advisory_xact_lock(480013)"))
    rows = list(
        db.scalars(
            select(ConversationEvent)
            .join(Conversation, Conversation.id == ConversationEvent.conversation_id)
            .where(ConversationEvent.processed.is_(False), Conversation.lead_id.is_not(None))
            .order_by(ConversationEvent.occurred_at)
            .limit(100)
        )
    )
    for event in rows:
        c = db.get(Conversation, event.conversation_id)
        assert c
        if c.lead_id:
            a = db.get(ChannelAccount, c.account_id)
            assert a
            event_key = "social:" + hashlib.sha256(f"{a.id}:{event.message_id}".encode()).hexdigest()
            sales.record_event(
                db,
                c.lead_id,
                {
                    "event_key": event_key,
                    "kind": "reply",
                    "channel": a.platform,
                    "occurred_at": event.occurred_at,
                    "payload": {
                        "source": "meta",
                        "platform_message_id": event.message_id,
                        "conversation_id": str(c.id),
                        "summary": "社媒会话收到回复，等待负责人处理",
                    },
                },
                "social-webhook",
            )
            event.processed = True
            db.commit()
    db.commit()


def bind(db: Session, c: Conversation, eligibility_id: uuid.UUID):
    elig = db.get(ChannelEligibility, eligibility_id)
    a = db.get(ChannelAccount, c.account_id)
    if not elig or not a or elig.channel.value != a.platform:
        raise sales.SalesError("只能关联该平台的准入记录")
    if c.lead_id and (c.lead_id != elig.lead_id or c.eligibility_id != elig.id):
        raise sales.SalesError("会话已有明确关联，不能直接换到其他门店或联系方式")
    c.lead_id, c.eligibility_id, c.mapping_version = elig.lead_id, elig.id, uuid.uuid4().hex
    db.commit()
    process_events(db)


def tick(db: Session):
    for conversation in db.scalars(
        select(Conversation).where(
            Conversation.last_inbound_at < now() - timedelta(days=30), Conversation.last_message.is_not(None)
        )
    ):
        conversation.last_message = None
    db.commit()
    process_events(db)
    for d in db.scalars(
        select(OutreachDelivery).where(
            OutreachDelivery.status == "sending", OutreachDelivery.claimed_at < now() - timedelta(minutes=5)
        )
    ):
        reconcile(db, d)
    ids = list(
        db.scalars(
            select(OutreachDelivery.id)
            .where(OutreachDelivery.status.in_(["ready", "queued"]))
            .order_by(OutreachDelivery.approved_at)
            .limit(20)
        )
    )
    for did in ids:
        result = send_one(db, did)
        if result.get("status") in {"sent", "failed", "unknown"}:
            break
    db.commit()
