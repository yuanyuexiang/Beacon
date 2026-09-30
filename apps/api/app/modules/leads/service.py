"""导入逻辑：稳定来源键；同批次同键重导不新增；已存在门店跨批次关联；坏行逐条记录；不按店名合并不同地址。"""

import csv
import hashlib
import io
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.leads.models import Batch, BatchLead, ImportRun, Lead, ScreeningClass

REQUIRED_ANY_KEY = ("source_key", "source_id", "fhrsid")
OPTIONAL = ("address", "postcode", "lat", "lng", "website", "sample_order", "screening_class", "screening_reason")


def _source_key(row: dict[str, str], default_source: str) -> tuple[str, str]:
    if row.get("source_key"):
        key = row["source_key"].strip()
        if ":" not in key:
            raise ValueError("source_key 必须形如 <source>:<id>")
        return key.split(":", 1)[0], key
    if row.get("fhrsid"):
        return "fsa", f"fsa:{row['fhrsid'].strip()}"
    if row.get("source_id"):
        src = (row.get("source_name") or default_source).strip()
        return src, f"{src}:{row['source_id'].strip()}"
    raise ValueError("缺少 source_key / fhrsid / source_id")


def _float(v: str | None) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def import_csv(db: Session, batch: Batch, content: bytes, file_name: str | None, operator: str | None) -> ImportRun:
    sha = hashlib.sha256(content).hexdigest()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    run = ImportRun(
        batch_id=batch.id,
        file_name=file_name,
        file_sha256=sha,
        operator=operator,
        errors=[],
        row_count=0,
        created_count=0,
        linked_count=0,
        skipped_count=0,
        error_count=0,
    )
    seen_in_file: set[str] = set()
    errors: list[dict] = []
    existing_members = {m.lead_id for m in db.scalars(select(BatchLead).where(BatchLead.batch_id == batch.id)).all()}
    for idx, row in enumerate(reader, start=2):  # 第 1 行是表头
        run.row_count += 1
        try:
            name = (row.get("name") or row.get("business_name") or "").strip()
            if not name:
                raise ValueError("缺少 name")
            src, key = _source_key(row, batch.source_name)
            if key in seen_in_file:
                raise ValueError(f"文件内重复来源键 {key}")
            seen_in_file.add(key)
            lat, lng = _float(row.get("lat")), _float(row.get("lng"))
            order = int(row["sample_order"]) if (row.get("sample_order") or "").strip() else None
            sc = row.get("screening_class")
            screening = ScreeningClass(sc.strip()) if sc and sc.strip() else None
        except Exception as e:
            errors.append({"row": idx, "reason": str(e)})
            continue
        lead = db.scalar(select(Lead).where(Lead.source_key == key))
        if lead is None:
            lead = Lead(
                source_key=key,
                source_name=src,
                name=name,
                address=(row.get("address") or None),
                postcode=(row.get("postcode") or None),
                lat=lat,
                lng=lng,
                website=(row.get("website") or None),
                screening_class=screening or ScreeningClass.unchecked,
                screening_reason=(row.get("screening_reason") or None),
            )
            db.add(lead)
            db.flush()
            run.created_count += 1
        elif lead.id in existing_members:
            run.skipped_count += 1
            continue
        else:
            run.linked_count += 1
        db.add(BatchLead(batch_id=batch.id, lead_id=lead.id, sample_order=order))
        existing_members.add(lead.id)
    run.error_count = len(errors)
    run.errors = errors
    db.add(run)
    batch.candidate_count = len(existing_members)
    db.commit()
    db.refresh(run)
    return run


def get_batch_by_key(db: Session, batch_key: str) -> Batch | None:
    return db.scalar(select(Batch).where(Batch.batch_key == batch_key))


def list_leads(db: Session, batch_id: uuid.UUID | None, screening: ScreeningClass | None, limit: int, offset: int):
    q = select(Lead)
    if batch_id is not None:
        q = q.join(BatchLead, BatchLead.lead_id == Lead.id).where(BatchLead.batch_id == batch_id)
        q = q.order_by(BatchLead.sample_order.nulls_last(), Lead.name)
    else:
        q = q.order_by(Lead.name)
    if screening is not None:
        q = q.where(Lead.screening_class == screening)
    return db.scalars(q.limit(limit).offset(offset)).all()
