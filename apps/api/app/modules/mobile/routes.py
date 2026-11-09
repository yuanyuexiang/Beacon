"""Authenticated operators confirm jobs; paired devices can only execute their own frozen jobs."""

import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.auth import current_operator, may_send
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import Operator
from app.modules.content.models import ContentPiece
from app.modules.leads.models import Lead
from app.modules.mobile.assistance import PageIn
from app.modules.mobile.assistance import assist as assist_page
from app.modules.mobile.channels import PLATFORMS, destination
from app.modules.mobile.models import Device, Execution, Pairing
from app.modules.mobile.navigation import Screen, advise
from app.modules.sales import service
from app.modules.sales.models import ChannelEligibility, ManualTask, TaskStatus

router = APIRouter(prefix="/mobile", tags=["mobile"])
worker_router = APIRouter(prefix="/api/mobile/device", tags=["mobile-device"])


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def lock(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(1801105)"))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairIn(Input):
    code: str = Field(min_length=6, max_length=128, repr=False)
    label: str = Field(min_length=1, max_length=128)


class Heartbeat(Input):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    account: str = Field(default="", max_length=64)
    accounts: dict[str, str] = Field(default_factory=dict)
    installed: list[str] = Field(default_factory=list, max_length=10)
    ready: bool = False
    accessibility: bool = False
    unlocked: bool | None = None
    app_version: str = Field(max_length=64)
    protocol: Literal[1, 2] = 1


class QueueIn(Input):
    device_id: uuid.UUID
    preview_hash: str = Field(min_length=64, max_length=64)
    action: Literal["direct_message", "message_request", "connection_request", "inmail", "contact_discovery"] = (
        "direct_message"
    )


class AttemptIn(Input):
    lease: str = Field(min_length=16, max_length=128, repr=False)
    attempt: int = Field(ge=1)


class ResultIn(AttemptIn):
    status: Literal["sent", "failed", "unknown", "needs_action", "request_submitted", "unavailable"]
    detail: str = Field(default="", max_length=1000)


def operator_device(db: Session, identity: uuid.UUID, op: Operator) -> Device:
    row = db.get(Device, identity)
    if not row or row.owner != op.username:
        raise HTTPException(404, "手机不存在或未绑定当前用户")
    return row


def device_auth(request: Request, db: Session = Depends(get_db)) -> Device:
    lock(db)
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
    row = db.scalar(select(Device).where(Device.token_hash == digest(token))) if token else None
    if not row:
        raise HTTPException(401, "设备凭据无效，请重新配对")
    # Revoked devices may only settle an existing attempt, never get a new payload.
    settling = request.url.path.endswith("/result")
    if row.status == "revoked" and not settling:
        raise HTTPException(401, "设备已解除绑定")
    if not settling and not may_send(db, row.owner):
        raise HTTPException(403, "绑定用户已停用或无执行权限")
    return row


def public_device(d: Device) -> dict:
    return {
        "id": str(d.id),
        "label": d.label,
        "owner": d.owner,
        "status": d.status,
        "account": d.account,
        "last_seen_at": d.last_seen_at,
        "online": bool(
            d.status != "revoked"
            and not (d.capabilities or {}).get("connection_paused")
            and d.last_seen_at
            and d.last_seen_at > service.now() - timedelta(seconds=90)
        ),
        "capabilities": d.capabilities,
    }


def public_job(j: Execution) -> dict:
    return {
        "id": str(j.id),
        "task_id": str(j.task_id),
        "device_id": str(j.device_id),
        "status": j.status,
        "snapshot": j.snapshot,
        "attempt": j.attempt,
        "created_at": j.created_at,
        "finished_at": j.finished_at,
        "error": j.error,
        "navigation_history": (j.result or {}).get("navigation_history", []),
    }


@router.post("/pairing")
def create_pairing(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    lock(db)
    # Short numeric codes for the current testing phase; device tokens remain high entropy.
    code = f"{secrets.randbelow(1_000_000):06d}"
    while db.scalar(select(Pairing.id).where(Pairing.code_hash == digest(code))):
        code = f"{secrets.randbelow(1_000_000):06d}"
    # Refresh replaces unused codes for this operator only.
    for previous in db.scalars(select(Pairing).where(Pairing.owner == op.username, Pairing.used_at.is_(None))):
        previous.expires_at = service.now()
    expiry = service.now() + timedelta(minutes=5)
    db.add(Pairing(owner=op.username, code_hash=digest(code), expires_at=expiry))
    db.commit()
    return {"code": code, "expires_at": expiry, "owner": op.username, "server": get_settings().mobile_public_url}


@worker_router.post("/pair")
def pair(body: PairIn, db: Session = Depends(get_db)):
    lock(db)
    row = db.scalar(select(Pairing).where(Pairing.code_hash == digest(body.code)).with_for_update())
    if not row or row.used_at or row.expires_at <= service.now() or not may_send(db, row.owner):
        raise HTTPException(409, "配对码已失效，请在网页重新生成")
    token = secrets.token_urlsafe(48)
    d = Device(owner=row.owner, label=body.label, token_hash=digest(token), status="paired")
    db.add(d)
    row.used_at = service.now()
    db.commit()
    return {"device_id": str(d.id), "token": token, "protocol": 1, "owner": row.owner}


@router.get("/channels")
def channel_catalog(op: Operator = Depends(current_operator)):
    return PLATFORMS


@router.get("/devices")
def devices(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    return [
        public_device(d)
        for d in db.scalars(select(Device).where(Device.owner == op.username).order_by(Device.created_at.desc()))
        if not (d.capabilities or {}).get("list_hidden")
    ]


@router.post("/devices/{identity}/revoke")
def revoke(identity: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    lock(db)
    d = operator_device(db, identity, op)
    revoke_device(db, d)
    db.commit()
    return public_device(d)


def revoke_device(db: Session, d: Device) -> None:
    d.status = "revoked"
    for j in db.scalars(
        select(Execution).where(Execution.device_id == d.id, Execution.status.in_(["queued", "claimed", "sending"]))
    ):
        j.status = "unknown" if j.started_at else "cancelled"
        j.error = "设备已解除绑定" if not j.started_at else "发送时设备解除绑定，请核对实际结果"


@router.delete("/devices/{identity}")
def remove_device(identity: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    lock(db)
    d = operator_device(db, identity, op)
    revoke_device(db, d)
    d.capabilities = {**(d.capabilities or {}), "list_hidden": True}
    db.commit()
    return {"removed": True}


@worker_router.post("/disconnect")
def disconnect_device(d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    d.status = "paired"
    d.capabilities = {**(d.capabilities or {}), "ready": False, "connection_paused": True}
    db.commit()
    return {"disconnected": True}


@worker_router.post("/unbind")
def unbind_device(d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    revoke_device(db, d)
    db.commit()
    return {"unbound": True}


@worker_router.post("/heartbeat")
def heartbeat(body: Heartbeat, d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    if body.protocol == 1 and not re.fullmatch(r"\+[1-9][0-9]{6,14}", body.account):
        raise HTTPException(422, "请填写本方 WhatsApp 国际号码")
    accounts = body.accounts if body.protocol == 2 else {"whatsapp": body.account}
    if any(p not in PLATFORMS or not v.strip() or len(v) > 256 for p, v in accounts.items()):
        raise HTTPException(422, "请填写有效的平台账号")
    if "whatsapp" in accounts:
        try:
            destination("whatsapp", accounts["whatsapp"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    # Changing any sender invalidates not-yet-started confirmations.
    old_accounts = (d.capabilities or {}).get("accounts", {"whatsapp": d.account})
    if d.account and d.account != body.account or body.protocol == 2 and old_accounts != accounts:
        for j in db.scalars(
            select(Execution).where(Execution.device_id == d.id, Execution.status.in_(["queued", "claimed"]))
        ):
            j.status, j.error = "cancelled", "本方账号改变，请重新确认"
    if body.label and body.label.strip():
        d.label = body.label.strip()
    d.account, d.last_seen_at = body.account, service.now()
    d.capabilities = {**body.model_dump(exclude={"account", "label"}), "accounts": accounts}
    d.status = "ready" if body.ready and body.accessibility else "paired"
    db.commit()
    return device_state(d, db)


@worker_router.post("/state")
def device_state(d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    count = db.scalar(
        select(func.count()).select_from(Execution).where(Execution.device_id == d.id, Execution.status == "queued")
    )
    return {
        "status": d.status,
        "account": d.account,
        "accounts": (d.capabilities or {}).get("accounts", {"whatsapp": d.account} if d.account else {}),
        "label": d.label,
        "pending_count": count or 0,
    }


def task_for(db: Session, identity: uuid.UUID) -> ManualTask:
    t = db.get(ManualTask, identity)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


def _check_device_access(
    db: Session, lead_id: uuid.UUID, d: Device, assigned_to: str | None, confirmed_by: str
) -> None:
    if not may_send(db, confirmed_by) or not may_send(db, d.owner):
        raise HTTPException(409, "手机绑定人或确认人的账号已停用或无执行权限")
    owner = db.scalar(select(Operator).where(Operator.username == d.owner))
    if owner and owner.role in {"admin", "director"}:
        service.check_member_owner(db, lead_id, confirmed_by)
        return
    if assigned_to != d.owner:
        raise HTTPException(409, "请选择任务负责人绑定的手机，或由管理员使用自己的手机代办")
    service.check_member_owner(db, lead_id, d.owner)
    service.check_member_owner(db, lead_id, confirmed_by)


def check_device_access(db: Session, lead_id: uuid.UUID, d: Device, assigned_to: str | None, confirmed_by: str) -> None:
    try:
        _check_device_access(db, lead_id, d, assigned_to, confirmed_by)
    except service.SalesError as exc:
        raise HTTPException(409, str(exc)) from None


def checks(db: Session, t: ManualTask, d: Device, confirmed_by: str, action: str = "direct_message") -> dict:
    db.scalar(select(Lead).where(Lead.id == t.lead_id).with_for_update().execution_options(populate_existing=True))
    db.refresh(t)

    if t.status not in {TaskStatus.pending, TaskStatus.opened}:
        raise HTTPException(409, "任务已暂停、结束或发送，请刷新")
    check_device_access(db, t.lead_id, d, t.assigned_to or t.created_by, confirmed_by)
    service.check_task_owner(db, t)
    e, p = db.get(ChannelEligibility, t.eligibility_id), db.get(ContentPiece, t.content_id)
    assert e and p
    service.check_can_contact(db, e, p)
    if t.content_hash != p.content_hash:
        raise HTTPException(409, "消息已变化，请重新确认")
    return destination_payload(
        db, t.lead_id, t.channel.value, e.contact_ref, p, d, t.assigned_to or t.created_by, confirmed_by, action
    )


def destination_payload(
    db: Session,
    lead_id: uuid.UUID,
    channel: str,
    contact_ref: str | None,
    p: ContentPiece,
    d: Device,
    assigned_to: str | None,
    confirmed_by: str,
    action: str = "direct_message",
) -> dict:
    check_device_access(db, lead_id, d, assigned_to, confirmed_by)
    try:
        platform, target = destination(channel, contact_ref)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if action not in PLATFORMS[platform]["actions"]:
        raise HTTPException(409, "该渠道不支持此联系动作")
    capabilities = d.capabilities or {}
    modern = capabilities.get("protocol", 1) >= 2
    if platform != "whatsapp" and not modern:
        raise HTTPException(409, "请更新手机助手并配置此平台账号")
    sender = (capabilities.get("accounts") or {}).get(platform) if modern else d.account
    current_app = modern and not sender
    if current_app:
        sender = str(PLATFORMS[platform]["label"]) + " 当前登录账号"
    if modern and platform not in capabilities.get("installed", []):
        raise HTTPException(409, f"手机尚未检测到 {PLATFORMS[platform]['label']}，请安装后返回手机助手刷新运行检查")
    if not sender:
        raise HTTPException(409, "旧版手机助手需要记录本方号码，请更新手机助手或填写本方号码")
    if d.status == "revoked":
        raise HTTPException(409, "手机已解除绑定，请重新配对")
    if (
        capabilities.get("connection_paused")
        or not d.last_seen_at
        or d.last_seen_at < service.now() - timedelta(seconds=90)
    ):
        raise HTTPException(409, "手机未连接平台，请在手机助手点击重新连接")
    if not capabilities.get("accessibility"):
        raise HTTPException(409, "请在手机系统设置开启“Beacon 手机执行”无障碍服务，再返回 App 点击“检查并准备执行”")
    if d.status != "ready":
        raise HTTPException(409, "手机已连接，请在手机助手任务页点击“检查并准备执行”")
    lead = db.get(Lead, lead_id)
    return {
        "target": target,
        "sender": sender,
        "body": p.body_text,
        "content_hash": p.content_hash,
        "lead_name": lead.name if lead else "",
        "owner": d.owner,
        "channel": platform,
        "protocol": 2 if modern else 1,
        **({"action": action} if modern else {}),
        **({"sender_mode": "current_app"} if current_app else {}),
    }


def checked(db: Session, t: ManualTask, d: Device, by: str, action: str = "direct_message") -> dict:
    try:
        return checks(db, t, d, by, action)
    except service.SalesError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/tasks/{identity}")
def task_state(identity: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    task_for(db, identity)
    j = db.scalar(select(Execution).where(Execution.task_id == identity))
    return public_job(j) if j else None


@router.post("/tasks/{identity}/preview")
def preview(
    identity: uuid.UUID, body: QueueIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    lock(db)
    t, d = task_for(db, identity), operator_device(db, body.device_id, op)
    payload = checked(db, t, d, op.username, body.action)
    key = digest(json.dumps({"task": str(t.id), "device": str(d.id), **payload}, sort_keys=True))
    return {"payload": payload, "preview_hash": key}


@router.post("/tasks/{identity}/confirm")
def confirm(
    identity: uuid.UUID, body: QueueIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    lock(db)
    t, d = task_for(db, identity), operator_device(db, body.device_id, op)
    existing = db.scalar(select(Execution).where(Execution.task_id == identity))
    if existing:
        return public_job(existing)
    view = preview(identity, body, db, op)
    if not hmac.compare_digest(view["preview_hash"], body.preview_hash):
        raise HTTPException(409, "预览已变化，请重新预览")
    j = Execution(
        task_id=t.id,
        lead_id=t.lead_id,
        device_id=d.id,
        confirmed_by=op.username,
        snapshot=view["payload"],
        status="queued",
    )
    db.add(j)
    t.execution_mode = "mobile"
    db.commit()
    return public_job(j)


@router.post("/tasks/{identity}/cancel")
def cancel(identity: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    lock(db)
    task_for(db, identity)
    j = db.scalar(select(Execution).where(Execution.task_id == identity))
    if not j:
        raise HTTPException(404, "手机执行记录不存在")
    if j.status in {"queued", "claimed"}:
        j.status = "cancelled"
    elif j.status == "sending":
        j.status, j.error = "unknown", "已请求停止；发送动作可能已发生，请核对"
    db.commit()
    return public_job(j)


@worker_router.post("/claim")
def claim(d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    active = db.scalar(
        select(Execution).where(Execution.device_id == d.id, Execution.status.in_(["claimed", "sending", "unknown"]))
    )
    if active:
        if active.status != "unknown" and active.lease_until and active.lease_until < service.now():
            active.status, active.error = "unknown", "执行中断，请在手机核对结果；不会自动重发"
            db.commit()
        return {"job": None, "blocked": "存在未结算执行，请先恢复或核对"}
    if (d.capabilities or {}).get("unlocked") is False:
        return {"job": None, "waiting": "等待手机解锁"}
    j = db.scalar(
        select(Execution)
        .where(Execution.device_id == d.id, Execution.status == "queued")
        .order_by(Execution.created_at)
        .limit(1)
    )
    if not j:
        return {"job": None}
    try:
        payload = checked(db, task_for(db, j.task_id), d, j.confirmed_by, j.snapshot.get("action", "direct_message"))
        db.refresh(j)
        if j.status != "queued":
            raise HTTPException(409, "任务已取消或已交接")
        if payload != j.snapshot:
            raise HTTPException(409, "任务或本方账号已变化，请重新确认")
    except HTTPException as exc:
        j.status, j.error = "cancelled", str(exc.detail)
        db.commit()
        return {"job": None, "blocked": j.error}
    token = secrets.token_urlsafe(32)
    j.status, j.attempt, j.lease_hash, j.lease_until = (
        "claimed",
        j.attempt + 1,
        digest(token),
        service.now() + timedelta(minutes=5),
    )
    db.commit()
    return {"job": {**public_job(j), "lease": token}}


def attempt(db: Session, identity: uuid.UUID, d: Device, b: AttemptIn) -> Execution:
    j = db.get(Execution, identity)
    if (
        not j
        or j.device_id != d.id
        or j.attempt != b.attempt
        or not hmac.compare_digest(j.lease_hash or "", digest(b.lease))
    ):
        raise HTTPException(409, "执行凭据或尝试版本无效")
    return j


@worker_router.post("/jobs/{identity}/start")
def start(identity: uuid.UUID, body: AttemptIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    j = attempt(db, identity, d, body)
    payload = checked(db, task_for(db, j.task_id), d, j.confirmed_by, j.snapshot.get("action", "direct_message"))
    db.refresh(j)
    if j.status != "claimed" or not j.lease_until or j.lease_until < service.now():
        raise HTTPException(409, "执行已过期或已开始，不能再次发送")
    if payload != j.snapshot:
        raise HTTPException(409, "发送快照已变化")
    j.status, j.started_at = "sending", service.now()
    db.commit()
    return {"status": "sending"}


@worker_router.post("/jobs/{identity}/result")
def result(identity: uuid.UUID, body: ResultIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    j = attempt(db, identity, d, body)
    payload = {"status": body.status, "detail": body.detail}
    if j.result and "resolution" in j.result:
        prior = j.result.get("late_result")
        if prior and prior != payload:
            raise HTTPException(409, "迟到结果已归档，请核对")
        j.result = {**j.result, "late_result": payload}
        if j.result["resolution"]["sent"] != (body.status == "sent"):
            j.status, j.error = "unknown", "设备迟到结果与人工核对不一致，请再次核对"
        db.commit()
        return public_job(j)
    if j.result and "status" in j.result:
        if {key: j.result.get(key) for key in payload} != payload:
            raise HTTPException(409, "该尝试已有结果，请人工核对，不能覆盖")
        return public_job(j)
    if body.status in {"sent", "request_submitted"} and not j.started_at:
        raise HTTPException(409, "未完成发送前检查，不能记录已发送")
    j.status, j.result, j.finished_at, j.error = (
        body.status,
        {**(j.result or {}), **payload},
        service.now(),
        body.detail or None,
    )
    if body.status == "request_submitted" and j.snapshot.get("action", "direct_message") not in {
        "direct_message",  # The app may present a message request after navigation.
        "message_request",
        "connection_request",
        "inmail",
    }:
        raise HTTPException(409, "本次快照不是请求动作，不能记录请求已提交")
    if body.status == "sent" and j.snapshot.get("action") in {"connection_request", "contact_discovery"}:
        raise HTTPException(409, "此动作不能记录为私信已发送")
    if body.status in {"needs_action", "unavailable", "request_submitted"}:
        task = task_for(db, j.task_id)
        task.status_reason = (
            body.detail
            or {
                "needs_action": "请在手机处理",
                "unavailable": "该目标暂不可联系",
                "request_submitted": "联系请求已提交，等待对方接受",
            }[body.status]
        )
    if body.status == "sent":
        t = task_for(db, j.task_id)
        t.status, t.sent_at, t.sent_recorded_at, t.sent_by = (
            TaskStatus.sent_manual,
            j.started_at,
            service.now(),
            d.owner,
        )
        t.status_reason = "通过绑定手机执行，设备已核对发送结果"
    db.commit()
    return public_job(j)


class Resolution(Input):
    sent: bool
    reason: str = Field(min_length=4, max_length=1000)


@router.post("/tasks/{identity}/resolve")
def resolve(
    identity: uuid.UUID, body: Resolution, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    lock(db)
    t = task_for(db, identity)
    j = db.scalar(select(Execution).where(Execution.task_id == identity))
    if not j or j.status != "unknown":
        raise HTTPException(409, "仅能核对结果未知的手机执行")
    if j.lease_until and j.lease_until > service.now():
        raise HTTPException(409, "手机执行可能仍在进行，请先在手机暂停，稍后再记录核对结果")
    j.result = {**(j.result or {}), "resolution": {"by": op.username, "reason": body.reason, "sent": body.sent}}
    j.status, j.finished_at, j.error = "sent" if body.sent else "failed", service.now(), body.reason
    if body.sent:
        t.status, t.sent_recorded_at, t.sent_by = TaskStatus.sent_manual, service.now(), op.username
        t.sent_at = j.started_at
        t.status_reason = "人工核对手机发送结果：" + body.reason
    db.commit()
    return public_job(j)


class InboundIn(Input):
    body: str = Field(min_length=1, max_length=4000)
    confirmed_incoming: Literal[True]


@worker_router.post("/jobs/{identity}/inbound")
def inbound(identity: uuid.UUID, body: InboundIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    j = db.get(Execution, identity)
    if not j or j.device_id != d.id:
        raise HTTPException(404, "执行记录不存在")
    t = task_for(db, j.task_id)
    try:
        check_device_access(db, j.lead_id, d, t.assigned_to or t.created_by, d.owner)
    except (HTTPException, service.SalesError):
        raise HTTPException(403, "门店已交接或账号无权限，不能回填此会话") from None
    if body.body.strip() == j.snapshot.get("body", "").strip():
        raise HTTPException(409, "内容与本方发出的消息一致，请只记录客户真实回复")
    key = "mobile:" + str(j.id) + ":" + digest(body.body.strip())[:32]
    event, created = service.record_event(
        db,
        j.lead_id,
        {
            "event_key": key,
            "kind": "reply",
            "channel": t.channel.value,
            "payload": {
                "summary": body.body.strip(),
                "source": "mobile",
                "task_id": str(t.id),
                "confirmed_incoming": True,
            },
        },
        d.owner,
    )
    return {"id": str(event.id), "created": created}


@worker_router.post("/account-assistance")
def account_assistance(body: "PageIn", db: Session = Depends(get_db), device: Device = Depends(device_auth)):
    # Release the device-auth advisory lock before a potentially slow model call.
    db.commit()
    return assist_page(body)


class NavigationIn(AttemptIn):
    screen: Screen


class ProgressIn(AttemptIn):
    navigation_history: list[Annotated[str, Field(max_length=240)]] = Field(default_factory=list, max_length=12)
    stage: Literal["opening", "finding_entry", "reading_page", "composing", "verifying_send"]
    detail: str = Field(default="", max_length=240)


def navigation_job(db: Session, identity: uuid.UUID, device: Device, body: AttemptIn) -> Execution:
    j = attempt(db, identity, device, body)
    if j.status != "claimed" or not j.lease_until or j.lease_until < service.now():
        raise HTTPException(409, "任务已停止或执行租约过期")
    payload = checked(db, task_for(db, j.task_id), device, j.confirmed_by, j.snapshot.get("action", "direct_message"))
    if payload != j.snapshot:
        raise HTTPException(409, "任务已变化，请重新确认")
    return j


@worker_router.post("/jobs/{identity}/navigation")
def navigation(
    identity: uuid.UUID, body: NavigationIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)
):
    j = navigation_job(db, identity, d, body)
    count = (j.result or {}).get("navigation_calls", 0)
    if count >= 4:
        return {
            "action": "needs_action",
            "detail": "多次观察后仍未找到聊天入口，消息已保留",
            "screen_id": body.screen.screen_id,
        }
    j.result = {**(j.result or {}), "navigation_calls": count + 1, "progress": "AI 正在查找联系入口"}
    j.error = "AI 正在查找联系入口"
    snapshot = dict(j.snapshot)
    db.commit()
    try:
        return advise(body.screen, snapshot)
    except ValueError:
        return {
            "action": "needs_action",
            "detail": "页面识别结果无效，请重新观察或接管",
            "screen_id": body.screen.screen_id,
        }


@worker_router.post("/jobs/{identity}/progress")
def execution_progress(
    identity: uuid.UUID, body: ProgressIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)
):
    j = attempt(db, identity, d, body)
    if j.status not in {"claimed", "sending"} or not j.lease_until or j.lease_until < service.now():
        raise HTTPException(409, "任务已停止或执行租约过期")
    stages = {
        "opening": "正在打开目标主页",
        "finding_entry": "正在查找联系入口",
        "reading_page": "正在识别当前页面",
        "composing": "正在填写消息",
        "verifying_send": "正在核对发送结果",
    }
    j.error = stages[body.stage] + (f"：{body.detail}" if body.detail else "")
    j.result = {**(j.result or {}), "progress": j.error, "stage": body.stage}
    if body.navigation_history:
        j.result = {**j.result, "navigation_history": body.navigation_history}
    db.commit()
    return {"status": j.status, "progress": j.error}
