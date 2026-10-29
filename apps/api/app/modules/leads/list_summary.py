"""名单销售视图摘要：批量读取，避免逐店请求文件和联系方式。"""

import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.leads.models import Lead
from app.modules.menus.models import FetchStatus, MenuAnalysis, MenuAsset
from app.modules.sales.models import ChannelEligibility


def summarize(db: Session, identities: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    result: dict[uuid.UUID, dict[str, Any]] = {
        identity: {"menu_status": "missing", "channels": []} for identity in identities
    }
    if not identities:
        return result
    contacts = db.execute(
        select(ChannelEligibility.lead_id, ChannelEligibility.channel, ChannelEligibility.contact_ref)
        .where(ChannelEligibility.lead_id.in_(identities))
        .distinct()
        .order_by(ChannelEligibility.channel)
    )
    for lead_id, channel, contact_ref in contacts:
        name = channel.value
        if name == "other_social":
            host = (urlparse(contact_ref or "").hostname or "").lower().removeprefix("www.")
            platforms = {"x.com": "X", "twitter.com": "X", "youtube.com": "YouTube", "youtu.be": "YouTube"}
            name = next((v for k, v in platforms.items() if host == k or host.endswith("." + k)), host or "平台待确认")
        if name not in result[lead_id]["channels"]:
            result[lead_id]["channels"].append(name)
    contact_updates = dict(
        db.execute(
            select(ChannelEligibility.lead_id, func.max(ChannelEligibility.updated_at))
            .where(ChannelEligibility.lead_id.in_(identities))
            .group_by(ChannelEligibility.lead_id)
        ).all()
    )
    assets = list(db.scalars(select(MenuAsset).where(MenuAsset.lead_id.in_(identities))))
    analyses = db.scalars(
        select(MenuAnalysis)
        .where(MenuAnalysis.asset_id.in_([a.id for a in assets]))
        .order_by(MenuAnalysis.version.desc())
    )
    latest: dict[uuid.UUID, MenuAnalysis] = {}
    for analysis in analyses:
        latest.setdefault(analysis.asset_id, analysis)
    rank = {
        "missing": 0,
        "failed": 1,
        "fetching": 2,
        "obtained": 3,
        "analysis_failed": 3,
        "analyzing": 4,
        "needs_review": 5,
        "reviewed": 6,
    }
    for asset in assets:
        state = "failed" if asset.fetch_status == FetchStatus.failed else "fetching"
        if asset.fetch_status == FetchStatus.fetched:
            state = "obtained"
            current = latest.get(asset.id)
            if current:
                if current.status in {"succeeded", "needs_review"}:
                    state = "reviewed" if current.review_state == "reviewed" else "needs_review"
                elif current.status == "failed":
                    state = "analysis_failed"
                elif current.status in {"pending", "running"}:
                    state = "analyzing"
        previous = result[asset.lead_id]["menu_status"]
        if rank[state] > rank[previous]:
            result[asset.lead_id]["menu_status"] = state
    for lead in db.scalars(select(Lead).where(Lead.id.in_(identities))):
        summary = result[lead.id]
        raw = lead.raw or {}
        review = raw.get("website_research") or {}
        scan = raw.get("contacts_scan") or {}
        research = raw.get("auto_research") or {}
        own = [a for a in assets if a.lead_id == lead.id]
        fetched = [a for a in own if a.fetch_status == FetchStatus.fetched]
        current = [latest[a.id] for a in fetched if a.id in latest and latest[a.id].input_sha256 == a.sha256]
        website = (
            "done"
            if lead.website and review.get("website") == lead.website and review.get("status") == "verified"
            else "pending"
        )
        if website != "done" and review.get("status") in {"retry", "ai_unavailable"}:
            website = "failed"
        contact = "done" if summary["channels"] else "failed" if scan.get("pages_failed") else "pending"
        menu = (
            "done"
            if fetched
            else "failed"
            if any(a.fetch_status == FetchStatus.failed for a in own)
            else "running"
            if own
            else "pending"
        )
        if (
            not own
            and research.get("status") == "needs_review"
            and research.get("message") == "未发现菜单，需要人工补充"
        ):
            menu = "not_found"
        analysis = "pending"
        if current:
            if any(a.status in {"pending", "running"} for a in current):
                analysis = "running"
            elif any(a.status == "failed" for a in current):
                analysis = "failed"
            elif len(current) == len(fetched) and all(a.status in {"succeeded", "needs_review"} for a in current):
                analysis = "done"
        # Record updates include failed attempts; do not label them successful enrichment.
        updates = [lead.updated_at]
        if contact_updates.get(lead.id):
            updates.append(contact_updates[lead.id])
        updates.extend(a.updated_at for a in own)
        updates.extend(latest[a.id].updated_at for a in own if a.id in latest)
        summary["updated_at"] = max(updates).isoformat()
        summary["activity_times"] = {
            "website": review.get("checked_at"),
            "contacts": scan.get("at"),
            "menus": max((a.fetched_at for a in fetched if a.fetched_at), default=None),
            "analysis": max((a.created_at for a in current), default=None),
        }
        summary["activity_times"] = {
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in summary["activity_times"].items()
        }
        summary["completeness"] = {"website": website, "contacts": contact, "menus": menu, "analysis": analysis}
    return result
