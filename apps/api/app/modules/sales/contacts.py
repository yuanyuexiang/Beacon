"""联系方式查找与记录：官网页面 + 已存的 Overture 数据 → 候选；人工勾选后记为渠道准入行。
记录只表示“找到了这个联系方式及其来源”：可用性与准入都保持 unknown，不放行任何渠道，也不覆盖已有的审核结果。"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations import website_contacts as wc
from app.modules.leads.entity import site_fetch
from app.modules.leads.models import Lead
from app.modules.sales import contact_ranking, service
from app.modules.sales.models import Channel, ChannelEligibility, ContactUsable, Eligibility

KIND_CHANNEL = {
    "email": Channel.email,
    "phone": Channel.phone,
    "whatsapp": Channel.whatsapp,
    "instagram": Channel.instagram,
    "facebook": Channel.facebook,
    "tiktok": Channel.tiktok,
    "x": Channel.other_social,
    "linkedin": Channel.linkedin,
    "youtube": Channel.other_social,
    "contact_form": Channel.contact_form,
}
KIND_ORDER = list(KIND_CHANNEL)
NOTICE = (
    "AI 推荐依据官网原文判断归属与用途，不代表联系方式有效或已获准触达。"
    "候选、旧记录与渠道准入分别保留；证据不足时不自动推荐，可展开全部候选人工选择。"
)


SCAN_WORKERS = 8  # 批量时同时读多少个站点


def scan_website(website: str, web_transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """读一个官网并提取联系方式。只有网络访问，不接触数据库，可在线程里调用。"""
    return wc.scan(website, site_fetch(web_transport))


def scan_websites(urls: list[str]) -> dict[str, dict[str, Any] | Exception]:
    """并行读多个官网：不同站点同时进行；同一主机的多个地址排队，不对单个站点并发加压；相同地址只读一次。
    单个站点出错不影响其余，错误作为该地址的结果返回。"""
    unique = list(dict.fromkeys(urls))
    if not unique:
        return {}
    locks = {(urlparse(u).hostname or u).lower(): threading.Lock() for u in unique}

    def one(url: str) -> dict[str, Any] | Exception:
        with locks[(urlparse(url).hostname or url).lower()]:
            try:
                return scan_website(url)
            except Exception as e:
                return e

    with ThreadPoolExecutor(max_workers=min(SCAN_WORKERS, len(unique))) as pool:
        return dict(zip(unique, pool.map(one, unique), strict=True))


def find_contacts(db: Session, lead: Lead, website_scan: dict[str, Any] | None = None) -> dict[str, Any]:
    """只读：不写库。官网抓取失败只记录在 website.pages。website_scan 为已读好的官网结果（批量并行时传入）。"""
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def add(kind: str, value: str, source_type: str, ref: str) -> None:
        cur = found.setdefault(
            (kind, value),
            {
                "id": contact_ranking.candidate_id(kind, value),
                "kind": kind,
                "channel": KIND_CHANNEL[kind].value,
                "value": value,
                "sources": [],
                "evidence": [],
            },
        )
        if not any(s["type"] == source_type and s["ref"] == ref for s in cur["sources"]):
            cur["sources"].append({"type": source_type, "ref": ref})

    website = None
    if lead.website:
        website = dict(website_scan) if website_scan is not None else scan_website(lead.website)
        for c in website.pop("contacts"):
            add(c["kind"], c["value"], "website", c["page_url"])
            cur = found[(c["kind"], c["value"])]
            for evidence in c.get("evidence") or []:
                if evidence not in cur["evidence"]:
                    cur["evidence"].append(evidence)
                    add(c["kind"], c["value"], "website", evidence["page_url"])

    ov = (lead.raw or {}).get("overture") or {}
    if ov.get("matched"):
        ref = f"overture:{ov.get('place_id')}（名称相似度 {ov.get('similarity')}，距离 {ov.get('distance_m')} 米）"
        for phone in ov.get("phones") or []:
            add("phone", wc.normalize_uk_phone(phone) or str(phone).strip(), "overture", ref)
        for url in ov.get("socials") or []:
            hit = wc.classify_link(url)
            if hit:
                add(*hit, "overture", ref)

    recorded = {
        (row.channel.value, row.contact_ref): row
        for row in db.scalars(select(ChannelEligibility).where(ChannelEligibility.lead_id == lead.id)).all()
    }
    out = sorted(found.values(), key=lambda c: KIND_ORDER.index(c["kind"]))
    for c in out:
        c["assessment"] = contact_ranking.stored(lead, c["channel"], c["value"]) or contact_ranking.pending()
        c["personal"] = c["kind"] == "email" and wc.is_personal_email(c["value"])
        c["mobile"] = c["kind"] in ("phone", "whatsapp") and c["value"].startswith("+447")
        row = recorded.get((c["channel"], c["value"]))
        c["recorded"] = row is not None
        c["eligibility"] = row.eligibility.value if row else None
        c["suppressed"] = service.is_suppressed(db, lead.id, c["value"]) is not None
    return {"checked_at": service.now().isoformat(), "website": website, "candidates": out, "notice": NOTICE}


def record_contacts(db: Session, lead_id: uuid.UUID, items: list[dict[str, Any]]) -> dict[str, int]:
    """把人工勾选的联系方式记为渠道准入行：只新增，已存在的（含已审核过的）一律跳过，不改其状态。"""
    created = skipped = 0
    for item in items:
        channel, ref = Channel(item["channel"]), item["contact_ref"].strip()
        exists = db.scalar(
            select(ChannelEligibility.id).where(
                ChannelEligibility.lead_id == lead_id,
                ChannelEligibility.channel == channel,
                ChannelEligibility.contact_ref == ref,
            )
        )
        if exists or not ref:
            skipped += 1
            continue
        db.add(
            ChannelEligibility(
                lead_id=lead_id,
                channel=channel,
                contact_ref=ref,
                contact_source=(item.get("contact_source") or "")[:256] or None,
                contact_collected_at=service.now(),
                contact_usable=ContactUsable.unknown,
                eligibility=Eligibility.unknown,
            )
        )
        db.flush()
        created += 1
    return {"created": created, "skipped": skipped}


def review_contacts(db: Session, lead: Lead, website_scan: dict[str, Any] | None = None) -> dict[str, Any]:
    """显式 AI 操作，保存推荐证据，网络期间发生门店修改则不落档。"""
    from app.modules.leads import website_review
    from app.modules.leads.google_places import _lead

    original = website_review.snapshot(lead)
    found = find_contacts(db, lead, website_scan)
    meta = contact_ranking.rank(lead, found)
    locked = _lead(db, lead.id, lock=True)
    if website_review.snapshot(locked) != original:
        raise ValueError("查找期间门店或官网发生变化，已保留最新资料，请重新查找")
    found["ai"] = meta
    found["candidates"].sort(key=lambda c: contact_ranking.RANK[c["assessment"]["recommendation"]])
    locked.raw = {
        **(locked.raw or {}),
        "contact_review": {**meta, "website": locked.website, "candidates": found["candidates"]},
    }
    return found


def collect(db: Session, lead: Lead, website_scan: dict[str, Any] | None = None) -> dict[str, Any]:
    """批量仅记录经过原文校验的 AI 推荐项；备选和不确定项保留，不改变既有准入。"""
    found = review_contacts(db, lead, website_scan)
    items, held = [], 0
    for c in found["candidates"]:
        if c["recorded"] or c["suppressed"] or service.is_suppressed(db, lead.id, c["value"]):
            continue
        if c["assessment"]["recommendation"] != "recommended":
            held += 1
            continue
        source = "；".join(f"官网 {s['ref']}" if s["type"] == "website" else s["ref"] for s in c["sources"])
        items.append({"channel": c["channel"], "contact_ref": c["value"], "contact_source": source})
    result = record_contacts(db, lead.id, items) if items else {"created": 0, "skipped": 0}
    pages = (found["website"] or {}).get("pages") or []
    scan = {
        "at": found["checked_at"],
        "found": len(found["candidates"]),
        "recorded": result["created"],
        "held_for_review": held,
        "pages_ok": sum(1 for p in pages if p["ok"]),
        "pages_failed": sum(1 for p in pages if not p["ok"]),
        "website": lead.website,
        "ai_status": found["ai"]["status"],
        "ai_reason": found["ai"]["reason"],
        "ranking_version": contact_ranking.VERSION,
        "recommended": sum(c["assessment"]["recommendation"] == "recommended" for c in found["candidates"]),
        "page_errors": [{"url": p["url"], "error": p.get("error") or "页面读取失败"} for p in pages if not p["ok"]],
    }
    lead.raw = {**(lead.raw or {}), "contacts_scan": scan}
    return scan
