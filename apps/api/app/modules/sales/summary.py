"""D9：成本与批次汇总。统计以去重门店为主；零分母写“不适用”；多渠道结果单列，不相加冒充客户数。"""

import csv
import io
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.content.models import ContentPiece, ContentStatus
from app.modules.leads.models import Batch, BatchLead, Lead, ScreeningClass
from app.modules.menus.models import FetchStatus, MenuAnalysis, MenuAsset
from app.modules.sales.models import (
    ChannelEligibility,
    CostEntry,
    Eligibility,
    Event,
    EventKind,
    ManualTask,
    Suppression,
    SuppressionScope,
    TaskStatus,
)

POSITIVE_INTENTS = {"positive", "quote"}


def _ratio(n: int, d: int) -> dict:
    return {
        "numerator": n,
        "denominator": d,
        "value": round(n / d, 3) if d else None,
        "note": None if d else "不适用（分母为零）",
    }


def _latest_reviewed_confirmed(db: Session, asset_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """返回“最新分析版本已审核且至少一个已确认问题”的 asset_id 集合。"""
    out: set[uuid.UUID] = set()
    for aid in asset_ids:
        a = db.scalar(
            select(MenuAnalysis).where(MenuAnalysis.asset_id == aid).order_by(MenuAnalysis.version.desc()).limit(1)
        )
        if (
            a
            and a.review_state == "reviewed"
            and any(i.get("confirmed") is True and not i.get("deleted") for i in (a.issues or []))
        ):
            out.add(aid)
    return out


def per_lead_rows(db: Session, batch: Batch) -> list[dict]:
    members = db.scalars(
        select(BatchLead).where(BatchLead.batch_id == batch.id).order_by(BatchLead.sample_order.nulls_last())
    ).all()
    rows = []
    for m in members:
        lead = db.get(Lead, m.lead_id)
        assert lead is not None
        assets = db.scalars(select(MenuAsset).where(MenuAsset.lead_id == lead.id)).all()
        fetched = [a for a in assets if a.fetch_status == FetchStatus.fetched]
        confirmed_assets = _latest_reviewed_confirmed(db, [a.id for a in fetched])
        eligs = db.scalars(select(ChannelEligibility).where(ChannelEligibility.lead_id == lead.id)).all()
        suppressed = (
            db.scalar(
                select(Suppression)
                .where(Suppression.scope == SuppressionScope.lead, Suppression.lead_id == lead.id)
                .limit(1)
            )
            is not None
        )
        allowed = [e for e in eligs if e.eligibility == Eligibility.allowed and e.contact_usable != "invalid"]
        tasks = db.scalars(select(ManualTask).where(ManualTask.lead_id == lead.id)).all()
        events = db.scalars(select(Event).where(Event.lead_id == lead.id)).all()
        replies = [e for e in events if e.kind == EventKind.reply]
        intents = {str((e.payload or {}).get("intent") or "unknown") for e in replies}
        approved = (
            db.scalar(
                select(ContentPiece.id)
                .where(ContentPiece.lead_id == lead.id, ContentPiece.status == ContentStatus.approved)
                .limit(1)
            )
            is not None
        )
        rows.append(
            {
                "lead_id": str(lead.id),
                "source_key": lead.source_key,
                "name": lead.name,
                "screening_class": lead.screening_class.value,
                "entity_status": lead.entity_status.value,
                "website": lead.website or "",
                "assets": len(assets),
                "menu_obtained": bool(fetched),
                "asset_kinds": ",".join(sorted({a.kind.value for a in fetched})),
                "issue_confirmed": bool(confirmed_assets),
                "content_approved": approved,
                "channels_allowed": ",".join(sorted({e.channel.value for e in allowed})),
                "suppressed": suppressed,
                "is_candidate": lead.screening_class == ScreeningClass.candidate,
                "contactable": bool(confirmed_assets)
                and lead.screening_class == ScreeningClass.candidate
                and bool(allowed)
                and not suppressed,
                "sent": any(t.status == TaskStatus.sent_manual for t in tasks),
                "sent_channels": ",".join(
                    sorted({t.channel.value for t in tasks if t.status == TaskStatus.sent_manual})
                ),
                "replied": bool(replies),
                "reply_channels": ",".join(sorted({e.channel.value for e in replies if e.channel})),
                "positive": bool(intents & POSITIVE_INTENTS),
                "quote_request": "quote" in intents,
                "rejected": any(e.kind in (EventKind.reject, EventKind.unsubscribe) for e in events),
            }
        )
    return rows


def summarize(db: Session, batch: Batch) -> dict:
    rows = per_lead_rows(db, batch)
    n = len(rows)
    m = sum(r["menu_obtained"] for r in rows)
    i = sum(r["issue_confirmed"] for r in rows)
    e = sum(r["contactable"] for r in rows)
    s = sum(r["sent"] for r in rows)
    r_ = sum(r["replied"] for r in rows)
    p = sum(r["positive"] for r in rows)
    q = sum(r["quote_request"] for r in rows)
    by_channel: dict[str, dict[str, int]] = defaultdict(lambda: {"sent": 0, "replied": 0})
    for r in rows:
        for ch in filter(None, r["sent_channels"].split(",")):
            by_channel[ch]["sent"] += 1
        for ch in filter(None, r["reply_channels"].split(",")):
            by_channel[ch]["replied"] += 1
    costs = db.scalars(select(CostEntry).where(CostEntry.batch_id == batch.id)).all()
    cost_by_cat: dict[str, dict] = defaultdict(
        lambda: {"amount_by_currency": defaultdict(Decimal), "minutes": 0, "entries": 0}
    )
    for c in costs:
        cc = cost_by_cat[c.category.value]
        cc["entries"] += 1
        cc["minutes"] += c.minutes or 0
        if c.amount is not None and c.currency:
            cc["amount_by_currency"][c.currency] += c.amount
    currencies = {c.currency for c in costs if c.amount is not None and c.currency}
    total_amount = sum((c.amount for c in costs if c.amount is not None), Decimal(0))
    total_minutes = sum(c.minutes or 0 for c in costs)
    unit = {
        "currency": next(iter(currencies)) if len(currencies) == 1 else None,
        "cost_per_contactable": (str(round(total_amount / e, 2)) if e and len(currencies) == 1 else None),
        "cost_per_positive": (str(round(total_amount / p, 2)) if p and len(currencies) == 1 else None),
        "minutes_per_candidate": round(total_minutes / n, 1) if n else None,
        "minutes_per_contactable": round(total_minutes / e, 1) if e else None,
        "note": "多币种或分母为零时不计算单位成本" if len(currencies) > 1 or not e else None,
    }
    return {
        "batch_key": batch.batch_key,
        "observation_until": batch.observation_until.isoformat() if batch.observation_until else None,
        "counts": {"N": n, "M": m, "I": i, "E": e, "S": s, "R": r_, "P": p, "Q": q},
        "ratios": {
            "M/N": _ratio(m, n),
            "I/M": _ratio(i, m),
            "E/N": _ratio(e, n),
            "R/S": _ratio(r_, s),
            "P/S": _ratio(p, s),
            "Q/S": _ratio(q, s),
        },
        "by_channel": dict(by_channel),
        "costs": {
            k: {
                "amount_by_currency": {cur: str(v) for cur, v in d["amount_by_currency"].items()},
                "minutes": d["minutes"],
                "entries": d["entries"],
            }
            for k, d in cost_by_cat.items()
        },
        "unit_costs": unit,
        "commercial_status": "未验证（无实际触达）" if s == 0 else "观测中，见 observation_until",
    }


def export_csv(db: Session, batch: Batch) -> str:
    rows = per_lead_rows(db, batch)
    buf = io.StringIO()
    if not rows:
        return ""
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
