import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.modules.directory import service
from app.modules.directory.models import Authority, Change, Entry, Region, SyncRun, WorkerStatus

router = APIRouter(prefix="/directory", tags=["directory"])


class RegionIn(BaseModel):
    authority_id: int = Field(gt=0)
    business_type_ids: list[Literal[1, 7843, 7844]] = Field(default=[1, 7843, 7844], min_length=1, max_length=3)
    auto_sync: bool = False
    interval_hours: Literal[24, 72, 168] = 24


class RegionPatch(BaseModel):
    business_type_ids: list[Literal[1, 7843, 7844]] = Field(min_length=1, max_length=3)
    auto_sync: bool
    interval_hours: Literal[24, 72, 168] = 24


class SyncOut(BaseModel):
    id: uuid.UUID
    authority_id: int
    business_type_ids: list[int]
    trigger: str
    status: str
    counts: dict | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    source_versions: dict | None
    model_config = {"from_attributes": True}


def region_out(db: Session, region: Region) -> dict:
    counts = dict(
        db.execute(
            select(Entry.business_type_id, func.count())
            .where(Entry.authority_id == region.authority_id, Entry.present.is_(True))
            .group_by(Entry.business_type_id)
        ).all()
    )
    authority = db.get(Authority, region.authority_id)
    latest = db.scalar(
        select(SyncRun)
        .where(SyncRun.authority_id == region.authority_id)
        .order_by(SyncRun.created_at.desc(), SyncRun.id.desc())
        .limit(1)
    )
    return {
        "id": region.authority_id,
        "name": region.name,
        "region": authority.region if authority else None,
        "count": authority.establishment_count if authority else None,
        "business_type_ids": region.business_type_ids,
        "auto_sync": region.auto_sync,
        "interval_hours": region.interval_hours,
        "next_sync_at": region.next_sync_at,
        "last_success_at": region.last_success_at,
        "type_versions": region.type_versions,
        "counts": counts,
        "pool_count": sum(counts.values()),
        "latest_sync": SyncOut.model_validate(latest) if latest else None,
    }


@router.get("/status")
def worker_status(db: Session = Depends(get_db)) -> dict:
    row = db.get(WorkerStatus, "directory")
    return {
        "online": bool(row and service.utcnow() - row.heartbeat_at < timedelta(seconds=60)),
        "heartbeat_at": row.heartbeat_at if row else None,
    }


@router.get("/authorities")
def list_authorities(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"id": a.authority_id, "name": a.name, "region": a.region, "count": a.establishment_count}
        for a in db.scalars(select(Authority).order_by(Authority.name))
    ]


@router.post("/authorities/refresh")
def refresh_authorities(db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> dict:
    try:
        count = service.refresh_authorities(db)
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"地区名录更新失败，已缓存的地区仍可使用：{exc}") from exc
    audit.record(db, op, "refresh_directory_authorities", "directory", "authorities", after={"count": count})
    db.commit()
    return {"count": count}


@router.get("/regions")
def list_regions(db: Session = Depends(get_db)) -> list[dict]:
    return [region_out(db, r) for r in db.scalars(select(Region).order_by(Region.name))]


@router.post("/regions", status_code=201)
def create_region(body: RegionIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> dict:
    authority = db.get(Authority, body.authority_id)
    if authority is None:
        raise HTTPException(422, "请先更新地区名录并选择有效地区")
    if db.get(Region, body.authority_id):
        raise HTTPException(409, "该地区已加入门店池")
    region = Region(
        authority_id=body.authority_id,
        name=authority.name,
        business_type_ids=sorted(set(body.business_type_ids)),
        auto_sync=body.auto_sync,
        interval_hours=body.interval_hours,
        type_versions={},
    )
    db.add(region)
    db.flush()
    audit.record(db, op, "create_directory_region", "directory", str(body.authority_id), after=body.model_dump())
    run = service.enqueue(db, region.authority_id)
    db.commit()
    return {**region_out(db, region), "queued_sync_id": str(run.id)}


@router.patch("/regions/{authority_id}")
def update_region(
    authority_id: int, body: RegionPatch, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    region = db.scalar(select(Region).where(Region.authority_id == authority_id).with_for_update())
    if region is None:
        raise HTTPException(404, "地区不存在")
    region.business_type_ids = sorted(set(body.business_type_ids))
    region.auto_sync, region.interval_hours = body.auto_sync, body.interval_hours
    region.next_sync_at = service.utcnow() + timedelta(hours=body.interval_hours) if body.auto_sync else None
    audit.record(db, op, "update_directory_region", "directory", str(authority_id), after=body.model_dump())
    db.commit()
    return region_out(db, region)


@router.post("/regions/{authority_id}/sync", response_model=SyncOut, status_code=202)
def enqueue_sync(authority_id: int, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    run = service.enqueue(db, authority_id)
    audit.record(db, op, "queue_directory_sync", "directory_sync", run.id)
    db.commit()
    return run


@router.get("/regions/{authority_id}/syncs", response_model=list[SyncOut])
def list_syncs(authority_id: int, db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(SyncRun)
            .where(SyncRun.authority_id == authority_id)
            .order_by(SyncRun.created_at.desc(), SyncRun.id.desc())
            .limit(50)
        )
    )


@router.get("/syncs/{run_id}/changes")
def list_changes(run_id: uuid.UUID, page: int = Query(1, ge=1), db: Session = Depends(get_db)) -> dict:
    total = db.scalar(select(func.count()).select_from(Change).where(Change.sync_id == run_id)) or 0
    rows = db.execute(
        select(Change, Entry.name)
        .join(Entry, Entry.fhrsid == Change.fhrsid)
        .where(Change.sync_id == run_id)
        .order_by(Change.fhrsid)
        .limit(100)
        .offset((page - 1) * 100)
    )
    return {
        "total": total,
        "items": [
            {"fhrsid": c.fhrsid, "name": name, "kind": c.kind, "changed_at": c.changed_at, "diff": c.diff}
            for c, name in rows
        ],
    }


@router.get("/entries")
def list_entries(
    authority_id: int,
    business_type_id: int | None = None,
    view: Literal["current", "added", "changed", "missing", "all"] = "current",
    q: str = "",
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    where = [Entry.authority_id == authority_id]
    if business_type_id is not None:
        where.append(Entry.business_type_id == business_type_id)
    if view == "current":
        where.append(Entry.present.is_(True))
    elif view == "missing":
        where.append(Entry.present.is_(False))
    elif view == "added":
        where.extend([Entry.discovery_kind == "added", Entry.present.is_(True)])
    elif view == "changed":
        where.extend([Entry.last_change_kind.in_(["changed", "reappeared"]), Entry.present.is_(True)])
    if q.strip():
        where.append(Entry.name.ilike("%" + q.strip() + "%"))
    total = db.scalar(select(func.count()).select_from(Entry).where(*where)) or 0
    entries = db.scalars(select(Entry).where(*where).order_by(Entry.fhrsid).limit(100).offset((page - 1) * 100))
    return {
        "total": total,
        "items": [
            {
                "fhrsid": e.fhrsid,
                "name": e.name,
                "address": e.data["address"],
                "postcode": e.postcode,
                "business_type_id": e.business_type_id,
                "business_type_name": e.data["raw"].get("BusinessType"),
                "inspection_pending": e.data["raw"].get("RatingValue") == "AwaitingInspection",
                "present": e.present,
                "discovery_kind": e.discovery_kind,
                "last_change_kind": e.last_change_kind,
                "first_seen_at": e.first_seen_at,
                "last_seen_at": e.last_seen_at,
                "last_changed_at": e.last_changed_at,
            }
            for e in entries
        ],
    }
