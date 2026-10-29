"""同一工作空间内的用户管理；不删除历史操作者，不记录密码或哈希。"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator, hash_password, lock_current, verify_password
from app.core.db import get_db
from app.core.models import Operator

Role = Literal["admin", "director", "member", "viewer"]
router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None
    avatar_url: str | None
    role: Role
    is_active: bool
    must_change_password: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str | None = Field(default=None, max_length=80)
    role: Role = "member"
    initial_password: str = Field(min_length=8, max_length=128, repr=False)

    @field_validator("username", mode="before")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=80)
    role: Role | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporary_password: str = Field(min_length=8, max_length=128, repr=False)


def user_manager(op: Operator = Depends(current_operator)) -> Operator:
    if op.role not in {"admin", "director"}:
        raise HTTPException(403, "此操作需要管理员或销售总监权限")
    return op


def lock_manager(db: Session, op: Operator) -> None:
    lock_current(db, op)
    if op.role not in {"admin", "director"}:
        raise HTTPException(403, "此操作需要管理员或销售总监权限")


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), op: Operator = Depends(user_manager)):
    query = select(Operator).order_by(Operator.created_at, Operator.id)
    if op.role == "director":
        query = query.where(Operator.role == "member")
    return db.scalars(query).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), op: Operator = Depends(user_manager)):
    lock_manager(db, op)
    if op.role == "director" and body.role != "member":
        raise HTTPException(403, "销售总监只能创建业务成员")
    if db.scalar(select(Operator.id).where(func.lower(Operator.username) == body.username)):
        raise HTTPException(409, "登录名已存在")
    target = Operator(
        username=body.username,
        display_name=(body.display_name or "").strip() or None,
        role=body.role,
        is_active=True,
        password_hash=hash_password(body.initial_password),
        must_change_password=True,
    )
    db.add(target)
    try:
        db.flush()
        audit.record(
            db, op, "user_created", "operator", target.id, after=UserOut.model_validate(target).model_dump(mode="json")
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "登录名已存在") from None
    return target


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, body: UserPatch, db: Session = Depends(get_db), op: Operator = Depends(user_manager)
):
    lock_manager(db, op)
    target = db.get(Operator, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if op.role == "director" and (target.role != "member" or body.role not in {None, "member"}):
        raise HTTPException(403, "销售总监只能管理业务成员，不能调整角色")
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(k, "missing") is None for k in ("role", "is_active")):
        raise HTTPException(422, "角色和启用状态不能为空")
    before = UserOut.model_validate(target).model_dump(mode="json")
    if (
        target.is_active
        and target.role == "admin"
        and (changes.get("role", "admin") != "admin" or changes.get("is_active") is False)
    ):
        count = db.scalar(
            select(func.count()).select_from(Operator).where(Operator.role == "admin", Operator.is_active.is_(True))
        )
        if (count or 0) <= 1:
            raise HTTPException(409, "至少保留一位有效管理员，请先创建或启用其他管理员")
    revoke = any(k in changes and changes[k] != getattr(target, k) for k in ("role", "is_active"))
    for key, value in changes.items():
        if key == "display_name":
            value = (value or "").strip() or None
        setattr(target, key, value)
    if revoke:
        target.session_version += 1
    audit.record(
        db,
        op,
        "user_updated",
        "operator",
        target.id,
        before=before,
        after=UserOut.model_validate(target).model_dump(mode="json"),
    )
    db.commit()
    return target


@router.post("/{user_id}/reset-password", response_model=UserOut)
def reset_password(
    user_id: uuid.UUID, body: PasswordReset, db: Session = Depends(get_db), op: Operator = Depends(user_manager)
):
    lock_manager(db, op)
    target = db.get(Operator, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if op.role == "director" and target.role != "member":
        raise HTTPException(403, "销售总监只能管理业务成员")
    if verify_password(body.temporary_password, target.password_hash):
        raise HTTPException(422, "临时密码不能与当前密码相同")
    target.password_hash = hash_password(body.temporary_password)
    target.must_change_password = True
    target.session_version += 1
    audit.record(
        db,
        op,
        "user_password_reset",
        "operator",
        target.id,
        after={"must_change_password": True, "sessions_revoked": True},
    )
    db.commit()
    return target
