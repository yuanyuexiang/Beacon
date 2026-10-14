"""原子更新来源池；后台串行同步，失败保留最后成功快照。"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.integrations import fsa
from app.modules.directory.models import Authority, Change, Entry, Region, SyncRun
from app.modules.leads.models import Batch, BatchLead, ImportRun, Lead, ScreeningClass

TYPE_IDS = {1, 7843, 7844}
WORKER_LOCK = 0x424541434F4E57


def utcnow() -> datetime:
    return datetime.now(UTC)


def refresh_authorities(db: Session) -> int:
    rows = fsa.list_authorities()
    if not rows:
        raise ValueError("FSA 地区名录为空，保留已有地区")
    for row in rows:
        item = db.get(Authority, row["id"])
        if item is None:
            item = Authority(authority_id=row["id"], name=row["name"])
            db.add(item)
        item.name, item.region, item.establishment_count = row["name"], row["region"], row["count"]
    db.commit()
    return len(rows)


def enqueue(db: Session, authority_id: int, trigger: str = "manual") -> SyncRun:
    region = db.scalar(select(Region).where(Region.authority_id == authority_id).with_for_update())
    if region is None:
        raise HTTPException(404, "地区未加入门店池")
    existing = db.scalar(
        select(SyncRun).where(SyncRun.authority_id == authority_id, SyncRun.status.in_(["queued", "running"]))
    )
    if existing:
        if region.auto_sync and (region.next_sync_at is None or region.next_sync_at <= utcnow()):
            region.next_sync_at = utcnow() + timedelta(hours=region.interval_hours)
            db.commit()
        return existing
    run = SyncRun(authority_id=authority_id, business_type_ids=list(region.business_type_ids), trigger=trigger)
    db.add(run)
    if region.auto_sync:
        region.next_sync_at = utcnow() + timedelta(hours=region.interval_hours)
    db.commit()
    db.refresh(run)
    return run


def schedule_due(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    ids = list(db.scalars(select(Region.authority_id).where(Region.auto_sync.is_(True), Region.next_sync_at <= now)))
    for authority_id in ids:
        enqueue(db, authority_id, "scheduled")
    return len(ids)


def apply_snapshot(db: Session, run: SyncRun, pages: dict[int, fsa.FsaPage], now: datetime | None = None) -> dict:
    now = now or utcnow()
    region = db.get(Region, run.authority_id)
    assert region is not None
    # 必须完整读取全部请求类型后，才能判断本次未发现；任何异常均不更新池。
    if set(pages) != set(run.business_type_ids):
        raise ValueError("同步范围不完整，保留上次成功的门店池")
    authority = db.get(Authority, region.authority_id)
    expected_name = (authority.name if authority else region.name).strip().casefold()
    rows = {}
    for type_id, page in pages.items():
        if len(page.establishments) != page.total:
            raise ValueError("FSA 分页结果不完整，保留上次成功的门店池")
        for raw in page.establishments:
            if raw.get("BusinessTypeID") != type_id:
                raise ValueError("FSA 返回类型不一致，保留门店池")
            source_authority = raw.get("LocalAuthorityName")
            if source_authority and str(source_authority).strip().casefold() != expected_name:
                raise ValueError("FSA 返回了其他地区的记录，保留门店池")
            identity = raw.get("FHRSID")
            if not isinstance(identity, int) or identity <= 0 or identity in rows:
                raise ValueError("FSA 来源 ID 缺失或重复，保留门店池")
            data = fsa.to_lead_row(raw)
            if not data["name"]:
                raise ValueError("FSA 门店名称为空，保留门店池")
            rows[identity] = (type_id, data, raw)
    baseline_types = {type_id for type_id in pages if str(type_id) not in region.type_versions}
    old_scope = list(
        db.scalars(
            select(Entry).where(
                Entry.authority_id == region.authority_id, Entry.business_type_id.in_(run.business_type_ids)
            )
        )
    )
    existing = {entry.fhrsid: entry for entry in db.scalars(select(Entry).where(Entry.fhrsid.in_(rows))).all()}
    counts = {key: 0 for key in ("baseline", "added", "changed", "missing", "reappeared", "unchanged")}
    for identity, (type_id, data, raw) in rows.items():
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        entry = existing.get(identity)
        diff = {}
        if entry is None:
            kind = "baseline" if type_id in baseline_types else "added"
            entry = Entry(
                fhrsid=identity,
                authority_id=region.authority_id,
                business_type_id=type_id,
                name=data["name"],
                data=data,
                raw=raw,
                fingerprint=fingerprint,
                discovery_kind=kind,
                last_change_kind=kind,
                first_seen_at=now,
                last_seen_at=now,
                last_changed_at=now,
                last_seen_run_id=run.id,
            )
            db.add(entry)
        else:
            if not entry.present:
                kind = "reappeared"
            elif entry.fingerprint != fingerprint or entry.authority_id != region.authority_id:
                kind = "changed"
            else:
                kind = "unchanged"
            if kind != "unchanged":
                diff = {
                    key: {"before": entry.data.get(key), "after": value}
                    for key, value in data.items()
                    if entry.data.get(key) != value
                }
                if entry.authority_id != region.authority_id:
                    diff["authority_id"] = {"before": entry.authority_id, "after": region.authority_id}
                entry.last_change_kind, entry.last_changed_at = kind, now
        counts[kind] += 1
        entry.authority_id, entry.business_type_id = region.authority_id, type_id
        entry.name, entry.postcode = data["name"], data["postcode"]
        entry.data, entry.raw, entry.fingerprint = data, raw, fingerprint
        entry.present, entry.last_seen_at, entry.last_seen_run_id = True, now, run.id
        db.flush()
        if kind != "unchanged":
            db.add(Change(sync_id=run.id, fhrsid=identity, kind=kind, changed_at=now, diff=diff))
    for entry in old_scope:
        if entry.fhrsid not in rows and entry.present:
            entry.present = False
            entry.last_change_kind, entry.last_changed_at = "missing", now
            counts["missing"] += 1
            db.add(Change(sync_id=run.id, fhrsid=entry.fhrsid, kind="missing", changed_at=now, diff={}))
    versions = {
        str(t): {"extract_date": page.extract_date, "synced_at": now.isoformat(), "sync_id": str(run.id)}
        for t, page in pages.items()
    }
    region.type_versions = {**region.type_versions, **versions}
    region.last_success_at = now
    run.status, run.finished_at, run.error = "completed", now, None
    run.counts, run.source_versions = {**counts, "total": len(rows)}, versions
    # 当前原文仅保存一份，详细变更保留 180 天；同步摘要不含原文。
    db.execute(delete(Change).where(Change.changed_at < now - timedelta(days=180)))
    db.commit()
    return run.counts


def tick(db: Session) -> bool:
    # API 只排队；专用连接锁保证多 worker 和重启恢复均只有一个同步执行者。
    engine = db.get_bind()
    with engine.connect() as connection:  # type: ignore[union-attr]
        if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK}):
            return False
        try:
            schedule_due(db)
            run = db.scalar(
                select(SyncRun)
                .where(SyncRun.status.in_(["queued", "running"]))
                .order_by(SyncRun.created_at, SyncRun.id)
                .limit(1)
            )
            if run is None:
                return False
            run.status, run.started_at, run.error = "running", utcnow(), None
            db.commit()
            try:
                pages = {
                    type_id: fsa.fetch_establishments(run.authority_id, type_id) for type_id in run.business_type_ids
                }
                apply_snapshot(db, run, pages)
            except Exception as exc:
                db.rollback()
                db.refresh(run)
                run.status, run.finished_at = "failed", utcnow()
                run.error = (
                    str(exc)[:1500]
                    if isinstance(exc, (ValueError, fsa.FsaConnectionError))
                    else "同步未完成，已保留上次成功数据；请稍后重试"
                )
                region = db.get(Region, run.authority_id)
                if region and region.auto_sync:
                    region.next_sync_at = utcnow() + timedelta(hours=1)
                db.commit()
            return True
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK})
            connection.commit()


def require_pool(db: Session, authority_id: int, type_ids: list[int]) -> Region:
    region = db.get(Region, authority_id)
    if region is None or not all(str(t) in region.type_versions for t in type_ids):
        raise HTTPException(409, "所选类型尚未同步到门店池，请先到「门店池」同步该地区；已有名单保留")
    return region


def add_to_batch(
    db: Session,
    batch: Batch,
    authority_id: int,
    type_ids: list[int],
    exclude_awaiting: bool = False,
    limit: int | None = None,
    operator: str | None = None,
) -> dict:
    region = require_pool(db, authority_id, type_ids)
    if region.name != batch.region:
        raise ValueError("门店池地区与目标名单不一致")
    entries = list(
        db.scalars(
            select(Entry)
            .where(Entry.authority_id == authority_id, Entry.business_type_id.in_(type_ids), Entry.present.is_(True))
            .order_by(Entry.fhrsid)
        )
    )
    if exclude_awaiting:
        entries = [e for e in entries if e.data["raw"].get("RatingValue") != "AwaitingInspection"]
    existing_members = {m.lead_id for m in db.scalars(select(BatchLead).where(BatchLead.batch_id == batch.id))}
    existing_keys = (
        set(db.scalars(select(Lead.source_key).where(Lead.id.in_(existing_members)))) if existing_members else set()
    )
    fetched = len(entries)
    already = sum(e.data["source_key"] in existing_keys for e in entries)
    entries = [e for e in entries if e.data["source_key"] not in existing_keys]
    pool = len(entries)
    if limit is not None:
        entries = entries[:limit]
    order = db.scalar(select(func.max(BatchLead.sample_order)).where(BatchLead.batch_id == batch.id)) or 0
    created = linked = 0
    for entry in entries:
        data = entry.data
        lead = db.scalar(select(Lead).where(Lead.source_key == data["source_key"]))
        if lead is None:
            # 不同名单同时选中同一来源门店时，仅新建一个 Lead，不覆盖已有人工字段。
            inserted_id = db.scalar(
                insert(Lead)
                .values(
                    source_key=data["source_key"],
                    source_name="fsa",
                    name=data["name"],
                    address=data["address"],
                    postcode=data["postcode"],
                    lat=data["lat"],
                    lng=data["lng"],
                    raw=data["raw"],
                    screening_class=ScreeningClass.unchecked,
                )
                .on_conflict_do_nothing(index_elements=[Lead.source_key])
                .returning(Lead.id)
            )
            lead = db.scalar(select(Lead).where(Lead.source_key == data["source_key"]))
            assert lead is not None
            if inserted_id is not None:
                created += 1
            else:
                linked += 1
        else:
            linked += 1  # 已有线索的人工字段、官网、分析、联系方式都不覆盖。
        order += 1
        db.add(
            BatchLead(
                batch_id=batch.id,
                lead_id=lead.id,
                sample_order=order,
                source_snapshot={
                    **data,
                    "sync_id": str(entry.last_seen_run_id),
                    "fhrsid": entry.fhrsid,
                    "authority_id": authority_id,
                },
                source_synced_at=entry.last_seen_at,
            )
        )
        existing_members.add(lead.id)
    previous_types = {
        int(t) for t in (batch.business_type or "").removeprefix("fsa:").split(",") if t in {"1", "7843", "7844"}
    }
    batch.business_type = "fsa:" + ",".join(map(str, sorted(previous_types | set(type_ids))))
    batch.source_name, batch.source_licence = "fsa", "OGL-3.0"
    batch.source_version = region.last_success_at.isoformat() if region.last_success_at else None
    batch.sampling_method = (
        f"FSA 门店池 localAuthorityId={authority_id} businessTypeIds={type_ids}；全量／稳定顺序；成员来源快照保留"
    )
    batch.sampling_seed, batch.candidate_count = None, len(existing_members)
    db.add(
        ImportRun(
            batch_id=batch.id,
            file_name=f"directory:{authority_id}",
            file_sha256=hashlib.sha256(json.dumps([e.fhrsid for e in entries]).encode()).hexdigest(),
            operator=operator,
            row_count=len(entries),
            created_count=created,
            linked_count=linked,
            skipped_count=0,
            error_count=0,
            errors=[],
        )
    )
    return {
        "fetched": fetched,
        "pool": pool,
        "already_in_list": already,
        "selected": len(entries),
        "created": created,
        "linked": linked,
        "skipped": 0,
        "directory_synced_at": region.last_success_at.isoformat() if region.last_success_at else None,
        "business_type_ids": type_ids,
    }
