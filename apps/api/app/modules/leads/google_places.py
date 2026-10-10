"""Google 实时查看：仅保存 Place ID 与人工核对元数据；响应、照片和签名引用均不缓存。"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import AuditLog, Operator
from app.integrations import google_places as google
from app.modules.leads.models import Lead

router = APIRouter(tags=["google-places"])
NO_STORE = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}
TOKEN_SECONDS = 600


class PlacesLink(BaseModel):
    place_id: str
    version: str
    reviewed_by: str
    reviewed_at: str


class PlacesState(BaseModel):
    configured: bool
    link: PlacesLink | None
    attempts_today: int
    daily_limit: int


class PlacesSearchIn(BaseModel):
    query: str | None = Field(default=None, max_length=600)


class PlacesCandidate(BaseModel):
    place: google.Place
    token: str


class PlacesSearchOut(BaseModel):
    candidates: list[PlacesCandidate]
    fetched_at: str
    expires_at: str


class PlacesConfirmIn(BaseModel):
    token: str = Field(min_length=1, max_length=8192)
    address_checked: bool
    branch_checked: bool


class PlacesPhotoOut(BaseModel):
    token: str
    width: int
    height: int
    authors: list[google.Attribution]
    source_url: str | None


class PlacesDetailsOut(BaseModel):
    place: google.Place
    photos: list[PlacesPhotoOut]
    fetched_at: str
    expires_at: str


class PlacesTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=8192)


class PlacesUnlinkIn(BaseModel):
    expected_version: str


def _lead(db: Session, lead_id: uuid.UUID, *, lock: bool = False) -> Lead:
    stmt = select(Lead).where(Lead.id == lead_id).execution_options(populate_existing=True)
    lead = db.scalar(stmt.with_for_update() if lock else stmt)
    if lead is None:
        raise HTTPException(404, "线索不存在", headers=NO_STORE)
    return lead


def _link(lead: Lead) -> dict | None:
    return (lead.raw or {}).get("google_places_link")


def _fingerprint(lead: Lead) -> str:
    value = [lead.name, lead.address, lead.postcode, (lead.raw or {}).get("google_places_revision")]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def _signature(payload: bytes) -> str:
    return hmac.new(get_settings().secret_key.encode(), b"google-places-v1:" + payload, hashlib.sha256).hexdigest()


def _token(lead: Lead, op: Operator, purpose: str, value: str) -> str:
    payload = json.dumps(
        {
            "lead": str(lead.id),
            "op": str(op.id),
            "purpose": purpose,
            "value": value,
            "fingerprint": _fingerprint(lead),
            "exp": int(time.time()) + TOKEN_SECONDS,
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode() + "." + _signature(payload)


def _parse(token: str, lead: Lead, op: Operator, purpose: str) -> str:
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded)
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError
        data = json.loads(payload)
        if (
            data["lead"] != str(lead.id)
            or data["op"] != str(op.id)
            or data["purpose"] != purpose
            or data["exp"] <= time.time()
            or data["fingerprint"] != _fingerprint(lead)
        ):
            raise ValueError
        return str(data["value"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(409, "结果已失效或门店信息已改变，请重新搜索或刷新", headers=NO_STORE) from e


def _client(db: Session, op: Operator, lead_id: uuid.UUID) -> google.PlacesClient:
    settings = get_settings()

    def reserve(sku: google.SKU) -> None:
        # 项目级持久限额；并发请求先锁计数再提交预留，网络失败也占一次尝试。
        db.execute(text("SELECT pg_advisory_xact_lock(70931246)"))
        now = datetime.now(UTC)
        count = select(func.count()).select_from(AuditLog).where(AuditLog.action == "google_places_request")
        daily = db.scalar(count.where(AuditLog.at >= _day_start())) or 0
        recent = db.scalar(count.where(AuditLog.at >= now - timedelta(minutes=1))) or 0
        if daily >= settings.google_places_daily_limit or recent >= 20:
            db.rollback()
            raise google.PlacesError("Google 查询次数已达上限，请稍后或次日重试", 429)
        audit.record(db, op, "google_places_request", "lead", lead_id, after={"sku": sku, "attempts": 1})
        db.commit()

    return google.PlacesClient(settings.google_places_api_key, settings.google_places_proxy, reserve=reserve)


def _day_start() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _error(e: google.PlacesError) -> HTTPException:
    return HTTPException(e.status, str(e), headers=NO_STORE)


def _freshness() -> tuple[str, str]:
    now = datetime.now(UTC)
    return now.isoformat(), (now + timedelta(seconds=TOKEN_SECONDS)).isoformat()


@router.get("/leads/{lead_id}/google-places", response_model=PlacesState)
def state(
    lead_id: uuid.UUID, response: Response, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    response.headers.update(NO_STORE)
    lead = _lead(db, lead_id)
    attempts = (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "google_places_request", AuditLog.at >= _day_start())
        )
        or 0
    )
    return {
        "configured": bool(get_settings().google_places_api_key),
        "link": _link(lead),
        "attempts_today": attempts,
        "daily_limit": get_settings().google_places_daily_limit,
    }


@router.post("/leads/{lead_id}/google-places/search", response_model=PlacesSearchOut)
def search(
    lead_id: uuid.UUID,
    body: PlacesSearchIn,
    response: Response,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> dict:
    response.headers.update(NO_STORE)
    lead = _lead(db, lead_id)
    fingerprint = _fingerprint(lead)
    query = (body.query or "").strip() or " ".join(x for x in (lead.name, lead.address, lead.postcode, "UK") if x)[:600]
    try:
        places = _client(db, op, lead_id).search(query)
    except google.PlacesError as e:
        raise _error(e) from e
    lead = _lead(db, lead_id)
    if _fingerprint(lead) != fingerprint:
        raise HTTPException(409, "门店信息已改变，请重新搜索", headers=NO_STORE)
    fetched, expires = _freshness()
    return {
        "candidates": [{"place": p, "token": _token(lead, op, "candidate", p.id)} for p in places],
        "fetched_at": fetched,
        "expires_at": expires,
    }


@router.post("/leads/{lead_id}/google-places/confirm", response_model=PlacesLink)
def confirm(
    lead_id: uuid.UUID,
    body: PlacesConfirmIn,
    response: Response,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> dict:
    response.headers.update(NO_STORE)
    if not body.address_checked or not body.branch_checked:
        raise HTTPException(400, "须核对地址与门店归属，确认不是同名异店或其他分店", headers=NO_STORE)
    lead = _lead(db, lead_id, lock=True)
    place_id = _parse(body.token, lead, op, "candidate")
    old = _link(lead)
    link = {
        "place_id": place_id,
        "version": str(uuid.uuid4()),
        "reviewed_by": op.username,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    lead.raw = {**(lead.raw or {}), "google_places_link": link, "google_places_revision": link["version"]}
    audit.record(
        db, op, "confirm_google_place", "lead", lead_id, before={"place_id": (old or {}).get("place_id")}, after=link
    )
    db.commit()
    return link


@router.post("/leads/{lead_id}/google-places/unlink", status_code=204)
def unlink(
    lead_id: uuid.UUID, body: PlacesUnlinkIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> Response:
    lead = _lead(db, lead_id, lock=True)
    old = _link(lead)
    if not old or old["version"] != body.expected_version:
        raise HTTPException(409, "关联已改变，请刷新", headers=NO_STORE)
    lead.raw = {
        **{k: v for k, v in (lead.raw or {}).items() if k != "google_places_link"},
        "google_places_revision": str(uuid.uuid4()),
    }
    audit.record(db, op, "unlink_google_place", "lead", lead_id, before={"place_id": old["place_id"]})
    db.commit()
    return Response(status_code=204, headers=NO_STORE)


@router.post("/leads/{lead_id}/google-places/details", response_model=PlacesDetailsOut)
def details(
    lead_id: uuid.UUID, response: Response, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    response.headers.update(NO_STORE)
    lead = _lead(db, lead_id)
    link = _link(lead)
    if not link:
        raise HTTPException(400, "请先搜索并人工确认 Google 门店", headers=NO_STORE)
    fingerprint = _fingerprint(lead)
    try:
        place = _client(db, op, lead_id).details(link["place_id"])
    except google.PlacesError as e:
        raise _error(e) from e
    lead = _lead(db, lead_id)
    if _fingerprint(lead) != fingerprint:
        raise HTTPException(409, "关联已改变，请重新查看", headers=NO_STORE)
    photos = [
        {
            "token": _token(lead, op, "photo", p.name),
            "width": p.widthPx,
            "height": p.heightPx,
            "authors": p.authorAttributions,
            "source_url": p.googleMapsUri,
        }
        for p in place.photos
    ]
    # 不将原始照片资源名纳入输出 place；短期引用只随当前响应返回。
    place.photos = []
    fetched, expires = _freshness()
    return {"place": place, "photos": photos, "fetched_at": fetched, "expires_at": expires}


@router.post("/leads/{lead_id}/google-places/photo")
def photo(
    lead_id: uuid.UUID, body: PlacesTokenIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> Response:
    lead = _lead(db, lead_id)
    name = _parse(body.token, lead, op, "photo")
    fingerprint = _fingerprint(lead)
    match = google.PHOTO_NAME.fullmatch(name)
    if not match or match.group(1) != (_link(lead) or {}).get("place_id"):
        raise HTTPException(409, "照片与当前关联不一致，请刷新", headers=NO_STORE)
    try:
        content, media = _client(db, op, lead_id).photo(name)
    except google.PlacesError as e:
        raise _error(e) from e
    if _fingerprint(_lead(db, lead_id)) != fingerprint:
        raise HTTPException(409, "关联已改变，请重新查看", headers=NO_STORE)
    return Response(content=content, media_type=media, headers={**NO_STORE, "X-Content-Type-Options": "nosniff"})
