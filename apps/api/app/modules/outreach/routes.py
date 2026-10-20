import base64
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.modules.outreach import client, service
from app.modules.outreach.models import ChannelAccount, Conversation, OutreachDelivery
from app.modules.sales.service import SalesError

router = APIRouter(prefix="/outreach", tags=["outreach"])
public_router = APIRouter(prefix="/api/outreach", tags=["outreach-public"])


@contextmanager
def operation(db: Session):
    db.execute(text(f"SELECT pg_advisory_xact_lock({service.LOCK_KEY})"))
    try:
        yield
    except (SalesError, client.ProviderError, IntegrityError) as exc:
        db.rollback()
        message = "发送账号已存在，请编辑现有账号" if isinstance(exc, IntegrityError) else str(exc)
        raise HTTPException(409, message) from None


def account(db: Session, aid: uuid.UUID) -> ChannelAccount:
    a = db.scalar(select(ChannelAccount).where(ChannelAccount.id == aid).with_for_update())
    if not a:
        raise HTTPException(404, "渠道账号不存在")
    return a


class AppConfig(BaseModel):
    app_id: str = Field(min_length=1, max_length=128, pattern=r"^[0-9]+$")
    app_secret: str = Field(min_length=1, max_length=512, repr=False)
    verify_token: str = Field(min_length=16, max_length=256, repr=False)
    version: str = Field(default="v25.0", pattern=r"^v\d+\.\d+$")
    redirect_uri: str = Field(max_length=512)


class AccountCreate(BaseModel):
    platform: Literal["facebook", "instagram"]
    label: str = Field(min_length=1, max_length=128)
    auth_mode: Literal["facebook_login", "instagram_login"]
    sender_id: str = Field(min_length=1, max_length=128, pattern=r"^[0-9]+$")
    page_id: str | None = Field(default=None, max_length=128, pattern=r"^[0-9]+$")

    @model_validator(mode="after")
    def compatible(self):
        if self.platform == "facebook" and self.auth_mode != "facebook_login":
            raise ValueError("Facebook 需使用 Facebook Login")
        return self


class Credentials(BaseModel):
    token: str = Field(min_length=1, max_length=8192, repr=False)


class Policy(BaseModel):
    sending_enabled: bool
    queue_enabled: bool = False
    daily_limit: int = Field(default=20, ge=1, le=100000)


class Bind(BaseModel):
    eligibility_id: uuid.UUID


class Preview(BaseModel):
    task_id: uuid.UUID
    conversation_id: uuid.UUID


class Approve(BaseModel):
    delivery_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    preview_keys: dict[str, str]
    confirmed: Literal[True]
    queued: bool = False

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.delivery_ids)) != len(self.delivery_ids):
            raise ValueError("不能重复确认同一发送记录")
        if len(self.delivery_ids) > 1 and not self.queued:
            raise ValueError("多条发送须进入队列")
        return self


@router.get("/status")
def status():
    try:
        return {"configured": True, "app": client.call("GET", "/app")}
    except client.ProviderError as exc:
        return {"configured": False, "message": str(exc)}


@router.put("/app")
def app_config(body: AppConfig, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        result = client.call("PUT", "/app", body.model_dump())
        for a in db.scalars(select(ChannelAccount).with_for_update()):
            service.sync_account(a, client.call("GET", f"/accounts/{a.id}"))
        audit.record(db, op, "configure_meta_app", "integration", "meta", after={"app_id": body.app_id})
        db.commit()
        return result


@router.get("/accounts")
def accounts(db: Session = Depends(get_db)):
    return [service.account_public(a) for a in db.scalars(select(ChannelAccount).order_by(ChannelAccount.created_at))]


@router.post("/accounts")
def create(body: AccountCreate, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        a = ChannelAccount(**body.model_dump())
        db.add(a)
        db.flush()
        audit.record(db, op, "create_channel_account", "channel_account", a.id, after={"platform": a.platform})
        db.commit()
        return service.account_public(a)


@router.put("/accounts/{aid}/credentials")
def credentials(
    aid: uuid.UUID, body: Credentials, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    with operation(db):
        a = account(db, aid)
        result = client.call(
            "PUT",
            f"/accounts/{a.id}",
            {
                "platform": a.platform,
                "auth_mode": a.auth_mode,
                "sender_id": a.sender_id,
                "page_id": a.page_id,
                "token": body.token,
            },
        )
        service.sync_account(a, result)
        audit.record(db, op, "configure_channel_credentials", "channel_account", a.id)
        db.commit()
        return service.account_public(a)


@router.post("/accounts/{aid}/check")
def check(aid: uuid.UUID, db: Session = Depends(get_db)):
    with operation(db):
        a = account(db, aid)
        try:
            result = client.call("POST", f"/accounts/{a.id}/check", {})
        except client.ProviderError:
            a.connected, a.sending_enabled, a.queue_enabled = False, False, False
            db.commit()
            raise
        service.sync_account(a, result)
        db.commit()
        return service.account_public(a)


@router.put("/accounts/{aid}/policy")
def policy(aid: uuid.UUID, body: Policy, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        a = account(db, aid)
        result = client.call(
            "PUT",
            f"/accounts/{a.id}/policy",
            {"sending_enabled": body.sending_enabled, "daily_limit": body.daily_limit},
        )
        service.sync_account(a, result)
        a.queue_enabled, a.daily_limit = body.queue_enabled, body.daily_limit
        audit.record(db, op, "channel_sending_policy", "channel_account", a.id, after=body.model_dump())
        db.commit()
        return service.account_public(a)


@router.post("/accounts/{aid}/disconnect")
def disconnect(aid: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        a = account(db, aid)
        service.sync_account(a, client.call("POST", f"/accounts/{a.id}/disconnect", {}))
        audit.record(db, op, "disconnect_channel_account", "channel_account", a.id)
        db.commit()
        return service.account_public(a)


@router.post("/accounts/{aid}/connect")
def connect(aid: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        a = account(db, aid)
        result = client.call(
            "POST",
            f"/accounts/{a.id}/connect",
            {"platform": a.platform, "auth_mode": a.auth_mode, "sender_id": a.sender_id, "page_id": a.page_id},
        )
        a.connected, a.sending_enabled, a.queue_enabled = False, False, False
        audit.record(db, op, "start_channel_oauth", "channel_account", a.id)
        db.commit()
        return result


@router.get("/conversations")
def conversations(db: Session = Depends(get_db)):
    return [
        service.conversation_public(c)
        for c in db.scalars(select(Conversation).order_by(Conversation.last_inbound_at.desc()).limit(500))
    ]


@router.put("/conversations/{cid}/binding")
def bind(cid: uuid.UUID, body: Bind, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        c = db.scalar(select(Conversation).where(Conversation.id == cid).with_for_update())
        if not c:
            raise HTTPException(404, "会话不存在")
        audit.record(
            db,
            op,
            "bind_social_conversation",
            "social_conversation",
            c.id,
            after={"eligibility_id": str(body.eligibility_id)},
        )
        service.bind(db, c, body.eligibility_id)
        return service.conversation_public(c)


@router.post("/preview")
def preview(body: Preview, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        d = service.preview(db, body.task_id, body.conversation_id, op)
        db.commit()
        return service.public(d)


@router.post("/approve")
def approve(body: Approve, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        return service.approve(db, body.delivery_ids, body.preview_keys, body.queued, op)


@router.get("/deliveries")
def deliveries(db: Session = Depends(get_db)):
    return [
        service.public(d)
        for d in db.scalars(select(OutreachDelivery).order_by(OutreachDelivery.created_at.desc()).limit(500))
    ]


@router.post("/deliveries/{did}/cancel")
def cancel(did: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    with operation(db):
        d = db.scalar(select(OutreachDelivery).where(OutreachDelivery.id == did).with_for_update())
        if not d or d.status not in {"preview", "ready", "queued", "blocked", "expired"}:
            raise SalesError("当前发送状态不能取消；未知结果须先对账")
        d.status, d.approval_token = "cancelled", None
        audit.record(db, op, "cancel_social_delivery", "outreach_delivery", d.id)
        db.commit()
        return service.public(d)


@router.post("/deliveries/{did}/reconcile")
def reconcile(did: uuid.UUID, db: Session = Depends(get_db)):
    with operation(db):
        d = db.get(OutreachDelivery, did)
        if not d:
            raise HTTPException(404, "发送记录不存在")
        return service.reconcile(db, d)


@public_router.get("/oauth/callback")
def callback(request: Request, db: Session = Depends(get_db)):
    try:
        result = client.call(
            "POST",
            "/oauth/callback",
            {"state": request.query_params.get("state", ""), "code": request.query_params.get("code", "")},
        )
        a = account(db, uuid.UUID(result["account_id"]))
        service.sync_account(a, result)
        db.commit()
        return RedirectResponse("/settings?meta=connected", status_code=303)
    except (client.ProviderError, ValueError, KeyError, HTTPException):
        db.rollback()
        return RedirectResponse("/settings?meta=failed", status_code=303)


@public_router.get("/webhook")
def webhook_challenge(request: Request):
    if request.query_params.get("hub.mode") != "subscribe":
        raise HTTPException(400, "Webhook 验证模式无效")
    try:
        result = client.call(
            "POST",
            "/webhook/challenge",
            {
                "token": request.query_params.get("hub.verify_token", ""),
                "challenge": request.query_params.get("hub.challenge", ""),
            },
        )
        return PlainTextResponse(result["challenge"])
    except client.ProviderError:
        raise HTTPException(403, "Webhook 验证失败") from None


@public_router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            raise HTTPException(413, "Webhook 请求过大")
    try:
        result = client.call(
            "POST",
            "/webhook/verify",
            {"raw": base64.b64encode(raw).decode(), "signature": request.headers.get("x-hub-signature-256", "")},
        )
    except client.ProviderError as exc:
        if exc.status_code == 409:
            raise HTTPException(403, "Webhook 签名验证失败") from None
        raise HTTPException(503, "Webhook 服务暂不可用，请重试") from None
    count = service.ingest(db, result["events"])
    service.process_events(db)
    return {"received": count}


class ManualReconcile(BaseModel):
    sent_at: AwareDatetime | None = None
    status: Literal["sent", "failed"]
    message_id: str | None = Field(default=None, max_length=256)
    reason: str = Field(min_length=10, max_length=1000)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def evidence(self):
        if self.status == "sent" and (not self.message_id or not self.sent_at):
            raise ValueError("已发送必须提供真实平台消息 ID 与发送时间")
        if self.sent_at and self.sent_at > datetime.now(UTC):
            raise ValueError("实际发送时间不能晚于现在")
        return self


@router.post("/deliveries/{did}/manual-reconcile")
def manual_reconcile(
    did: uuid.UUID, body: ManualReconcile, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    with operation(db):
        db.execute(text(f"select pg_advisory_xact_lock({service.LOCK_KEY})"))
        d = db.scalar(select(OutreachDelivery).where(OutreachDelivery.id == did).with_for_update())
        if not d or d.status != "unknown":
            raise SalesError("只能处理结果未知的记录，请先查询服务结果")
        payload = {
            **body.model_dump(exclude={"sent_at"}),
            "sent_at": body.sent_at.timestamp() if body.sent_at else None,
        }
        result = client.call("POST", f"/requests/{d.request_key}/reconcile", payload)
        audit.record(
            db,
            op,
            "manually_reconcile_social",
            "outreach_delivery",
            d.id,
            after={"status": body.status, "message_id": body.message_id, "evidence": body.reason},
        )
        service.apply_result(db, d, result)
        return service.public(d)
