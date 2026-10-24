"""名单来源查询与 AI 核验分离；候选不自动成为已核验官网。"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import Operator
from app.integrations import google_places as google
from app.modules.leads import google_places, policy, service
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


def sync_one(db: Session, lead: Lead, op: Operator, workflow_id: str) -> None:
    fingerprint = google_places._fingerprint(lead)
    client = google_places._client(db, op, lead.id, workflow_id=workflow_id)
    linked = google_places._link(lead)
    candidates = (
        [client.enrichment_details(linked["place_id"])]
        if linked
        else client.search(" ".join(x for x in [lead.name, lead.address, lead.postcode, "UK"] if x))
    )
    # 所有结果均为候选，不能因排第一就确认门店或替换人工官网。
    saved = []
    for candidate in candidates[:2]:
        place = candidate if linked else client.enrichment_details(candidate.id)
        saved.append({"place_id": place.id, "website": place.websiteUri})
    current = google_places._lead(db, lead.id)
    if google_places._fingerprint(current) != fingerprint:
        raise google.PlacesError("门店资料已变化，请重新同步", 409)
    current.raw = {
        **(current.raw or {}),
        "source_sync": {
            "status": "completed",
            "fetched_at": datetime.now(UTC).isoformat(),
            "fingerprint": fingerprint,
            "candidates": saved,
            "review_status": "pending",
            "source": "google_places",
        },
    }
    db.commit()


def advance(db: Session, batch: Batch, task: "Workflow") -> dict:
    from app.modules.leads.workflows import cancelled

    selected = policy.Policy.model_validate(task.params["policy"])
    state = dict(task.results[task.step]) if len(task.results) > task.step else {}
    for key, default in {"processed": [], "synced": 0, "retry": 0}.items():
        state.setdefault(key, default)
    if selected.google_mode == "off" or not get_settings().google_places_api_key:
        return {**state, "done": True, "note": "Google 补充未启用或未配置；名单可以使用"}
    op = db.scalar(select(Operator).where(Operator.username == task.started_by))
    if op is None:
        raise ValueError("任务操作者不存在")
    leads = [
        x
        for x in service.list_leads(db, batch.id, None, None, 0)
        if str(x.id) not in state["processed"] and not fresh(x, selected.stale_days)
    ]
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
