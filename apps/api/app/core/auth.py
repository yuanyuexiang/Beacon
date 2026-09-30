"""认证：scrypt 口令哈希，HMAC 签名的会话 cookie，当前操作者依赖。仅标准库。"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
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


def make_session_token(operator_id: str) -> str:
    payload = json.dumps({"op": operator_id, "exp": int(time.time()) + SESSION_TTL, "n": secrets.token_hex(8)}).encode()
    b = base64.urlsafe_b64encode(payload).decode()
    return b + "." + _sign(payload)


def parse_session_token(token: str) -> str | None:
    try:
        b, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(b.encode())
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        data = json.loads(payload)
        if data.get("exp", 0) < time.time():
            return None
        return str(data["op"])
    except Exception:
        return None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=SESSION_TTL, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def current_operator(request: Request, db: Session = Depends(get_db)) -> Operator:
    token = request.cookies.get(COOKIE)
    op_id = parse_session_token(token) if token else None
    if not op_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    op = db.get(Operator, op_id)
    if op is None or not op.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "操作者不存在或已停用")
    return op


def bootstrap_operator(db: Session) -> Operator | None:
    """无任何操作者时，用 BEACON_BOOTSTRAP_OPERATOR/PASSWORD 创建首个操作者；已有操作者则不动。"""
    if db.scalar(select(Operator.id).limit(1)) is not None:
        return None
    s = get_settings()
    if not s.bootstrap_operator or not s.bootstrap_password:
        return None
    op = Operator(username=s.bootstrap_operator, password_hash=hash_password(s.bootstrap_password), is_active=True)
    db.add(op)
    db.commit()
    return op


def now() -> datetime:
    return datetime.now(UTC)
