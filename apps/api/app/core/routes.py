"""认证与受控文件路由。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import (
    clear_session_cookie,
    current_operator,
    make_session_token,
    set_session_cookie,
    verify_password,
)
from app.core.db import get_db
from app.core.files import UnsafePathError, resolve_within
from app.core.models import Operator

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    id: uuid.UUID
    username: str


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> Operator:
    op = db.scalar(select(Operator).where(Operator.username == body.username))
    if op is None or not op.is_active or not verify_password(body.password, op.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或口令错误")
    set_session_cookie(response, make_session_token(str(op.id)))
    audit.record(db, op, "login", "operator", op.id)
    db.commit()
    return op


@router.post("/auth/logout", status_code=204)
def logout(response: Response, op: Operator = Depends(current_operator)) -> Response:
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=MeOut)
def me(op: Operator = Depends(current_operator)) -> Operator:
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
