"""名单销售视图摘要：批量读取，避免逐店请求文件和联系方式。"""

import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    return result
