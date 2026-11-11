"""来源网站直接使用；保留人工修改与来源历史，不依赖身份 AI 核验。"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import Operator
from app.integrations import google_places as google
from app.modules.leads import google_places, policy, service, website_review
from app.modules.leads.models import Batch, Lead

if TYPE_CHECKING:
    from app.modules.leads.workflows import Workflow


def fresh(lead: Lead, days: int) -> bool:
    record = (lead.raw or {}).get("source_sync") or {}
    try:
        return (
            record.get("status") == "completed"
            and record.get("fingerprint") == google_places._fingerprint(lead)
            and datetime.now(UTC) - datetime.fromisoformat(record["fetched_at"]) < timedelta(days=days)
        )
    except (KeyError, ValueError, TypeError):
        return False


def apply_saved(lead: Lead) -> bool:
    """Adopt the source's primary website without claiming identity verification."""
    raw = dict(lead.raw or {})
    record = raw.get("source_sync") or {}
    if record.get("fingerprint") != google_places._fingerprint(lead):
        return False
    candidates = record.get("candidates") or []
    url = candidates[0].get("website") if candidates else None
    if not url or urlparse(url).scheme not in {"http", "https"} or not urlparse(url).hostname:
        return False
    if website_review.manual(lead) or (lead.website and not website_review.automatic(lead)):
        return False
    if lead.website == url:
        return False
    history = list(raw.get("website_history") or [])
    at = datetime.now(UTC).isoformat()
    if lead.website and not any(x.get("url") == lead.website for x in history):
        history.append({"url": lead.website, "source": lead.website_source, "recorded_at": at})
    raw["website_history"] = history
    raw.pop("contacts_scan", None)
    raw["website_refresh_required"] = {"menus": True, "contacts": True, "changed_at": at}
    lead.website = url
    lead.website_source = "Google Places 来源同步"
    lead.raw = raw
    return True


def sync_one(db: Session, lead: Lead, op: Operator, workflow_id: str) -> None:
    fingerprint = google_places._fingerprint(lead)
    client = google_places._client(db, op, lead.id, workflow_id=workflow_id)
    linked = google_places._link(lead)
    candidates = (
        [client.enrichment_details(linked["place_id"])]
        if linked
        else client.search(" ".join(x for x in [lead.name, lead.address, lead.postcode, "UK"] if x))
    )
    # 使用来源首选网站；保留其他候选，人工和导入网站不被覆盖。
    saved = []
    for candidate in candidates[:2]:
        place = candidate if linked else client.enrichment_details(candidate.id)
        saved.append({"place_id": place.id, "website": place.websiteUri})
    current = google_places._lead(db, lead.id, lock=True)
    if google_places._fingerprint(current) != fingerprint:
        raise google.PlacesError("门店资料已变化，请重新同步", 409)
    current.raw = {
        **(current.raw or {}),
        "source_sync": {
            "status": "completed",
            "fetched_at": datetime.now(UTC).isoformat(),
            "fingerprint": fingerprint,
            "candidates": saved,
            "review_status": "not_required",
            "source": "google_places",
        },
    }
    apply_saved(current)
    db.commit()


def advance(db: Session, batch: Batch, task: "Workflow") -> dict:
    from app.modules.leads.workflows import cancelled

    selected = policy.Policy.model_validate(task.params["policy"])
    state = dict(task.results[task.step]) if len(task.results) > task.step else {}
    if "Google 查询次数已达上限" in state.get("note", ""):
        state = {}  # 旧本地每日上限不再阻断来源同步；已完成结果由 fresh 复用。
    for key, default in {"processed": [], "synced": 0, "retry": 0}.items():
        state.setdefault(key, default)
    op = db.scalar(select(Operator).where(Operator.username == task.started_by))
    if op is None:
        raise ValueError("任务操作者不存在")
    scope = set(task.params.get("lead_ids") or [])
    members = [x for x in service.list_leads(db, batch.id, None, None, 0) if not scope or str(x.id) in scope]
    for member in members:
        apply_saved(member)
    db.commit()
    if selected.google_mode == "off" or not get_settings().google_places_api_key:
        return {**state, "done": True, "note": "Google 补充未启用或未配置；名单可以使用"}
    leads = [x for x in members if str(x.id) not in state["processed"] and not fresh(x, selected.stale_days)]
    for index, lead in enumerate(leads[:2]):
        if cancelled(db, task.id):
            break
        try:
            sync_one(db, lead, op, str(task.id))
            state["synced"] += 1
        except google.PlacesError as exc:
            db.rollback()
            state["retry"] += 1
            if exc.status in (429, 503):
                return {
                    **state,
                    "done": True,
                    "remaining": len(leads) - index,
                    "note": "Google 暂停补充：" + str(exc) + "；名单可用，稍后再次同步资料将接续未完成门店",
                }
        state["processed"] = [*state["processed"], str(lead.id)]
    return {**state, "done": len(leads) <= 2}
