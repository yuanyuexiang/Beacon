"""认证：scrypt 口令哈希，HMAC 签名的会话 cookie，当前操作者依赖。仅标准库。"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import Operator

COOKIE = "beacon_session"
SESSION_TTL = 12 * 3600


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def _sign(payload: bytes) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def make_session_token(operator_id: str, session_version: int = 0) -> str:
    payload = json.dumps(
        {"op": operator_id, "ver": session_version, "exp": int(time.time()) + SESSION_TTL, "n": secrets.token_hex(8)}
    ).encode()
    b = base64.urlsafe_b64encode(payload).decode()
    return b + "." + _sign(payload)


def parse_session_payload(token: str) -> dict | None:
    try:
        b, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(b.encode())
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        data = json.loads(payload)
        if data.get("exp", 0) < time.time():
            return None
        uuid.UUID(data["op"])
        if not isinstance(data.get("ver", 0), int):
            return None
        return data
    except Exception:
        return None


def parse_session_token(token: str) -> str | None:
    payload = parse_session_payload(token)
    return str(payload["op"]) if payload else None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", max_age=SESSION_TTL, path="/", secure=get_settings().cookie_secure
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def current_operator(request: Request, db: Session = Depends(get_db)) -> Operator:
    token = request.cookies.get(COOKIE)
    payload = parse_session_payload(token) if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    op = db.get(Operator, uuid.UUID(payload["op"]))
    if op is None or not op.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "操作者不存在或已停用")
    if payload.get("ver", 0) != op.session_version:
        raise HTTPException(401, "登录已失效，请重新登录")
    db.info.pop("member_scope", None)
    db.info["operator_role"], db.info["operator_username"] = op.role, op.username
    enforce_permissions(request, op)
    if op.role == "member":
        from app.core.access import set_scope

        set_scope(db, op.username)
    return op


def enforce_permissions(request: Request, op: Operator) -> None:
    path = request.url.path.rstrip("/")
    personal = path in {"/api/auth/me", "/api/auth/logout", "/api/auth/profile", "/api/auth/password"}
    if op.must_change_password and path not in {"/api/auth/me", "/api/auth/logout", "/api/auth/password"}:
        raise HTTPException(403, "请先修改初始密码", headers={"X-Beacon-Action": "change-password"})
    if personal:
        return
    writes = request.method not in {"GET", "HEAD", "OPTIONS"}
    admin_only = path.startswith("/api/users") or (
        writes
        and (
            path in {"/api/lead-policy", "/api/outreach-profile"}
            or path.startswith("/api/directory/")
            or path
            in {
                "/api/gmail/credentials",
                "/api/gmail/configure",
                "/api/gmail/check",
                "/api/gmail/test/preview",
                "/api/gmail/test/send",
                "/api/gmail/connect",
                "/api/gmail/disconnect",
                "/api/gmail/policy",
            }
            or path == "/api/outreach/app"
            or path.startswith("/api/outreach/accounts")
        )
    )
    if admin_only and op.role != "admin":
        raise HTTPException(403, "此操作需要管理员权限")
    if op.role == "member":
        if (
            path.startswith(("/api/runs", "/api/directory", "/api/imports", "/api/lists"))
            or (path == "/api/batches" and writes)
            or (path.startswith("/api/batches/") and (writes or any(x in path for x in ("delete-preview", "/runs"))))
        ):
            raise HTTPException(403, "名单与门店池管理需要销售总监或管理员权限")
        if path == "/api/gmail/sync-replies":
            raise HTTPException(403, "全量回复同步需要销售总监或管理员权限")
    if writes and op.role == "viewer":
        raise HTTPException(403, "只读成员不能修改数据或发送消息")


def lock_current(db: Session, op: Operator) -> None:
    expected = op.session_version
    db.execute(text("SELECT pg_advisory_xact_lock(70931248)"))
    db.refresh(op, with_for_update=True)
    if not op.is_active or op.session_version != expected:
        raise HTTPException(401, "账号状态已改变，请重新登录")


def may_send(db: Session, username: str | None) -> bool:
    op = db.scalar(
        select(Operator)
        .where(Operator.username == username)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return bool(op and op.is_active and not op.must_change_password and op.role in {"admin", "director", "member"})


def bootstrap_operator(db: Session) -> Operator | None:
    """无任何操作者时，用 BEACON_BOOTSTRAP_OPERATOR/PASSWORD 创建首个操作者；已有操作者则不动。"""
    if db.scalar(select(Operator.id).limit(1)) is not None:
        return None
    s = get_settings()
    if not s.bootstrap_operator or not s.bootstrap_password:
        return None
    op = Operator(
        username=s.bootstrap_operator, password_hash=hash_password(s.bootstrap_password), is_active=True, role="admin"
    )
    db.add(op)
    db.commit()
    return op


def now() -> datetime:
    return datetime.now(UTC)
