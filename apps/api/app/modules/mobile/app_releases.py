"""Admin-reviewed Android releases and short-lived, APK-only phone downloads."""

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import AuditLog, Operator
from app.modules.mobile import apktools

router = APIRouter(prefix="/mobile/app", tags=["mobile-app"])
public_router = APIRouter(prefix="/api/mobile/app-download", tags=["mobile-app"])
MAX_BYTES = 256 * 1024**2
LINK_SECONDS = 15 * 60


def admin(op: Operator) -> None:
    if op.role != "admin":
        raise HTTPException(403, "仅管理员可以上传或发布安装包")


def directory() -> Path:
    folder = get_settings().data_dir / "mobile-apps"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def uploads(db: Session) -> list[dict]:
    return [
        dict(r.after or {}, id=r.entity_id)
        for r in db.scalars(
            select(AuditLog).where(
                AuditLog.action == "mobile_app_uploaded",
                AuditLog.entity == "mobile_app",
            )
        )
    ]


def publications(db: Session) -> list[dict]:
    return sorted(
        [
            r.after or {}
            for r in db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "mobile_app_published",
                    AuditLog.entity == "mobile_app",
                )
            )
        ],
        key=lambda r: r["published_at"],
        reverse=True,
    )


def release(db: Session, identity: str) -> dict:
    item = next((r for r in uploads(db) if r["id"] == identity), None)
    if not item:
        raise HTTPException(404, "安装包不存在")
    return item


def artifact(item: dict) -> Path:
    path = directory() / (item["sha256"] + ".apk")
    if not path.is_file() or path.stat().st_size != item["size"]:
        raise HTTPException(409, "安装包文件缺失或不完整，请联系管理员重新上传")
    return path


def pinned_signer(db: Session) -> str | None:
    history = publications(db)
    return release(db, history[-1]["release_id"])["signer_sha256"] if history else None


def check_signer(db: Session, item: dict) -> None:
    pinned = pinned_signer(db)
    if pinned and not hmac.compare_digest(pinned, item["signer_sha256"]):
        raise HTTPException(409, "签名与已发布版本不一致，无法覆盖安装；请使用原签名密钥重新构建")


@router.get("")
def catalog(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    all_uploads = {r["id"]: r for r in uploads(db)}
    history = publications(db)
    versions: list[dict] = []
    for publication in history:
        if not any(r["id"] == publication["release_id"] for r in versions):
            versions.append({**all_uploads[publication["release_id"]], **publication})
    published_ids = {p["release_id"] for p in history}
    return {
        "current": versions[0] if versions else None,
        "previous": versions[1] if len(versions) > 1 else None,
        "drafts": sorted(
            [r for r in all_uploads.values() if r["id"] not in published_ids],
            key=lambda r: r["uploaded_at"],
            reverse=True,
        )
        if op.role == "admin"
        else [],
        "max_bytes": MAX_BYTES,
        "server": get_settings().mobile_public_url,
        "validator_available": apktools.available() if op.role == "admin" else None,
    }


@router.post("/uploads", status_code=201)
async def upload(request: Request, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    admin(op)
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError as exc:
        raise HTTPException(400, "上传长度无效") from exc
    if length > MAX_BYTES:
        raise HTTPException(413, "安装包不能超过 256 MB")
    fd, name = tempfile.mkstemp(prefix="upload-", suffix=".apk", dir=directory())
    temporary = Path(name)
    size, digest = 0, hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "安装包不能超过 256 MB")
                digest.update(chunk)
                stream.write(chunk)
        if not size:
            raise HTTPException(422, "安装包为空")
        info = await run_in_threadpool(apktools.inspect, temporary)
        db.execute(text("SELECT pg_advisory_xact_lock(71801801)"))
        check_signer(db, info)
        checksum = digest.hexdigest()
        existing = next((r for r in uploads(db) if r["sha256"] == checksum), None)
        destination = directory() / (checksum + ".apk")
        # Atomic replace also repairs a missing file from an incomplete backup restore.
        os.replace(temporary, destination)
        if existing:
            return {**existing, "already_published": any(p["release_id"] == existing["id"] for p in publications(db))}
        identity = str(uuid.uuid4())
        item = {
            **info,
            "id": identity,
            "sha256": checksum,
            "size": size,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "uploaded_by": op.username,
        }
        audit.record(db, op, "mobile_app_uploaded", "mobile_app", identity, after=item)
        db.commit()
        return item
    finally:
        temporary.unlink(missing_ok=True)


class PublishIn(BaseModel):
    expected_current_id: uuid.UUID | None = Field(...)
    notes: str = Field(default="", max_length=3000)
    rollback: bool = False


@router.post("/{identity}/publish")
def publish(
    identity: uuid.UUID, body: PublishIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    admin(op)
    db.execute(text("SELECT pg_advisory_xact_lock(71801801)"))
    history = publications(db)
    current = history[0]["release_id"] if history else None
    if (str(body.expected_current_id) if body.expected_current_id else None) != current:
        raise HTTPException(409, "当前发布版本已变化，请刷新后重新确认")
    item = release(db, str(identity))
    check_signer(db, item)
    artifact(item)
    if body.rollback:
        previous = next((p["release_id"] for p in history if p["release_id"] != current), None)
        if str(identity) != previous:
            raise HTTPException(409, "只能回退到上一发布版本")
    elif current and item["version_code"] < release(db, current)["version_code"]:
        raise HTTPException(409, "不能将旧版本作为更新发布，请使用回退操作")
    audit.record(
        db,
        op,
        "mobile_app_published",
        "mobile_app",
        identity,
        after={
            "release_id": str(identity),
            "notes": body.notes.strip(),
            "rollback": body.rollback,
            "published_at": datetime.now(UTC).isoformat(),
            "published_by": op.username,
        },
    )
    db.commit()
    return {"ok": True}


def token_signature(value: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), ("mobile-apk:" + value).encode(), hashlib.sha256).hexdigest()


@router.post("/download-link")
def download_link(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    if op.role not in {"admin", "director", "member"}:
        raise HTTPException(403, "只读账号不能获取安装包下载链接")
    history = publications(db)
    if not history:
        raise HTTPException(404, "管理员尚未发布安装包")
    identity = history[0]["release_id"]
    artifact(release(db, identity))
    expires = int(time.time()) + LINK_SECONDS
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "release_id": identity,
                    "issuer": str(op.id),
                    "session_version": op.session_version,
                    "expires": expires,
                },
                separators=(",", ":"),
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    token = payload + "." + token_signature(payload)
    return {
        "path": f"/api/mobile/app-download/{identity}?token={token}",
        "expires_at": datetime.fromtimestamp(expires, UTC),
    }


@public_router.get("/{identity}")
def download(identity: uuid.UUID, token: str, db: Session = Depends(get_db)):
    try:
        if len(token) > 2048:
            raise ValueError()
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature, token_signature(payload)):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["release_id"] != str(identity) or int(data["expires"]) <= time.time():
            raise ValueError()
        issuer = db.get(Operator, uuid.UUID(data["issuer"]))
        if (
            not issuer
            or not issuer.is_active
            or issuer.must_change_password
            or issuer.role not in {"admin", "director", "member"}
        ):
            raise ValueError()
        if data["session_version"] != issuer.session_version:
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(403, "下载链接已失效，请回到“我的手机”重新获取") from exc
    if not any(p["release_id"] == str(identity) for p in publications(db)):
        raise HTTPException(404, "安装包尚未发布")
    item = release(db, str(identity))
    return FileResponse(
        artifact(item),
        media_type="application/vnd.android.package-archive",
        filename=f"Beacon-{item['version_code']}-{item['sha256'][:8]}.apk",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Checksum-SHA256": item["sha256"],
            "Referrer-Policy": "no-referrer",
        },
    )
