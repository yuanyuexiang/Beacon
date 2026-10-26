"""Durable approved email queue. Unknown external results are never blindly retried."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import Operator
from app.modules.content.models import ContentKind, ContentPiece
from app.modules.gmail import client
from app.modules.gmail.models import EmailDelivery
from app.modules.leads.models import Lead
from app.modules.sales import service as sales
from app.modules.sales.models import Channel, ChannelEligibility, ManualTask, TaskStatus

LOCK_KEY = 470012


def now():
    return datetime.now(UTC)


def public(delivery: EmailDelivery) -> dict:
    return {
        "id": str(delivery.id),
        "task_id": str(delivery.task_id),
        "status": delivery.status,
        "payload": delivery.payload,
        "preview_key": delivery.request_key,
        "expires_at": delivery.expires_at.isoformat(),
        "approved_by": delivery.approved_by,
        "batch_key": delivery.batch_key,
        "gmail_message_id": delivery.gmail_message_id,
        "gmail_thread_id": delivery.gmail_thread_id,
        "sent_at": delivery.sent_at.isoformat() if delivery.sent_at else None,
        "last_error": delivery.last_error,
        "checked_at": delivery.checked_at.isoformat() if delivery.checked_at else None,
    }


def checked_task(db: Session, task_id: uuid.UUID) -> tuple[ManualTask, ChannelEligibility, ContentPiece]:
    task = db.scalar(
        select(ManualTask).where(ManualTask.id == task_id).with_for_update().execution_options(populate_existing=True)
    )
    if not task or task.channel != Channel.email:
        raise sales.SalesError("只支持已有邮箱渠道任务")
    if task.status not in (TaskStatus.pending, TaskStatus.opened):
        raise sales.SalesError("任务已暂停、取消或发送，不能执行 Gmail")
    elig = db.scalar(
        select(ChannelEligibility)
        .where(ChannelEligibility.id == task.eligibility_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    content = db.scalar(
        select(ContentPiece)
        .where(ContentPiece.id == task.content_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert elig is not None and content is not None
    sales.check_task_owner(db, task)
    sales.check_can_contact(db, elig, content)
    if content.kind != ContentKind.message_short or not content.body_text or content.content_hash != task.content_hash:
        raise sales.SalesError("任务须使用当前已审批的邮件文案，内容版本不能改变")
    if not elig.contact_ref or "@" not in elig.contact_ref:
        raise sales.SalesError("任务未关联有效邮箱")
    return task, elig, content


def preview(db: Session, task_id: uuid.UUID, subject: str, op: Operator, batch_key: str | None = None) -> EmailDelivery:
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    task, elig, content = checked_task(db, task_id)
    delivery = db.scalar(select(EmailDelivery).where(EmailDelivery.task_id == task_id).with_for_update())
    if delivery and delivery.status not in {"preview", "failed", "blocked", "expired", "cancelled"}:
        raise sales.SalesError("已有排队、发送或结果未知的邮件；请先查询发送记录")
    approved_subject = (content.spec or {}).get("subject", "")
    if approved_subject and subject.strip() and subject.strip() != approved_subject:
        raise sales.SalesError("主题与已确认消息不一致，请在客户消息中修改并重新确认")
    subject = approved_subject or subject.strip()
    if not subject:
        raise sales.SalesError("请填写邮件主题")
    payload = {"to": [elig.contact_ref], "subject": subject.strip(), "body": content.body_text}
    result = client.call("POST", "/preview", payload)
    if (
        result.get("to") != payload["to"]
        or result.get("body") != payload["body"]
        or result.get("subject") != payload["subject"]
    ):
        raise sales.SalesError("服务预览与任务内容不一致")
    if not delivery:
        delivery = EmailDelivery(task_id=task.id)
        db.add(delivery)
    delivery.status = "preview"
    delivery.payload = payload
    delivery.approval_token = result["approval_token"]
    delivery.expires_at = datetime.fromtimestamp(result["expires_at"], UTC)
    delivery.request_key = uuid.uuid4().hex
    delivery.batch_key = batch_key
    delivery.approved_by = None
    delivery.approved_at = None
    delivery.last_error = None
    db.flush()
    audit.record(db, op, "preview_gmail", "email_delivery", delivery.id, after={"task_id": str(task.id)})
    return delivery


def recheck(db: Session, delivery: EmailDelivery) -> ManualTask:
    from app.core.auth import may_send

    if delivery.status in {"ready", "queued", "sending"} and not may_send(db, delivery.approved_by):
        raise sales.SalesError("发送确认人的账号已停用、待改密或不再具有发送权限，请重新预览确认")
    task, elig, content = checked_task(db, delivery.task_id)
    if delivery.payload["to"] != [elig.contact_ref] or delivery.payload["body"] != content.body_text:
        raise sales.SalesError("邮箱或已审批内容改变，请重新预览确认")
    if delivery.expires_at <= now():
        raise sales.SalesError("最终邮件预览已过期，请重新预览确认")
    return task


def approve(db: Session, ids: list[uuid.UUID], op: Operator, queued: bool, preview_keys: dict[str, str]) -> list[dict]:
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    rows = []
    for did in sorted(ids):
        delivery = db.scalar(select(EmailDelivery).where(EmailDelivery.id == did).with_for_update())
        if not delivery or delivery.status != "preview":
            raise sales.SalesError("只能确认尚未发送的完整预览")
        if preview_keys.get(str(delivery.id)) != delivery.request_key:
            raise sales.SalesError("预览已被更新，请查看最新最终内容后重新确认")
        recheck(db, delivery)
        rows.append(delivery)
    for delivery in rows:
        delivery.payload = {**delivery.payload, "_dispatch_v2": True}
        delivery.status = "queued" if queued else "ready"
        delivery.approved_by, delivery.approved_at = op.username, now()
        audit.record(
            db,
            op,
            "approve_gmail_send",
            "email_delivery",
            delivery.id,
            after={"mode": "queue" if queued else "single", "request_key": delivery.request_key},
        )
    db.commit()
    return [public(row) for row in rows]


def apply_result(db: Session, delivery: EmailDelivery, result: dict) -> None:
    status = result.get("status", "unknown")
    delivery.status = status if status in {"sent", "failed"} else "unknown"
    delivery.attempt_id = result.get("attempt_id")
    if delivery.status == "sent" and result.get("id"):
        delivery.gmail_message_id = result["id"]
        delivery.gmail_thread_id = result.get("threadId")
        delivery.sent_at = datetime.fromtimestamp(result.get("sent_at", now().timestamp()), UTC)
        delivery.last_error = None
        task = db.get(ManualTask, delivery.task_id)
        assert task is not None
        task.status = TaskStatus.sent_email
        task.sent_at, task.sent_recorded_at, task.sent_by = delivery.sent_at, now(), delivery.approved_by
        audit.record(
            db,
            None,
            "gmail_sent",
            "email_delivery",
            delivery.id,
            after={"message_id": delivery.gmail_message_id, "thread_id": delivery.gmail_thread_id},
        )
    else:
        if delivery.status == "sent":
            delivery.status = "unknown"
        delivery.last_error = result.get("reason") or (
            "发送失败，可重新预览" if delivery.status == "failed" else "发送结果未知；查询发送结果，确认前不能重发"
        )
    if delivery.status == "sent":
        delivery.approval_token = None
    db.commit()


def send_one(db: Session, delivery_id: uuid.UUID) -> dict:
    # 单家和队列共用全局锁，发送/拒收处理共同锁定门店，避免并发重复执行。
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    delivery = db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.id == delivery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not delivery or delivery.status not in {"ready", "queued"}:
        result = public(delivery) if delivery else {"status": "not_found"}
        db.commit()
        return result
    if not delivery.payload.get("_dispatch_v2"):
        delivery.status = "queued_paused"
        delivery.last_error = "历史暂停邮件；点击继续发送后执行"
        result = public(delivery)
        db.commit()
        return result
    task = db.get(ManualTask, delivery.task_id)
    assert task is not None
    db.scalar(select(Lead).where(Lead.id == task.lead_id).with_for_update())
    try:
        recheck(db, delivery)
    except sales.SalesError as error:
        delivery.status, delivery.last_error = "blocked", str(error)
        db.commit()
        return public(delivery)
    delivery.status, delivery.claimed_at = "sending", now()
    # 持久化发送意图；进程中断后仅查询，不重新发送。
    db.commit()
    db.execute(text(f"select pg_advisory_xact_lock({LOCK_KEY})"))
    db.scalar(select(Lead).where(Lead.id == task.lead_id).with_for_update())
    delivery = db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.id == delivery_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert delivery is not None
    try:
        recheck(db, delivery)
    except sales.SalesError as error:
        delivery.status, delivery.last_error = "blocked", str(error)
        db.commit()
        return public(delivery)
    try:
        result = client.call(
            "POST",
            "/send",
            {
                **{k: v for k, v in delivery.payload.items() if not k.startswith("_")},
                "approval_token": delivery.approval_token,
                "request_key": delivery.request_key,
            },
        )
    except client.GmailServiceError:
        # 可能远端已经接收；不将网络错误当成未发送。
        result = {"status": "unknown"}
    apply_result(db, delivery, result)
    return public(delivery)


def reconcile(db: Session, delivery: EmailDelivery) -> dict:
    if delivery.status in {"sending", "unknown"}:
        result = client.call("GET", "/requests/" + delivery.request_key)
        apply_result(db, delivery, result)
    return public(delivery)


def sync_replies(db: Session) -> dict:
    deliveries = list(
        db.scalars(
            select(EmailDelivery)
            .where(EmailDelivery.status == "sent", EmailDelivery.gmail_message_id.is_not(None))
            .order_by(EmailDelivery.checked_at.asc().nullsfirst())
            .limit(20)
        )
    )
    if not deliveries:
        return {"checked": 0, "replies": 0}
    result = client.call("POST", "/replies", {"message_ids": [row.gmail_message_id for row in deliveries]})
    new = 0
    by_message = {row.gmail_message_id: row for row in deliveries}
    for thread in result.get("results", []):
        delivery = by_message.get(thread["sent_message_id"])
        if not delivery:
            continue
        task = db.get(ManualTask, delivery.task_id)
        assert task is not None
        for reply in thread.get("replies", []):
            if not reply.get("id"):
                continue
            _, created = sales.record_event(
                db,
                task.lead_id,
                {
                    "event_key": "gmail:" + reply["id"],
                    "kind": "reply",
                    "channel": "email",
                    "occurred_at": datetime.fromtimestamp(int(reply["internalDate"]) / 1000, UTC)
                    if reply.get("internalDate")
                    else None,
                    "payload": {
                        "source": "gmail",
                        "gmail_message_id": reply["id"],
                        "gmail_thread_id": thread["threadId"],
                        "from": reply.get("from"),
                        "subject": reply.get("subject"),
                        "date": reply.get("date"),
                        "summary": "Gmail 线程收到回复（仅邮件头，未判断意向）",
                    },
                },
                "gmail-sync",
            )
            new += int(created)
        delivery.checked_at = now()
    db.commit()
    return {"checked": len(deliveries), "replies": new}


def tick(db: Session) -> None:
    # 旧 sending 状态先对账；结果未知不会进入待发送队列。
    for row in db.scalars(
        select(EmailDelivery).where(
            EmailDelivery.status == "sending", EmailDelivery.claimed_at < now() - timedelta(minutes=5)
        )
    ):
        reconcile(db, row)
    ready = db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.status.in_(["ready", "queued"]))
        .order_by(EmailDelivery.approved_at)
        .limit(1)
    )
    if ready:
        send_one(db, ready.id)
    db.commit()
