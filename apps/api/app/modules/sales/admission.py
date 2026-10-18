"""AI 提取事实，版本化规则决定准入；实际发送仍需审批、身份／退出说明和抑制复核。"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.integrations import research_judge, website_contacts, website_entity
from app.modules.leads import entity, policy
from app.modules.leads.models import Lead
from app.modules.sales import contact_ranking
from app.modules.sales.models import ChannelEligibility, ContactUsable, Eligibility

VERSION = "ai-admission:uk-v1"
SOURCE = "https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/"
SUBSCRIBER_VERSION = "subscriber-v1"
AI_ACTOR = "AI+规则引擎"


def policy_stamp(p: policy.Policy) -> dict:
    return {
        "enabled": p.auto_admission_enabled,
        "corporate_email": p.corporate_email_auto,
        "days": p.admission_valid_days,
    }


def uk_scope(db: Session, lead: Lead) -> bool:
    from app.modules.leads.models import Batch, BatchLead

    countries = list(
        db.scalars(
            select(Batch.country).join(BatchLead, BatchLead.batch_id == Batch.id).where(BatchLead.lead_id == lead.id)
        )
    )
    return bool(countries) and all(country.upper() in {"UK", "GB"} for country in countries)


def role_mailbox(value: str) -> bool:
    local, _, domain = value.lower().partition("@")
    roles = {
        "info",
        "hello",
        "hi",
        "contact",
        "enquiries",
        "enquiry",
        "inquiries",
        "office",
        "restaurant",
        "manager",
        "management",
        "business",
        "procurement",
        "purchasing",
        "secretary",
        "reception",
        "team",
        "sales",
        "marketing",
    }
    return domain not in website_contacts.FREE_MAIL_DOMAINS and re.sub(r"[0-9]+$", "", local) in roles


def fingerprint(lead: Lead, row: ChannelEligibility, p: policy.Policy) -> str:
    data = {
        "website": lead.website,
        "name": lead.name,
        "address": lead.address,
        "postcode": lead.postcode,
        "channel": row.channel.value,
        "contact": row.contact_ref,
        "usable": row.contact_usable.value,
        "contact_evidence": contact_ranking.stored(lead, row.channel.value, row.contact_ref),
        "subscriber": (lead.raw or {}).get("subscriber_review"),
        "policy": policy_stamp(p),
    }
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def prepare(lead: Lead, found: dict, p: policy.Policy) -> dict:
    """无数据库写操作；只读取固定数量官网页，绝不向联系人发送探测消息。"""
    result: dict = {
        "version": SUBSCRIBER_VERSION,
        "website": lead.website,
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "insufficient",
        "subscriber_type": "unknown",
        "reason": "尚无公司主体原文证据",
        "citations": [],
    }
    if not p.auto_admission_enabled or not p.corporate_email_auto:
        return {**result, "reason": "自动公司邮箱准入已关闭"}
    if not any(c["kind"] == "email" for c in found["candidates"]):
        return {**result, "reason": "当前没有邮箱，无需识别邮件订户类型"}
    if not lead.website:
        return {**result, "reason": "缺少官网，不能核验公司主体"}
    if get_settings().llm_provider != "deepseek" or not get_settings().deepseek_api_key:
        return {**result, "status": "retry", "reason": "真实 AI 未配置，暂不能自动识别公司订户"}
    docs = list((found.get("website") or {}).get("identity_documents") or [])
    try:
        judge = research_judge.ResearchJudge()
        _, legal = website_entity.crawl(lead.website, entity.site_fetch())
        for i, d in enumerate(legal):
            docs.append({"id": f"legal{i}", "url": d["url"], "text": d["text"][:16000]})
        verdict = judge.subscriber({"name": lead.name, "address": lead.address, "postcode": lead.postcode}, docs)
        host = (urlsplit(lead.website).hostname or "").removeprefix("www.")
        pages = {d["id"]: d for d in docs if (urlsplit(d["url"]).hostname or "").removeprefix("www.") == host}
        valid = bool(verdict.citations) and all(
            c.kind == "identity"
            and c.document_id in pages
            and c.quote.strip()
            and c.quote in pages[c.document_id]["text"]
            for c in verdict.citations
        )

        def normalized(text: str) -> str:
            return re.sub(r"[^a-z0-9]", "", text.lower())

        name = normalized(verdict.legal_name)
        relationship = re.compile(r"operated\s+by|owned\s+by|trading\s+(?:name|as)|operator\s+(?:is|of)", re.I)
        operator_quote = any(
            name and name in normalized(c.quote) and relationship.search(c.quote) for c in verdict.citations
        )
        form = bool(re.search(r"\b(?:limited|ltd\.?|plc|llp)\b", verdict.legal_name, re.I))
        number = not verdict.company_number or any(
            normalized(verdict.company_number) in normalized(c.quote) for c in verdict.citations
        )
        verified = (
            valid
            and verdict.is_operator
            and operator_quote
            and form
            and number
            and verdict.subscriber_type == "corporate"
        )
        return {
            **result,
            **verdict.model_dump(),
            "status": "verified" if verified else "insufficient",
            "subscriber_type": "corporate" if verified else "unknown",
            "provider": "deepseek",
            "model": judge.model,
            "citations": [
                {**c.model_dump(), "url": pages[c.document_id]["url"]}
                for c in verdict.citations
                if c.document_id in pages
            ],
            "reason": verdict.reason if verified else "缺少可验证的公司法律形式及门店运营关系；" + verdict.reason,
            "usage": judge.usage,
        }
    except Exception:
        return {**result, "status": "retry", "reason": "公司主体 AI 核验或官网读取未完成，可重试"}


def _record(lead: Lead, row: ChannelEligibility) -> dict | None:
    return ((lead.raw or {}).get("admission_reviews") or {}).get(str(row.id))


def stale_reason(db: Session, lead: Lead, row: ChannelEligibility) -> str | None:
    if not (row.rule_version or "").startswith("ai-admission:"):
        return None
    record = _record(lead, row)
    if not record or row.rule_version != VERSION:
        return "自动准入规则已更新，请重新核验"
    if row.reviewed_by != AI_ACTOR or record.get("status") != row.eligibility.value:
        return "自动准入记录与当前审核结果不一致，请重新核验"
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(record["checked_at"])
        if age > timedelta(days=policy.current(db).admission_valid_days):
            return "自动准入证据已过期，请重新核验"
    except (KeyError, ValueError, TypeError):
        return "自动准入缺少有效核验时间，请重新核验"
    if not row.review_due_at or row.review_due_at <= datetime.now(UTC):
        return "自动准入已到期，请重新核验"
    if row.channel.value == "email" and not uk_scope(db, lead):
        return "当前名单地区不再符合英国准入规则，请重新审核"
    current = policy.current(db)
    if not current.auto_admission_enabled:
        return "自动准入已关闭，请人工审核或重新核验"
    if record.get("fingerprint") != fingerprint(lead, row, current):
        return "官网、联系方式证据或准入策略已变化，请重新核验"
    return None


def public(db: Session, lead: Lead, row: ChannelEligibility) -> dict | None:
    record = _record(lead, row)
    if not record:
        return None
    if not (row.rule_version or "").startswith("ai-admission:"):
        return {"status": row.eligibility.value, "method": "manual", "reason": "以当前人工准入结果为准", "missing": []}
    stale = stale_reason(db, lead, row)
    return {
        **record,
        **({"status": "unknown", "reason": stale, "missing": [stale], "needs_refresh": True} if stale else {}),
    }


def apply(db: Session, lead: Lead, prepared: dict | None = None, expected_policy: dict | None = None) -> dict:
    """在已有门店锁内调用，短事务内写实际 ChannelEligibility，保留人工审核。"""
    from app.modules.sales import service

    selected = policy.current(db)
    if prepared is not None:
        lead.raw = {**(lead.raw or {}), "subscriber_review": prepared}
    subscriber = (lead.raw or {}).get("subscriber_review") or {}
    in_uk = uk_scope(db, lead)
    rows = list(
        db.scalars(
            select(ChannelEligibility)
            .where(ChannelEligibility.lead_id == lead.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    records = dict((lead.raw or {}).get("admission_reviews") or {})
    totals = {"allowed": 0, "blocked": 0, "unknown": 0, "manual_preserved": 0}
    for row in rows:
        auto = (row.rule_version or "").startswith("ai-admission:")
        protected = not auto and row.eligibility != Eligibility.unknown
        suppression = service.is_suppressed(db, lead.id, row.contact_ref)
        missing = []
        decision, reason = "unknown", ""
        assessment = contact_ranking.stored(lead, row.channel.value, row.contact_ref) or {}
        if suppression or row.contact_usable == ContactUsable.invalid:
            decision, reason = "blocked", "已在抑制名单" if suppression else "联系方式已标记无效"
        elif protected:
            totals["manual_preserved"] += 1
            records[str(row.id)] = {
                "status": row.eligibility.value,
                "reason": "保留人工准入审核结果",
                "method": "manual",
                "missing": [],
            }
            continue
        elif not selected.auto_admission_enabled:
            missing.append("自动准入策略已关闭")
        elif expected_policy is not None and expected_policy != policy_stamp(selected):
            missing.append("核验期间准入策略已变化，请重新运行")
        elif not row.contact_ref:
            missing.append("缺少联系方式")
        elif assessment.get("recommendation") == "not_recommended" or assessment.get("affiliation") == "other":
            decision, reason = "blocked", "联系方式属于无关门店或不适合本次销售用途"
        elif (
            assessment.get("recommendation") not in {"recommended", "backup"}
            or assessment.get("affiliation") != "target"
            or not assessment.get("citations")
        ):
            missing.append("缺少该联系方式属于目标门店的原文证据")
        elif row.channel.value == "email":
            if not in_uk:
                missing.append("缺少明确的英国业务范围，当前规则不适用")
            try:
                contact_at = assessment.get("confirmed_at") or ((lead.raw or {}).get("contact_review") or {}).get(
                    "checked_at"
                )
                contact_fresh = datetime.now(UTC) - datetime.fromisoformat(contact_at or "") < timedelta(
                    days=selected.admission_valid_days
                )
            except (ValueError, TypeError):
                contact_fresh = False
            if not contact_fresh:
                missing.append("联系方式归属证据已过期或缺少核验时间")
            if not selected.corporate_email_auto:
                missing.append("公司邮箱自动准入未启用")
            if not role_mailbox(row.contact_ref):
                missing.append("可能涉及个人邮箱，需要对应授权或处理依据")
            if assessment.get("purpose") not in {"business", "general"}:
                missing.append("邮箱不是已核实的通用业务或商务联系用途")
            try:
                fresh = datetime.now(UTC) - datetime.fromisoformat(subscriber["checked_at"]) < timedelta(
                    days=selected.admission_valid_days
                )
            except (KeyError, ValueError, TypeError):
                fresh = False
            if (
                subscriber.get("status") != "verified"
                or subscriber.get("subscriber_type") != "corporate"
                or subscriber.get("provider") != "deepseek"
                or subscriber.get("website") != lead.website
                or subscriber.get("version") != SUBSCRIBER_VERSION
                or not fresh
            ):
                missing.append("缺少明确的公司订户及官网运营主体证据")
            if not missing:
                decision, reason = "allowed", "AI 已核实官网运营公司与通用业务邮箱，符合英国公司 B2B 邮件准入规则"
        elif row.channel.value == "phone":
            missing.extend(["缺少有效 TPS 筛查结果", "缺少有效 CTPS 筛查结果"])
        elif row.channel.value == "whatsapp":
            missing.append("缺少该收件人针对发送方与用途的 opt-in 授权证据")
        elif row.channel.value in {"facebook", "instagram", "tiktok", "linkedin", "other_social"}:
            missing.append("缺少该平台会话权限、有效消息窗口或针对本次触达的授权证据")
        else:
            missing.append("当前渠道没有可自动放行的规则与授权证据")
        reason = reason or "；".join(missing)
        before = {"eligibility": row.eligibility.value, "rule_version": row.rule_version}
        now = datetime.now(UTC)
        row.eligibility = Eligibility(decision)
        row.rule_version, row.reviewed_by, row.reviewed_at = VERSION, AI_ACTOR, now
        row.review_due_at = now + timedelta(days=selected.admission_valid_days)
        row.evidence = json.dumps(
            {
                "reason": reason,
                "contact_evidence": assessment,
                "subscriber_evidence": subscriber if row.channel.value == "email" else None,
                "rule_source": SOURCE,
            },
            ensure_ascii=False,
        )
        record = {
            "status": decision,
            "reason": reason,
            "missing": missing,
            "checked_at": now.isoformat(),
            "method": "ai_rules",
            "rule_version": VERSION,
            "rule_source": SOURCE,
            "contact_evidence": assessment,
            "subscriber_evidence": subscriber if row.channel.value == "email" else None,
            "fingerprint": fingerprint(lead, row, selected),
        }
        records[str(row.id)] = record
        totals[decision] += 1
        audit.record(db, None, "auto_admission", "channel_eligibility", row.id, before=before, after=record)
    lead.raw = {**(lead.raw or {}), "admission_reviews": records}
    return totals
