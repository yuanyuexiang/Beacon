"""官网证据核验：身份与经营类型分别落档，只有可复核原文才自动采用。"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core import audit
from app.core.models import Operator
from app.integrations import research_judge
from app.integrations.llm import ProviderUnavailable
from app.modules.leads import auto_research, google_places
from app.modules.leads.models import Lead

VERSION = "website-review-3"


def needed(lead: Lead, days: int) -> bool:
    raw = lead.raw or {}
    record = raw.get("website_research") or {}
    if not lead.website:
        return False
    if record.get("version") != VERSION or record.get("website") != lead.website:
        return True
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(record["checked_at"])
        if record.get("status") in {"retry", "ai_unavailable"}:
            return age > timedelta(minutes=10)
        operation = raw.get("operating_type") or {}
        if record.get("status") == "verified" and operation.get("status") in {"retry", "ai_unavailable"}:
            return age > timedelta(minutes=10)
        return age > timedelta(days=days)
    except (KeyError, ValueError, TypeError):
        return True


def _record(status: str, reason: str, url: str, **extra) -> dict:
    return {
        "status": status,
        "reason": reason,
        "website": url,
        "checked_at": datetime.now(UTC).isoformat(),
        "version": VERSION,
        **extra,
    }


def review(db: Session, lead: Lead, url: str, operator: Operator, place_id: str | None = None) -> str:
    original = auto_research.snapshot(lead)
    before_type = (lead.raw or {}).get("operating_type")
    docs: list[dict] = []
    verdict = None
    operation = None
    judge = None
    try:
        judge = research_judge.ResearchJudge()
    except (ProviderUnavailable, httpx.HTTPError):
        result = _record("ai_unavailable", "AI 未配置或不可用，未自动采用", url)
    else:
        try:
            docs = auto_research.pages(url)
            if not docs or not any(d.get("text", "").strip() for d in docs):
                raise ValueError("没有可读取的官网正文")
        except Exception as exc:
            result = _record("retry", f"官网读取未完成：{type(exc).__name__}，可重试", url)
        else:
            try:
                verdict = judge.judge(
                    {
                        "kind": "website",
                        "restaurant": {"name": lead.name, "address": lead.address, "postcode": lead.postcode},
                        "fsa_type": (lead.raw or {}).get("BusinessType"),
                        "candidate_url": url,
                        "instruction": "结合官网门店名称、运营方与门店信息判断身份；门牌或邮编差异不单独否决。",
                    },
                    docs,
                )
                if (
                    verdict.decision == "accept"
                    and research_judge.grounded(verdict, docs, "identity")
                    and not research_judge.grounded(verdict, docs, "conflict")
                ):
                    result = _record("verified", verdict.reason, url, judgment=verdict.model_dump())
                elif research_judge.grounded(verdict, docs, "conflict"):
                    result = _record("conflict", verdict.reason, url, judgment=verdict.model_dump())
                else:
                    result = _record("insufficient", verdict.reason, url, judgment=verdict.model_dump())
            except (ProviderUnavailable, httpx.HTTPError):
                result = _record("ai_unavailable", "AI 服务暂不可用，可重试", url)
            except Exception:
                result = _record("insufficient", "AI 未给出可验证的身份引用，未自动采用", url)
            if result["status"] == "verified":
                try:
                    classified = judge.classify({"kind": "business_type", "restaurant": lead.name}, docs)
                    texts = {d["id"]: d["text"] for d in docs}
                    if (
                        classified.category != "unknown"
                        and classified.citations
                        and all(
                            c.kind in {"identity", "menu"}
                            and c.document_id in texts
                            and c.quote in texts[c.document_id]
                            for c in classified.citations
                        )
                    ):
                        services = {
                            "food_service": r"food|breakfast|lunch|dinner|meals|pizza|sandwich",
                            "dine_in": r"dine.?in|eat.?in|tables|seating",
                            "coffee": r"coffee|espresso|cappuccino",
                            "drinks": r"drinks|beer|wine|cocktails",
                            "takeaway": r"take.?away|take.?out|collection|delivery",
                        }
                        quotes = " ".join(c.quote for c in classified.citations)
                        grounded_services = list(
                            dict.fromkeys(
                                [tag for tag in classified.services if re.search(services[tag], quotes, re.I)]
                            )
                        )
                        operation = {
                            **classified.model_dump(),
                            "services": grounded_services,
                            **_record("verified", classified.reason, url),
                            "source": "official_website",
                        }
                    else:
                        operation = _record(
                            "insufficient",
                            "经营类型未能通过原文校验：" + classified.reason,
                            url,
                            category="unknown",
                            failure_code="unknown" if classified.category == "unknown" else "unsupported_citations",
                        )
                except (ProviderUnavailable, httpx.HTTPError):
                    operation = _record(
                        "ai_unavailable", "官网身份已核验，经营类型 AI 暂不可用", url, category="unknown"
                    )
                except Exception:
                    operation = _record("insufficient", "经营类型缺少可验证原文，未自动采用", url, category="unknown")

    sources = [{"id": d["id"], "url": d["url"]} for d in docs]
    result["sources"] = sources
    locked = google_places._lead(db, lead.id, lock=True)
    if auto_research.snapshot(locked) != original or (locked.raw or {}).get("operating_type") != before_type:
        return "changed"
    raw = dict(locked.raw or {})
    previous_url = (before_type or {}).get("website") or next(
        (source.get("url") for source in (before_type or {}).get("sources", [])), None
    )
    raw["website_research"] = result
    if (
        operation
        and not raw.get("operating_type_manual")
        and (before_type or {}).get("source") != "manual"
        and (operation["status"] == "verified" or not before_type or previous_url != url)
    ):
        raw["operating_type"] = {**operation, "sources": sources}
    if result["status"] == "verified":
        history = list(raw.get("website_history") or [])
        if locked.website and not any(h["url"] == locked.website for h in history):
            history.append({"url": locked.website, "source": locked.website_source})
        raw["website_history"] = history
        alternatives = [x for x in raw.get("verified_websites", []) if x["url"] != url]
        raw["verified_websites"] = [
            *alternatives,
            {
                "url": url,
                "source": "official_website",
                "verified_at": result["checked_at"],
                "judgment": result.get("judgment"),
            },
        ]
        if not locked.website or (
            not raw.get("website_manual") and (locked.website_source or "").startswith(("overture:", "Overture"))
        ):
            locked.website = url
            locked.website_source = "官网原文 AI 核验"
        if place_id and not raw.get("google_places_link"):
            raw["google_places_link"] = {
                "place_id": place_id,
                "version": uuid.uuid4().hex,
                "reviewed_by": "AI+官网证据",
                "reviewed_at": result["checked_at"],
            }
            raw["google_places_revision"] = raw["google_places_link"]["version"]
    locked.raw = raw
    audit.record(
        db,
        operator,
        "review_official_website",
        "lead",
        locked.id,
        after={"research": result, "operation": operation, "usage": judge.usage if judge else []},
    )
    return result["status"]
