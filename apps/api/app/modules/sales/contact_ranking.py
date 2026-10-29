"""有证据的联系方式用途推荐，和有效性／渠道准入完全分离。"""

import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx

from app.integrations import ai_runtime, research_judge, website_contacts
from app.integrations.llm import ProviderUnavailable

VERSION = "contact-ranking-2"
RANK = {"recommended": 0, "backup": 1, "review": 2, "not_recommended": 3}


def candidate_id(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}|{value}".encode()).hexdigest()[:24]


def pending(reason: str = "尚无经过证据校验的 AI 推荐") -> dict:
    return {
        "recommendation": "review",
        "affiliation": "unknown",
        "owner": "",
        "purpose": "unknown",
        "reason": reason,
        "citations": [],
    }


def rank(lead: Any, found: dict) -> dict:
    candidates = found["candidates"]
    for c in candidates:
        c["assessment"] = pending()
    meta = {
        "version": VERSION,
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "completed",
        "reason": "AI 已按官网证据判断归属和用途",
    }
    if not candidates:
        return {**meta, "reason": "没有找到联系方式候选"}
    docs = list((found.get("website") or {}).get("identity_documents") or [])
    identity_ids = {d["id"] for d in docs}
    own_ids: dict[str, set[str]] = {}
    task_candidates = []
    for c in candidates[:40]:
        own_ids[c["id"]] = set()
        for index, evidence in enumerate(c.get("evidence") or []):
            if not evidence.get("text", "").strip():
                continue
            eid = f"{c['id']}_{index}"
            own_ids[c["id"]].add(eid)
            docs.append({"id": eid, "url": evidence["page_url"], "text": evidence["text"]})
        task_candidates.append(
            {
                "candidate_id": c["id"],
                "kind": c["kind"],
                "value": c["value"],
                "sources": c["sources"],
                "evidence_ids": sorted(own_ids[c["id"]]),
            }
        )
    try:
        judge = research_judge.ResearchJudge()
        verdict = judge.select_contacts(
            {
                "restaurant": {"name": lead.name, "address": lead.address, "postcode": lead.postcode},
                "website": lead.website,
                "candidates": task_candidates,
            },
            docs,
        )
        ids = [d.candidate_id for d in verdict.decisions]
        if len(set(ids)) != len(ids) or set(ids) - set(own_ids):
            raise ValueError("AI 返回重复或未知候选编号")
        texts = {d["id"]: d["text"] for d in docs}
        decisions = {d.candidate_id: d for d in verdict.decisions}
        counts: dict[str, int] = {}
        for c in candidates:
            decision = decisions.get(c["id"])
            if not decision:
                continue
            allowed = own_ids[c["id"]] | identity_ids
            grounded = bool(decision.citations) and all(
                q.kind == "identity"
                and q.document_id in allowed
                and bool(q.quote.strip())
                and q.quote in texts[q.document_id]
                for q in decision.citations
            )

            # 官网整页和抽取窗口可能包含同一事实；不要求模型必须引用内部窗口编号。
            def bound_quote(q, c=c) -> bool:
                if q.document_id in own_ids[c["id"]]:
                    return True
                document: dict[str, Any] = next((d for d in docs if d["id"] == q.document_id), {})
                source_urls = {s["ref"] for s in c["sources"] if s["type"] == "website"}
                if document.get("url") not in source_urls:
                    return False
                if c["kind"] in {"phone", "whatsapp"}:
                    return any(
                        website_contacts.normalize_uk_phone(m.group(0)) == c["value"]
                        for m in website_contacts.PHONE_TEXT.finditer(q.quote)
                    )
                return c["value"].casefold() in q.quote.casefold()

            own = any(bound_quote(q) for q in decision.citations)
            if not grounded or not own:
                c["assessment"] = pending("仅有来源记录，尚缺与该联系方式对应的原文；可重跑 AI 核验或点击人工确认")
                c["assessment"]["failure_code"] = "missing_contact_evidence"
                continue
            result = decision.model_dump(exclude={"candidate_id"})
            if not result["owner"].strip() or result["affiliation"] == "unknown" or result["purpose"] == "unknown":
                result["recommendation"] = "review"
            elif result["affiliation"] == "other" or result["purpose"] in {
                "media",
                "recruitment",
                "complaints",
                "support",
            }:
                result["recommendation"] = "not_recommended"
            elif result["recommendation"] == "recommended" and (
                result["affiliation"] == "group" or result["purpose"] in {"booking", "other"}
            ):
                result["recommendation"] = "backup"
            if result["recommendation"] == "recommended":
                counts[c["kind"]] = counts.get(c["kind"], 0) + 1
                if counts[c["kind"]] > 2:
                    result["recommendation"] = "backup"
            result["citations"] = [
                {**q.model_dump(), "url": next(d["url"] for d in docs if d["id"] == q.document_id)}
                for q in decision.citations
            ]
            c["assessment"] = {**result, "method": "ai", "confirmed_at": meta["checked_at"], "model": judge.model}
        return {**meta, "model": judge.model, "usage": judge.usage}
    except ProviderUnavailable as exc:
        if not ai_runtime.available():
            reason = "尚未配置真实 AI，候选已保留，可配置后重试或人工选择"
        else:
            import re

            code = re.search(r"HTTP (\d{3})", str(exc))
            reason = (
                f"AI 已配置，但服务请求失败（HTTP {code.group(1)}），候选已保留，可重试"
                if code
                else "AI 已配置，但本次服务调用未完成，候选已保留，可重试"
            )
        status = "ai_unavailable"
    except httpx.HTTPError:
        reason, status = "AI 已配置，但网络连接失败或请求超时，候选已保留，可重试", "ai_unavailable"
    except Exception:
        reason, status = "AI 判断未通过证据校验，候选已保留，可重试", "retry"
    for c in candidates:
        c["assessment"] = pending(reason)
    return {**meta, "status": status, "reason": reason}


def manual_assessment(lead: Any, channel: str, ref: str | None) -> dict | None:
    row = ((lead.raw or {}).get("contact_confirmations") or {}).get(candidate_id(channel, ref or ""))
    return row["assessment"] if row and row.get("website") == lead.website else None


def stored(lead: Any, channel: str, ref: str | None) -> dict | None:
    manual = manual_assessment(lead, channel, ref)
    if manual:
        return manual
    record = (lead.raw or {}).get("contact_review") or {}
    if record.get("website") != lead.website or record.get("version") not in {VERSION, "contact-ranking-1"}:
        return None
    return next(
        (c["assessment"] for c in record.get("candidates", []) if c["channel"] == channel and c["value"] == ref), None
    )
