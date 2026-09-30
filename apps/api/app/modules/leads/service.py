"""导入逻辑：稳定来源键；同批次同键重导不新增；已存在门店跨批次关联；坏行逐条记录；不按店名合并不同地址。"""

import csv
import hashlib
import io
import json
import re
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


# ---------- 来源同步：FSA ----------


def sync_fsa(
    db: Session,
    batch: Batch,
    authority_id: int,
    business_type_id: int = 1,
    exclude_awaiting: bool = True,
    sample_n: int | None = None,
    seed: int | None = None,
    operator: str | None = None,
    transport=None,
) -> dict:
    """从 FSA 拉取地方当局的经营者，去重后加入批次；可选固定种子抽样。返回计数与来源版本。"""
    import random

    from app.integrations import fsa

    page = fsa.fetch_establishments(authority_id, business_type_id, transport=transport)
    rows = [fsa.to_lead_row(e) for e in page.establishments]
    if exclude_awaiting:
        rows = [r for r in rows if r["raw"].get("RatingValue") != "AwaitingInspection"]
    rows.sort(key=lambda r: r["source_key"])
    pool = len(rows)
    if sample_n is not None and sample_n < len(rows):
        rows = random.Random(seed if seed is not None else 0).sample(rows, sample_n)
    existing_members = {m.lead_id for m in db.scalars(select(BatchLead).where(BatchLead.batch_id == batch.id)).all()}
    created = linked = skipped = 0
    for i, r in enumerate(rows, 1):
        lead = db.scalar(select(Lead).where(Lead.source_key == r["source_key"]))
        if lead is None:
            lead = Lead(
                source_key=r["source_key"],
                source_name="fsa",
                name=r["name"],
                address=r["address"],
                postcode=r["postcode"],
                lat=r["lat"],
                lng=r["lng"],
                screening_class=ScreeningClass.unchecked,
                raw=r["raw"],
            )
            db.add(lead)
            db.flush()
            created += 1
        elif lead.id in existing_members:
            skipped += 1
            continue
        else:
            linked += 1
        db.add(BatchLead(batch_id=batch.id, lead_id=lead.id, sample_order=i))
        existing_members.add(lead.id)
    batch.source_name = "fsa"
    batch.source_version = page.extract_date
    batch.source_licence = batch.source_licence or "OGL-3.0"
    batch.sampling_method = (
        f"FSA localAuthorityId={authority_id} businessTypeId={business_type_id}"
        + ("，排除 AwaitingInspection" if exclude_awaiting else "")
        + (f"，按 source_key 排序后 random.Random({seed}).sample({sample_n})" if sample_n else "，全量")
    )
    batch.sampling_seed = seed
    batch.candidate_count = len(existing_members)
    db.add(
        ImportRun(
            batch_id=batch.id,
            file_name=f"fsa:{authority_id}:{business_type_id}",
            file_sha256=hashlib.sha256(json.dumps([r["source_key"] for r in rows]).encode()).hexdigest(),
            operator=operator,
            errors=[],
            row_count=len(rows),
            created_count=created,
            linked_count=linked,
            skipped_count=skipped,
            error_count=0,
        )
    )
    db.commit()
    return {
        "fetched": page.total,
        "pool": pool,
        "selected": len(rows),
        "created": created,
        "linked": linked,
        "skipped": skipped,
        "source_version": page.extract_date,
    }


# ---------- 补全：Overture ----------


def batch_bbox(db: Session, batch: Batch, margin: float = 0.01) -> tuple[float, float, float, float] | None:
    leads = list_leads(db, batch.id, None, 5000, 0)
    pts = [(lead.lng, lead.lat) for lead in leads if lead.lat is not None and lead.lng is not None]
    if not pts:
        return None
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    return (min(lons) - margin, min(lats) - margin, max(lons) + margin, max(lats) + margin)


def enrich_overture(
    db: Session, batch: Batch, max_m: float = 200, min_sim: float = 0.5, overwrite: bool = False, places=None
) -> dict:
    """用 Overture Places 为批次内门店补官网/电话/社交。
    只填空缺（overwrite=False）；来源写入 website_source 与 raw.overture。"""
    from datetime import UTC, datetime

    from app.core.config import get_settings
    from app.integrations import overture

    bbox = batch_bbox(db, batch)
    if bbox is None:
        return {"leads": 0, "matched": 0, "website_set": 0, "note": "批次内没有坐标"}
    if places is None:
        path = overture.ensure_places(bbox, get_settings().data_dir)
        places = overture.load_places(path)
    leads = list_leads(db, batch.id, None, 5000, 0)
    matched = website_set = phone_set = 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for lead in leads:
        if lead.lat is None or lead.lng is None:
            continue
        m = overture.match(lead.name, lead.lat, lead.lng, places, max_m, min_sim)
        raw = dict(lead.raw or {})
        if m is None:
            raw["overture"] = {"matched": False, "checked_at": now}
            lead.raw = raw
            continue
        matched += 1
        raw["overture"] = {**m, "matched": True, "checked_at": now, "licence": "CDLA-Permissive-2.0"}
        lead.raw = raw
        if m["websites"] and (overwrite or not lead.website):
            lead.website = m["websites"][0]
            lead.website_source = (
                f"overture:{m['place_id']} sim={m['similarity']} "
                f"dist={m['distance_m']}m conf={m['confidence']} at={now}"
            )
            website_set += 1
        if m["phones"]:
            phone_set += 1
    db.commit()
    return {
        "leads": len(leads),
        "matched": matched,
        "website_set": website_set,
        "phone_found": phone_set,
        "bbox": bbox,
        "places": len(places),
    }


# ---------- 自动筛选（名称规则 + Overture 品牌） ----------

SCREEN_RULES_VERSION = "name-rule-v1"
CAFE_WORDS = re.compile(
    r"\b(cafe|caf\u00e9|coffee|tearoom|tea room|espresso|bakery|patisserie|deli|juice|bubble tea)\b", re.I
)
CHAIN_NAMES = [
    "starbucks",
    "costa",
    "caffe nero",
    "pret",
    "greggs",
    "nando",
    "pizza express",
    "franco manca",
    "itsu",
    "wagamama",
    "leon",
    "five guys",
    "mcdonald",
    "kfc",
    "subway",
    "burger king",
    "pizza hut",
    "domino",
    "wasabi",
    "gail's",
    "gails",
    "taco bell",
    "chilango",
    "amorino",
    "wetherspoon",
    "zizzi",
    "prezzo",
    "byron",
    "honest burgers",
    "dishoom",
    "tortilla",
    "chipotle",
    "shake shack",
    "pizza pilgrims",
    "rosa's thai",
    "wingstop",
    "popeyes",
    "tim hortons",
    "black sheep coffee",
    "joe & the juice",
    "muffin break",
    "breakfast club",
    "bird & blend",
    "bird and blend",
    "the salad kitchen",
]
INSTITUTION_WORDS = re.compile(
    r"\b(school|college|university|hospital|nursery|care home|church|mosque|community|charity|canteen|staff)\b", re.I
)
PUB_WORDS = re.compile(r"\b(pub|tavern|arms|inn)\b", re.I)


def auto_screen(db: Session, batch: Batch, only_unchecked: bool = True) -> dict:
    """按名称规则与 Overture brand 给出筛选建议：咖啡店/连锁/机构/酒吧标为排除，其余保持 unchecked 交人工。
    只改未筛选的记录。"""
    counts: dict[str, int] = {}
    for lead in list_leads(db, batch.id, None, 5000, 0):
        if only_unchecked and lead.screening_class != ScreeningClass.unchecked:
            continue
        name = lead.name or ""
        brand = ((lead.raw or {}).get("overture") or {}).get("brand")
        cls, why = None, None
        low = name.lower()
        if any(c in low for c in CHAIN_NAMES):
            cls, why = ScreeningClass.excluded_chain, f"{SCREEN_RULES_VERSION}: 名称匹配连锁清单"
        elif brand:
            cls, why = ScreeningClass.excluded_chain, f"{SCREEN_RULES_VERSION}: Overture brand={brand}"
        elif INSTITUTION_WORDS.search(name):
            cls, why = ScreeningClass.excluded_institution, f"{SCREEN_RULES_VERSION}: 名称含机构/社区词"
        elif CAFE_WORDS.search(name):
            cls, why = ScreeningClass.excluded_cafe, f"{SCREEN_RULES_VERSION}: 名称含咖啡店词（可能误杀，人工可改）"
        elif PUB_WORDS.search(name):
            cls, why = ScreeningClass.excluded_pub, f"{SCREEN_RULES_VERSION}: 名称含酒吧词"
        if cls is not None:
            lead.screening_class = cls
            lead.screening_reason = why
            counts[cls.value] = counts.get(cls.value, 0) + 1
        else:
            counts["unchecked"] = counts.get("unchecked", 0) + 1
    db.commit()
    return {"rules": SCREEN_RULES_VERSION, "counts": counts}
