"""Authenticated workspace avatars; only the owner can replace their normalized thumbnail."""

import io
import uuid
import warnings

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator, lock_current
from app.core.db import get_db
from app.core.models import Operator
from app.core.routes import MeOut

router = APIRouter()
LIMIT = 5 * 1024 * 1024


def thumbnail(data: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                if im.format not in {"JPEG", "PNG", "WEBP"} or im.width * im.height > 16_000_000:
                    raise ValueError()
                normalized = ImageOps.exif_transpose(im)
                normalized = ImageOps.fit(normalized.convert("RGB"), (256, 256))
                out = io.BytesIO()
                normalized.save(out, format="JPEG", quality=85)
                return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "请选择有效的 JPG、PNG 或 WebP 图片，像素不超过 1600 万") from None


@router.put("/auth/avatar", response_model=MeOut)
def upload_avatar(file: UploadFile, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    data = file.file.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise HTTPException(413, "头像不能超过 5 MB")
    normalized = thumbnail(data)
    lock_current(db, op)
    op.avatar_data = normalized
    op.avatar_version = uuid.uuid4().hex
    audit.record(db, op, "avatar_updated", "operator", op.id)
    db.commit()
    return op


@router.delete("/auth/avatar", response_model=MeOut)
def delete_avatar(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    lock_current(db, op)
    op.avatar_data = None
    op.avatar_version = None
    audit.record(db, op, "avatar_removed", "operator", op.id)
    db.commit()
    return op


@router.get("/avatars/{username}")
def avatar(username: str, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    data = db.scalar(select(Operator.avatar_data).where(Operator.username == username))
    if not data:
        raise HTTPException(404, "暂无头像")
    return Response(
        data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
