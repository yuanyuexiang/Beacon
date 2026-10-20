"""Google 优先发现当前官网；独立官网证据核验，历史网址只作回退。"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import Operator
from app.integrations import google_places as google
from app.modules.leads import google_places, policy, service, website_review
from app.modules.leads.models import Batch, Lead

if TYPE_CHECKING:
    from app.modules.leads.workflows import Workflow


STRATEGY_VERSION = "google-first-1"


def needed(lead: Lead, settings: policy.Policy) -> bool:
    if settings.google_mode == "all":
        return True
    record = (lead.raw or {}).get("places_enrichment") or {}
    if (
        record.get("strategy_version") != STRATEGY_VERSION
        or record.get("google_status") not in {"completed", "retry"}
        or record.get("website") != lead.website
        or record.get("manual") != website_review.manual(lead)
    ):
        return True
    if "本次任务 Google 调用预算已用完" in record.get("reason", ""):
        return True
    review = (lead.raw or {}).get("website_research") or {}
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(record["checked_at"])
        retry = (
            record.get("google_status") == "retry"
            or record.get("website_retry")
            or record.get("status") in {"retry", "ai_unavailable"}
        )
        if review.get("status") in {"retry", "conflict"} and not retry:
            return True
        return age > (timedelta(minutes=10) if retry else timedelta(days=settings.stale_days))
    except (KeyError, ValueError, TypeError):
        return True


def verify_website(db: Session, lead: Lead, place: google.Place, operator: Operator) -> bool:
    if not place.websiteUri:
        return False
    return website_review.review(db, lead, place.websiteUri, operator, place.id) == "verified"


def review_one(
    db: Session, lead: Lead, operator: Operator, selected: policy.Policy, workflow_id: str, force: bool = False
) -> str:
    configured = get_settings().llm_provider == "deepseek" and bool(get_settings().deepseek_api_key)
    google_enabled = selected.google_mode != "off" and bool(get_settings().google_places_api_key)
    lookup = google_enabled and (force or needed(lead, selected))
    if (
        not force
        and not lookup
        and (google_enabled or (configured and lead.website))
        and not website_review.needed(lead, selected.stale_days)
    ):
        return ((lead.raw or {}).get("places_enrichment") or {}).get("status", "insufficient")
    candidate_ids: list[str] = []
    google_status = "not_queried"
    error_status = None
    website_retry = False
    reason = "没有可靠的官网候选"
    status = "insufficient"
    original = website_review.snapshot(lead)
    if lookup:
        client = google_places._client(db, operator, lead.id, workflow_id=workflow_id)
        linked = google_places._link(lead)
        try:
            candidates = (
                [client.enrichment_details(linked["place_id"])]
                if linked
                else client.search(" ".join(x for x in [lead.name, lead.address, lead.postcode, "UK"] if x))
            )
            if website_review.snapshot(google_places._lead(db, lead.id)) != original:
                return "changed"
            candidate_ids = [x.id for x in candidates]
            google_status = "completed"
            if candidates and not configured:
                status, reason = "ai_unavailable", "AI 未配置，Google 候选尚未自动核验"
            for candidate in candidates[:2] if configured else []:
                place = candidate if linked else client.enrichment_details(candidate.id)
                current = google_places._lead(db, lead.id)
                if website_review.snapshot(current) != original:
                    return "changed"
                if not place.websiteUri:
                    continue
                # 即便和 Overture 相同也必须核验，不能把“值存在”当成可靠性。
                status = website_review.review(db, lead, place.websiteUri, operator, place.id)
                if status == "changed":
                    return status
                reason = ((lead.raw or {}).get("website_research") or {}).get("reason", "")
                if status == "verified":
                    return _save_status(lead, status, reason, candidate_ids, google_status=google_status)
                website_retry = website_retry or status in {"retry", "ai_unavailable"}
                db.commit()
        except google.PlacesError as exc:
            if website_review.snapshot(google_places._lead(db, lead.id)) != original:
                return "changed"
            google_status, error_status, reason = "retry", exc.status, str(exc)
            status = "retry"
    # Google 不可用／没有可信候选时仍可使用独立核验的既有网址；不伪造查询成功。
    google_reason = reason
    if lead.website and configured:
        if force or website_review.needed(lead, selected.stale_days):
            status = website_review.review(db, lead, lead.website, operator)
            if status == "changed":
                return status
        else:
            status = ((lead.raw or {}).get("website_research") or {}).get("status", "insufficient")
        reason = ((lead.raw or {}).get("website_research") or {}).get("reason", "")
    elif not configured and status != "retry" and not (google_status == "completed" and not candidate_ids):
        status, reason = "ai_unavailable", "AI 未配置，不能自动核验官网或识别类型"
    if google_status == "retry":
        reason = f"Google 查询未完成：{google_reason}；既有官网：{reason}"
    elif website_retry:
        reason = f"新官网候选待重试：{google_reason}；既有官网：{reason}"
    previous = (lead.raw or {}).get("places_enrichment") or {}
    if not lookup and previous.get("strategy_version") == STRATEGY_VERSION:
        # 仅重跑 AI 不刷新 Google 查询时间，也不丢失待重试状态。
        lead.raw = {**(lead.raw or {}), "places_enrichment": {**previous, "status": status, "reason": reason}}
        return status
    return _save_status(
        lead,
        status,
        reason,
        candidate_ids,
        google_status=google_status,
        error_status=error_status,
        website_retry=website_retry,
    )


def _save_status(
    lead: Lead,
    status: str,
    reason: str,
    candidates: list[str],
    *,
    google_status: str = "not_queried",
    error_status: int | None = None,
    website_retry: bool = False,
) -> str:
    lead.raw = {
        **(lead.raw or {}),
        "places_enrichment": {
            "status": status,
            "reason": reason,
            "candidate_ids": candidates,
            "version": website_review.VERSION,
            "strategy_version": STRATEGY_VERSION,
            "website": lead.website,
            "manual": website_review.manual(lead),
            "google_checked": google_status == "completed",
            "google_status": google_status,
            "error_status": error_status,
            "website_retry": website_retry,
            "checked_at": datetime.now(UTC).isoformat(),
        },
    }
    return status


def advance(db: Session, batch: Batch, task: "Workflow") -> dict:
    selected = policy.Policy.model_validate(task.params["policy"])
    state: dict[str, Any] = dict(task.results[task.step]) if len(task.results) > task.step else {}
    # 兼容旧任务：只清除旧的单任务额度耗尽检查点，当前全局限流继续保留。
    if "本次任务 Google 调用预算已用完" in state.get("note", ""):
        state = {}
    for key, value in {
        "processed": [],
        "verified": 0,
        "review": 0,
        "failed": 0,
        "insufficient": 0,
        "retry": 0,
        "ai_unavailable": 0,
        "conflict": 0,
    }.items():
        state.setdefault(key, value)
    if state.get("google_exhausted"):
        selected = selected.model_copy(update={"google_mode": "off"})
    configured = get_settings().llm_provider == "deepseek" and bool(get_settings().deepseek_api_key)
    google_enabled = selected.google_mode != "off" and bool(get_settings().google_places_api_key)
    if not google_enabled and not configured:
        return {**state, "done": True, "note": "未配置 AI；Google 补充未启用或未配置，已跳过"}
    operator = db.scalar(select(Operator).where(Operator.username == task.started_by))
    if operator is None:
        raise ValueError("任务操作者不存在")
    leads = [
        lead
        for lead in service.list_leads(db, batch.id, None, None, 0)
        if str(lead.id) not in state["processed"]
        and (
            (configured and website_review.needed(lead, selected.stale_days))
            or (google_enabled and needed(lead, selected))
        )
    ]
    chunk = 1 if configured else 2
    for lead in leads[:chunk]:
        try:
            status = review_one(db, lead, operator, selected, str(task.id))
            if status == "changed":
                status = "retry"
            query = (lead.raw or {}).get("places_enrichment") or {}
            if query.get("error_status") in (429, 503):
                state["google_exhausted"], state["note"] = True, query["reason"]
        except google.PlacesError as exc:
            db.rollback()
            if exc.status in (429, 503):
                if not configured:
                    return {**state, "done": True, "note": str(exc), "remaining": len(leads)}
                state["google_exhausted"], state["note"] = True, str(exc)
                current = (lead.raw or {}).get("website_research") or {}
                status = current.get("status") or _save_status(lead, "retry", str(exc), [])
            else:
                status = _save_status(lead, "retry", str(exc), [])
        except Exception:
            db.rollback()
            status = _save_status(lead, "retry", "核验执行未完成，可重试", [])
        state[status] += 1
        if status == "conflict":
            state["review"] += 1
        state["processed"] = [*state["processed"], str(lead.id)]
        task.results = task.results[: task.step] + [state]
        db.commit()
    return {**state, "done": len(leads) <= chunk}
