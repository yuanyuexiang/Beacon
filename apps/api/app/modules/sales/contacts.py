"""联系方式查找与记录：官网页面 + 已存的 Overture 数据 → 候选；人工勾选后记为渠道准入行。
记录只表示“找到了这个联系方式及其来源”：可用性与准入都保持 unknown，不放行任何渠道，也不覆盖已有的审核结果。"""

import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations import website_contacts as wc
from app.modules.leads.entity import site_fetch
from app.modules.leads.models import Lead
from app.modules.sales import service
from app.modules.sales.models import Channel, ChannelEligibility, ContactUsable, Eligibility

KIND_CHANNEL = {
    "email": Channel.email,
    "phone": Channel.phone,
    "whatsapp": Channel.whatsapp,
    "instagram": Channel.instagram,
    "facebook": Channel.facebook,
    "tiktok": Channel.tiktok,
    "x": Channel.other_social,
    "linkedin": Channel.other_social,
    "youtube": Channel.other_social,
    "contact_form": Channel.contact_form,
}
KIND_ORDER = list(KIND_CHANNEL)
NOTICE = (
    "候选仅供人工核对：页面里可能有建站公司、订位平台等第三方的联系方式，Overture 匹配到的也可能是相邻门店。"
    "记录不等于允许使用：邮件看主体类型，电话核对 TPS/CTPS，WhatsApp 需 opt-in 证据，社媒与联系表单当前暂缓。"
)


def find_contacts(db: Session, lead: Lead, web_transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """只读：不写库。官网抓取失败只记录在 website.pages。"""
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def add(kind: str, value: str, source_type: str, ref: str) -> None:
        cur = found.setdefault(
            (kind, value),
            {"kind": kind, "channel": KIND_CHANNEL[kind].value, "value": value, "sources": []},
        )
        if not any(s["type"] == source_type for s in cur["sources"]):
            cur["sources"].append({"type": source_type, "ref": ref})

    website = None
    if lead.website:
        website = wc.scan(lead.website, site_fetch(web_transport))
        for c in website.pop("contacts"):
            add(c["kind"], c["value"], "website", c["page_url"])

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
