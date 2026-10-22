import hashlib
import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import Operator
from app.modules.gmail import client, service
from app.modules.gmail.models import EmailDelivery
from app.modules.sales.service import SalesError

router = APIRouter(prefix="/gmail", tags=["gmail"])
callback_router = APIRouter(tags=["gmail-oauth"])


def error_handler(call):
    try:
        return call()
    except (SalesError, client.GmailServiceError) as error:
        raise HTTPException(409, str(error)) from None


@router.get("/status")
def status():
    try:
        return {"configured": True, **client.call("GET", "/auth/status"), "policy": client.call("GET", "/policy")}
    except client.GmailServiceError as error:
        return {"configured": False, "message": str(error)}


@router.post("/check")
def check():
    return error_handler(lambda: client.call("POST", "/auth/check"))


class ImportIn(BaseModel):
    credentials: dict
    token: dict | None = None


def invalidate_previews(db: Session) -> None:
    db.execute(
        update(EmailDelivery)
        .where(EmailDelivery.status.in_(["preview", "ready", "queued"]))
        .values(
            status="expired",
            approved_by=None,
            approved_at=None,
            last_error="Gmail 连接已更新，请重新预览并确认；任务和发送历史保留",
        )
    )


@router.post("/credentials")
def credentials(body: ImportIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    result = error_handler(lambda: client.call("POST", "/auth/import", body.model_dump()))
    if body.token is not None:
        invalidate_previews(db)
    audit.record(
        db, op, "import_gmail_auth", "gmail_account", "default", after={"token_imported": body.token is not None}
    )
    db.commit()
    return result


@router.post("/configure")
def configure(body: ImportIn):
    return error_handler(lambda: client.call("POST", "/auth/configure", {"credentials": body.credentials}))


class ConnectIn(BaseModel):
    purpose: Literal["send", "replies"] = "send"


def oauth_binding(op: Operator, nonce: str) -> str:
    return hashlib.sha256(f"{op.id}:{op.session_version}:{nonce}".encode()).hexdigest()


@router.post("/connect")
def connect(
    request: Request, response: Response, body: ConnectIn = ConnectIn(), op: Operator = Depends(current_operator)
):
    nonce = secrets.token_urlsafe(32)
    result = error_handler(
        lambda: client.call(
            "POST",
            "/auth/start",
            {
                "purpose": body.purpose,
                "binding": oauth_binding(op, nonce),
            },
        )
    )
    response.set_cookie(
        "beacon_gmail_oauth",
        nonce,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/api/gmail",
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@callback_router.get("/api/gmail/oauth/callback")
def callback(request: Request, db: Session = Depends(get_db)):
    result, reason = "failed", "oauth_failed"
    try:
        op = current_operator(request, db)
        nonce = request.cookies.get("beacon_gmail_oauth")
        if op.role != "admin" or not nonce:
            raise HTTPException(403, "授权会话不匹配")
        client.call(
            "POST",
            "/auth/callback",
            {
                "code": request.query_params.get("code", ""),
                "state": request.query_params.get("state", ""),
                "binding": oauth_binding(op, nonce),
                "error": request.query_params.get("error", "")[:100],
            },
        )
        result = "connected"
        invalidate_previews(db)
        audit.record(db, op, "connect_gmail", "gmail_account", "default")
        db.commit()
    except (client.GmailServiceError, HTTPException) as exc:
        message = str(exc)
        for code in (
            "invalid_grant",
            "invalid_client",
            "redirect_uri_mismatch",
            "access_denied",
            "missing_send_scope",
            "missing_read_scope",
            "account_identity_failed",
            "browser_blocked",
        ):
            if code in message:
                reason = code
                break
    response = RedirectResponse(
        "/settings?gmail=" + result + ("&gmail_error=" + reason if result == "failed" else ""),
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.delete_cookie("beacon_gmail_oauth", path="/api/gmail")
    return response


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    policy = error_handler(lambda: client.call("GET", "/policy"))
    policy.update(sending_enabled=False, queue_enabled=False)
    error_handler(lambda: client.call("PUT", "/policy", policy))
    result = error_handler(lambda: client.call("POST", "/auth/disconnect"))
    invalidate_previews(db)
    audit.record(db, op, "disconnect_gmail", "gmail_account", "default")
    db.commit()
    return result


class PolicyIn(BaseModel):
    sending_enabled: bool = False
    queue_enabled: bool = False
    daily_limit: int = Field(default=0, ge=0, le=100000)


@router.put("/policy")
def policy(body: PolicyIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    result = error_handler(lambda: client.call("PUT", "/policy", body.model_dump()))
    audit.record(db, op, "configure_gmail", "gmail_account", "default", after=result)
    db.commit()
    return result


@router.get("/deliveries")
def deliveries(db: Session = Depends(get_db)):
    return [
        service.public(row)
        for row in db.scalars(select(EmailDelivery).order_by(EmailDelivery.created_at.desc()).limit(500))
    ]


class PreviewIn(BaseModel):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    subject: str = Field(default="", max_length=256)


@router.post("/preview")
def preview(body: PreviewIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    if len(set(body.task_ids)) != len(body.task_ids):
        raise HTTPException(400, "任务不能重复")
    batch_key = uuid.uuid4().hex if len(body.task_ids) > 1 else None
    try:
        rows = [service.preview(db, tid, body.subject, op, batch_key) for tid in sorted(body.task_ids)]
        db.commit()
        return [service.public(row) for row in rows]
    except (SalesError, client.GmailServiceError) as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None


class ApproveIn(BaseModel):
    delivery_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    preview_keys: dict[str, str] = Field(default_factory=dict)
    confirmed: bool
    queued: bool = False


@router.post("/approve")
def approve(body: ApproveIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    if not body.confirmed or len(set(body.delivery_ids)) != len(body.delivery_ids):
        raise HTTPException(400, "需确认最终邮件且记录不能重复")
    if len(body.delivery_ids) > 1 and not body.queued:
        raise HTTPException(400, "多封邮件须使用队列")
    try:
        result = service.approve(db, body.delivery_ids, op, body.queued, body.preview_keys)
        # 单家 ready 也由持久 worker 执行，网页断开不会丢失发送记录。
        return result
    except (SalesError, client.GmailServiceError) as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None


@router.post("/deliveries/{delivery_id}/cancel")
def cancel(delivery_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    row = db.scalar(select(EmailDelivery).where(EmailDelivery.id == delivery_id).with_for_update())
    if not row or row.status not in {"preview", "ready", "queued", "blocked", "expired"}:
        raise HTTPException(409, "已开始发送或结果未知的邮件不能取消")
    row.status = "cancelled"
    row.approval_token = None
    audit.record(db, op, "cancel_gmail", "email_delivery", row.id)
    db.commit()
    return service.public(row)


@router.post("/deliveries/{delivery_id}/reconcile")
def reconcile(delivery_id: uuid.UUID, db: Session = Depends(get_db)):
    db.execute(text(f"SELECT pg_advisory_xact_lock({service.LOCK_KEY})"))
    row = db.scalar(select(EmailDelivery).where(EmailDelivery.id == delivery_id).with_for_update())
    if not row:
        raise HTTPException(404, "发送记录不存在")
    return error_handler(lambda: service.reconcile(db, row))


@router.post("/sync-replies")
def sync(db: Session = Depends(get_db)):
    return error_handler(lambda: service.sync_replies(db))


class TestMailIn(BaseModel):
    to: list[str] = Field(min_length=1, max_length=1)


class TestSendIn(TestMailIn):
    approval_token: str = Field(max_length=256)
    request_key: str = Field(min_length=1, max_length=128)


@router.post("/test/preview")
def test_preview(body: TestMailIn):
    return error_handler(lambda: client.call("POST", "/test/preview", body.model_dump()))


@router.post("/test/send")
def test_send(body: TestSendIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    result = error_handler(lambda: client.call("POST", "/test/send", body.model_dump()))
    audit.record(
        db,
        op,
        "gmail_test_send",
        "gmail_account",
        "default",
        after={"status": result.get("status"), "request_key": body.request_key},
    )
    db.commit()
    return result
