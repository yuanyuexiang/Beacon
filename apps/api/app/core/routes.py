"""认证与受控文件路由。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import (
    clear_session_cookie,
    current_operator,
    hash_password,
    lock_current,
    make_session_token,
    set_session_cookie,
    verify_password,
)
from app.core.db import get_db
from app.core.files import UnsafePathError, resolve_within
from app.core.models import Operator

router = APIRouter()


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256, repr=False)


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None
    role: str
    must_change_password: bool

    model_config = {"from_attributes": True}


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> Operator:
    db.execute(text("SELECT pg_advisory_xact_lock(70931248)"))
    op = db.scalar(select(Operator).where(Operator.username == body.username))
    if op is None or not op.is_active or not verify_password(body.password, op.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或口令错误")
    set_session_cookie(response, make_session_token(str(op.id), op.session_version))
    audit.record(db, op, "login", "operator", op.id)
    db.commit()
    return op


@router.post("/auth/logout", status_code=204)
def logout(response: Response, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> Response:
    lock_current(db, op)
    op.session_version += 1
    audit.record(db, op, "logout", "operator", op.id)
    db.commit()
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=MeOut)
def me(op: Operator = Depends(current_operator)) -> Operator:
    return op


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=80)


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256, repr=False)
    new_password: str = Field(min_length=12, max_length=128, repr=False)


@router.patch("/auth/profile", response_model=MeOut)
def profile(body: ProfileIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> Operator:
    lock_current(db, op)
    previous = op.display_name
    op.display_name = (body.display_name or "").strip() or None
    audit.record(
        db,
        op,
        "profile_updated",
        "operator",
        op.id,
        before={"display_name": previous},
        after={"display_name": op.display_name},
    )
    db.commit()
    return op


@router.post("/auth/password", response_model=MeOut)
def password(
    body: ChangePasswordIn, response: Response, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> Operator:
    lock_current(db, op)
    if not verify_password(body.current_password, op.password_hash):
        raise HTTPException(400, "当前密码不正确")
    if verify_password(body.new_password, op.password_hash):
        raise HTTPException(422, "新密码不能与当前密码相同")
    op.password_hash = hash_password(body.new_password)
    op.must_change_password = False
    op.session_version += 1
    audit.record(db, op, "password_changed", "operator", op.id, after={"sessions_revoked": True})
    db.commit()
    # 当前窗口获得新会话，其他旧会话失效。
    set_session_cookie(response, make_session_token(str(op.id), op.session_version))
    return op


@router.get("/files/{rel_path:path}")
def get_file(rel_path: str, op: Operator = Depends(current_operator)) -> FileResponse:
    """受控文件下载：需登录；路径限定在数据目录内。"""
    try:
        p = resolve_within(rel_path)
    except UnsafePathError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return FileResponse(p)
