"""已有官网先行 AI 核验；必要时在预算内查询 Google 候选。"""

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


def needed(lead: Lead, settings: policy.Policy) -> bool:
    if settings.google_mode == "all":
        return True
    record = (lead.raw or {}).get("places_enrichment") or {}
    if record.get("version") != website_review.VERSION and record.get("status") != "verified":
        return True
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(record["checked_at"])
        return age > (
            timedelta(minutes=10)
            if record.get("status") in {"retry", "ai_unavailable"}
            else timedelta(days=settings.stale_days)
        )
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
    status = "insufficient"
    reason = "没有可靠的官网候选"
    candidate_ids: list[str] = []
    if lead.website and configured:
        status = website_review.review(db, lead, lead.website, operator)
        if status == "changed":
            return status
        reason = ((lead.raw or {}).get("website_research") or {}).get("reason", "")
        if status == "verified" and selected.google_mode != "all":
            return status
        db.commit()  # 官网结果先保存；Google 配额耗尽不能回滚已取得的证据。
        # 网络或 AI 服务异常应重试对应环节，不用 Google 掩盖网络故障。
        if status in {"retry", "ai_unavailable"}:
            return status
    if selected.google_mode == "off" or not get_settings().google_places_api_key:
        if not configured:
            status, reason = "ai_unavailable", "AI 未配置，不能自动核验官网或识别类型"
        elif not lead.website:
            reason = "没有官网，Google 补充未启用或未配置"
        return _save_status(lead, status, reason, candidate_ids)
    if not force and not needed(lead, selected):
        return ((lead.raw or {}).get("places_enrichment") or {}).get("status", "insufficient")
    client = google_places._client(
        db, operator, lead.id, workflow_id=workflow_id, request_limit=selected.google_request_limit
    )
    linked = google_places._link(lead)
    candidates = (
        [client.enrichment_details(linked["place_id"])]
        if linked
        else client.search(" ".join(x for x in [lead.name, lead.address, lead.postcode, "UK"] if x))
    )
    candidate_ids = [x.id for x in candidates]
    if candidates and not configured:
        return _save_status(lead, "ai_unavailable", "AI 未配置，候选尚未自动核验", candidate_ids)
    for candidate in candidates[:2]:
        place = candidate if linked else client.enrichment_details(candidate.id)
        if not place.websiteUri or place.websiteUri == lead.website:
            continue
        status = website_review.review(db, lead, place.websiteUri, operator, place.id)
        if status == "changed":
            return status
        reason = ((lead.raw or {}).get("website_research") or {}).get("reason", "")
        db.commit()
        if status == "verified":
            break
    return _save_status(lead, status, reason, candidate_ids)


def _save_status(lead: Lead, status: str, reason: str, candidates: list[str]) -> str:
    lead.raw = {
        **(lead.raw or {}),
        "places_enrichment": {
            "status": status,
            "reason": reason,
            "candidate_ids": candidates,
            "version": website_review.VERSION,
            "checked_at": datetime.now(UTC).isoformat(),
        },
    }
    return status


def advance(db: Session, batch: Batch, task: "Workflow") -> dict:
    selected = policy.Policy.model_validate(task.params["policy"])
    state: dict[str, Any] = dict(task.results[task.step]) if len(task.results) > task.step else {}
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
            or (
                google_enabled
                and needed(lead, selected)
                and (
                    selected.google_mode == "all"
                    or ((lead.raw or {}).get("website_research") or {}).get("status") != "verified"
                )
            )
        )
    ]
    chunk = 1 if configured else 2
    for lead in leads[:chunk]:
        try:
            status = review_one(db, lead, operator, selected, str(task.id))
            if status == "changed":
                status = "retry"
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
