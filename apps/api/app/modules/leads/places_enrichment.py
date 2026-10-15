"""名单 Google 补充：小块推进，预算按上游尝试计数，候选仅保存 ID。

只有真实模型引用官网原文确认身份后才能采用官网；原有人工官网不覆盖。
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.models import Operator
from app.integrations import google_places as google
from app.integrations import research_judge
from app.integrations.overture import similarity
from app.modules.leads import auto_research, google_places, policy, service
from app.modules.leads.models import Batch, Lead

if TYPE_CHECKING:
    from app.modules.leads.workflows import Workflow


def needed(lead: Lead, settings: policy.Policy) -> bool:
    if settings.google_mode == "all":
        return True
    record = (lead.raw or {}).get("places_enrichment") or {}
    if record.get("status") not in {"verified", "review"}:
        return True
    stamp = record.get("checked_at")
    if not stamp:
        return True  # 有 Overture 官网也需要首次核验。
    return datetime.fromisoformat(stamp) < datetime.now(UTC) - timedelta(days=settings.stale_days)


def verify_website(db: Session, lead: Lead, place: google.Place, operator: Operator) -> bool:
    if not place.websiteUri or similarity(lead.name, place.displayName.text) < 0.8:
        return False
    original = auto_research.snapshot(lead)
    judge = research_judge.ResearchJudge()  # Fake 不允许自动采用。
    docs = auto_research.pages(place.websiteUri)
    verdict = judge.judge(
        {
            "kind": "website",
            "restaurant": {"name": lead.name, "address": lead.address, "postcode": lead.postcode},
            "candidate_url": place.websiteUri,
        },
        docs,
    )
    if verdict.decision != "accept" or not research_judge.grounded(verdict, docs, "identity"):
        return False
    # 不把地址或邮编差异单独作为否决条件；由官网原文身份判断决定。
    operation = None
    try:
        classified = judge.classify({"kind": "business_type", "restaurant": lead.name}, docs)
        texts = {d["id"]: d["text"] for d in docs}
        if (
            classified.category != "unknown"
            and classified.citations
            and all(c.document_id in texts and c.quote in texts[c.document_id] for c in classified.citations)
        ):
            operation = {
                **classified.model_dump(),
                "source": "official_website",
                "sources": [{"id": d["id"], "url": d["url"]} for d in docs],
                "checked_at": datetime.now(UTC).isoformat(),
            }
    except Exception:
        pass  # 类型识别失败不抹掉已核验的官网。
    before = {"website": lead.website, "website_source": lead.website_source}
    lead = google_places._lead(db, lead.id, lock=True)
    if auto_research.snapshot(lead) != original:
        return False
    raw = dict(lead.raw or {})
    if operation:
        raw["operating_type"] = operation
    history = list(raw.get("website_history") or [])
    if lead.website and not any(x["url"] == lead.website for x in history):
        history.append({"url": lead.website, "source": lead.website_source})
    raw["website_history"] = history
    alternatives = list(raw.get("verified_websites") or [])
    if not any(x["url"] == place.websiteUri for x in alternatives):
        alternatives.append(
            {
                "url": place.websiteUri,
                "source": "official_website",
                "verified_at": datetime.now(UTC).isoformat(),
                "judgment": verdict.model_dump(),
            }
        )
    raw["verified_websites"] = alternatives
    if not lead.website or (
        not raw.get("website_manual") and (lead.website_source or "").startswith(("overture:", "Overture"))
    ):
        lead.website = place.websiteUri
        lead.website_source = "官网原文 AI 校验（Google Places 发现）"
    raw["google_places_link"] = raw.get("google_places_link") or {
        "place_id": place.id,
        "version": uuid.uuid4().hex,
        "reviewed_by": "AI+官网证据",
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    raw["google_places_revision"] = raw["google_places_link"]["version"]
    lead.raw = raw
    from app.core import audit

    audit.record(
        db,
        operator,
        "verify_places_website",
        "lead",
        lead.id,
        before=before,
        after={"website": lead.website, "evidence": verdict.model_dump(), "usage": judge.usage},
    )
    return True


def advance(db: Session, batch: Batch, task: "Workflow") -> dict:
    selected = policy.Policy.model_validate(task.params["policy"])
    state: dict[str, Any] = (
        dict(task.results[task.step])
        if len(task.results) > task.step
        else {"processed": [], "verified": 0, "review": 0, "failed": 0}
    )
    if selected.google_mode == "off" or not get_settings().google_places_api_key:
        return {**state, "done": True, "note": "未启用 Google 补充或未配置密钥，已跳过"}
    operator = db.scalar(select(Operator).where(Operator.username == task.started_by))
    if operator is None:
        raise ValueError("任务操作者不存在")
    leads = [
        x
        for x in service.list_leads(db, batch.id, None, None, 0)
        if str(x.id) not in state["processed"] and needed(x, selected)
    ]
    for lead in leads[:2]:
        try:
            client = google_places._client(
                db, operator, lead.id, workflow_id=str(task.id), request_limit=selected.google_request_limit
            )
            linked = google_places._link(lead)
            candidates = (
                [client.enrichment_details(linked["place_id"])]
                if linked
                else client.search(" ".join(x for x in [lead.name, lead.address, lead.postcode, "UK"] if x))
            )
            candidate_ids = [x.id for x in candidates]
            verified = False
            if candidates and get_settings().llm_provider == "deepseek" and get_settings().deepseek_api_key:
                top = candidates[0]
                if linked or similarity(lead.name, top.displayName.text) >= 0.8:
                    place = top if linked else client.enrichment_details(top.id)
                    verified = verify_website(db, lead, place, operator)
            status = "verified" if verified else "review"
            state[status] += 1
            lead.raw = {
                **(lead.raw or {}),
                "places_enrichment": {
                    "status": status,
                    "candidate_ids": candidate_ids,
                    "checked_at": datetime.now(UTC).isoformat(),
                },
            }
        except google.PlacesError as exc:
            db.rollback()
            if exc.status in (429, 503):
                # 配额／速率／任务预算用尽不阻断后续预筛与联系方式步骤。
                return {**state, "done": True, "note": str(exc), "remaining": len(leads)}
            state["failed"] += 1
            lead.raw = {**(lead.raw or {}), "places_enrichment": {"status": "failed", "error": str(exc)}}
        except Exception:
            db.rollback()
            state["failed"] += 1
            lead.raw = {
                **(lead.raw or {}),
                "places_enrichment": {"status": "review", "error": "官网证据校验未完成，可在详情页重试"},
            }
        state["processed"] = [*state["processed"], str(lead.id)]
        task.results = task.results[: task.step] + [state]
        db.commit()  # 每家检查点，崩溃重试仍受持久调用预算约束。
    return {**state, "done": len(leads) <= 2}
