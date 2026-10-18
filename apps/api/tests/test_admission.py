"""AI 自动准入实际写入、证据约束、人工保护与各发送入口共用复核。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.integrations import research_judge as rj
from app.modules.leads import policy
from app.modules.leads.models import Lead
from app.modules.sales import admission, contact_ranking, service
from app.modules.sales.models import Channel, ChannelEligibility, ContactUsable, Eligibility
from tests.test_contacts import SITE, _lead_id

TEXT = "Vesper Restaurant is owned and operated by Vesper Dining Limited, company number 01234567."


def evidence(lead):
    now = datetime.now(UTC).isoformat()
    sub = {
        "version": admission.SUBSCRIBER_VERSION,
        "website": lead.website,
        "checked_at": now,
        "status": "verified",
        "subscriber_type": "corporate",
        "legal_name": "Vesper Dining Limited",
        "provider": "deepseek",
        "citations": [{"quote": TEXT, "url": SITE}],
    }
    assessment = {
        "recommendation": "recommended",
        "affiliation": "target",
        "purpose": "general",
        "owner": lead.name,
        "confirmed_at": now,
        "method": "ai",
        "citations": [{"quote": "Business enquiries info@vesper.example", "url": SITE}],
    }
    lead.raw = {
        **(lead.raw or {}),
        "subscriber_review": sub,
        "contact_review": {
            "version": contact_ranking.VERSION,
            "website": lead.website,
            "checked_at": now,
            "candidates": [{"channel": "email", "value": "info@vesper.example", "assessment": assessment}],
        },
    }
    return sub


@pytest.fixture
def eligible(client, db):
    _lead_id(client, db)
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    row = ChannelEligibility(
        lead_id=lead.id,
        channel=Channel.email,
        contact_ref="info@vesper.example",
        contact_usable=ContactUsable.unknown,
        eligibility=Eligibility.unknown,
    )
    db.add(row)
    evidence(lead)
    db.commit()
    return lead, row


def test_actual_auto_allowed_without_changing_deliverability(client, db, eligible):
    lead, row = eligible
    totals = admission.apply(db, lead)
    db.commit()
    assert totals["allowed"] == 1
    assert row.eligibility == Eligibility.allowed and row.contact_usable == ContactUsable.unknown
    assert row.rule_version == admission.VERSION and row.review_due_at > datetime.now(UTC)
    assert admission.stale_reason(db, lead, row) is None
    response = client.get(f"/api/leads/{lead.id}/eligibility").json()[0]
    assert response["eligibility"] == "allowed" and response["auto_admission"]["status"] == "allowed"


@pytest.mark.parametrize(
    "change", ["no_subscriber", "no_identity", "personal_email", "unrelated", "stale_identity", "non_uk"]
)
def test_missing_or_wrong_evidence_never_auto_allows(client, db, eligible, change):
    lead, row = eligible
    if change == "no_subscriber":
        lead.raw = {**lead.raw, "subscriber_review": {"status": "insufficient"}}
    elif change == "no_identity":
        lead.raw = {**lead.raw, "contact_review": {}}
    elif change == "personal_email":
        row.contact_ref = "vesper@gmail.com"
        c = lead.raw["contact_review"]["candidates"][0]
        lead.raw = {
            **lead.raw,
            "contact_review": {**lead.raw["contact_review"], "candidates": [{**c, "value": row.contact_ref}]},
        }
    elif change in {"unrelated", "stale_identity"}:
        c = lead.raw["contact_review"]["candidates"][0]
        update = {"affiliation": "other"} if change == "unrelated" else {"confirmed_at": "2020-01-01T00:00:00+00:00"}
        lead.raw = {
            **lead.raw,
            "contact_review": {
                **lead.raw["contact_review"],
                "candidates": [{**c, "assessment": {**c["assessment"], **update}}],
            },
        }
    else:
        from app.modules.leads.models import Batch

        batch = db.scalar(select(Batch))
        batch.country = "FR"
    admission.apply(db, lead)
    assert row.eligibility != Eligibility.allowed
    assert (admission.public(db, lead, row) or {})["reason"]


@pytest.mark.parametrize("status", [Eligibility.allowed, Eligibility.blocked])
def test_manual_result_is_preserved(client, db, eligible, status):
    lead, row = eligible
    row.eligibility, row.reviewed_by, row.rule_version = status, "tester", "manual-v1"
    row.evidence = "人工审核依据"
    admission.apply(db, lead)
    assert row.eligibility == status and row.reviewed_by == "tester" and row.evidence == "人工审核依据"


@pytest.mark.parametrize(
    "channel,needle", [(Channel.phone, "TPS"), (Channel.whatsapp, "opt-in"), (Channel.facebook, "平台")]
)
def test_channel_specific_missing_requirements(client, db, eligible, channel, needle):
    lead, row = eligible
    row.channel = channel
    c = lead.raw["contact_review"]["candidates"][0]
    lead.raw = {
        **lead.raw,
        "contact_review": {**lead.raw["contact_review"], "candidates": [{**c, "channel": channel.value}]},
    }
    admission.apply(db, lead)
    assert row.eligibility == Eligibility.unknown
    assert needle in (admission.public(db, lead, row) or {})["reason"]


def test_suppression_outweighs_positive_corporate_evidence(client, db, eligible, monkeypatch):
    lead, row = eligible
    monkeypatch.setattr(service, "is_suppressed", lambda *a: object())
    admission.apply(db, lead)
    assert row.eligibility == Eligibility.blocked


@pytest.mark.parametrize("change", ["website", "policy", "expiry", "contact", "disabled"])
def test_auto_permission_is_revalidated_after_changes(client, db, eligible, change):
    lead, row = eligible
    admission.apply(db, lead)
    db.commit()
    assert admission.stale_reason(db, lead, row) is None
    if change == "website":
        lead.website = "https://new.example"
    elif change == "contact":
        row.contact_ref = "different@vesper.example"
    elif change == "expiry":
        row.review_due_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        from app.core.models import Operator

        p = policy.current(db).model_copy(
            update={"auto_admission_enabled": False} if change == "disabled" else {"admission_valid_days": 10}
        )
        policy.save_policy(p, db, db.scalar(select(Operator)))
    assert admission.stale_reason(db, lead, row)
    assert (admission.public(db, lead, row) or {})["status"] == "unknown"


@pytest.mark.parametrize("bad", [False, True])
def test_ai_subscriber_quotes_must_prove_operator_not_web_designer(client, db, eligible, monkeypatch, bad):
    lead, row = eligible
    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-not-real")
    text = "Website designed by Vesper Dining Limited." if bad else TEXT
    monkeypatch.setattr(admission.website_entity, "crawl", lambda *a: ([], [{"url": SITE, "text": text}]))

    class Judge:
        model = "test"
        usage = []

        def subscriber(self, *args):
            return rj.SubscriberJudgment(
                subscriber_type="corporate",
                legal_name="Vesper Dining Limited",
                company_number=None if bad else "01234567",
                is_operator=True,
                reason="识别公司",
                citations=[rj.Citation(document_id="legal0", quote=text, kind="identity")],
            )

    monkeypatch.setattr(rj, "ResearchJudge", Judge)
    result = admission.prepare(lead, {"website": {}, "candidates": [{"kind": "email"}]}, policy.Policy())
    assert (result["status"] == "verified") is (not bad)


def test_auto_endpoint_collects_ai_facts_and_writes_permission(client, db, eligible, monkeypatch):
    from app.modules.sales import contacts

    lead, row = eligible
    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-not-real")
    contact_text = "Vesper Restaurant business enquiries: info@vesper.example"
    monkeypatch.setattr(
        contacts,
        "scan_website",
        lambda *a: {
            "url": SITE,
            "pages": [{"url": SITE, "ok": True}],
            "contacts": [
                {
                    "kind": "email",
                    "value": row.contact_ref,
                    "page_url": SITE,
                    "evidence": [{"page_url": SITE, "text": contact_text}],
                }
            ],
            "identity_documents": [{"id": "page0", "url": SITE, "text": contact_text}],
        },
    )
    monkeypatch.setattr(admission.website_entity, "crawl", lambda *a: ([], [{"url": SITE, "text": TEXT}]))

    class Judge:
        model = "test"
        usage = []

        def select_contacts(self, task, docs):
            c = task["candidates"][0]
            return rj.ContactJudgment(
                decisions=[
                    rj.ContactDecision(
                        candidate_id=c["candidate_id"],
                        recommendation="recommended",
                        affiliation="target",
                        owner="Vesper",
                        purpose="general",
                        reason="官网明确公开业务邮箱",
                        citations=[rj.Citation(document_id=c["evidence_ids"][0], quote=contact_text, kind="identity")],
                    )
                ]
            )

        def subscriber(self, *a):
            return rj.SubscriberJudgment(
                subscriber_type="corporate",
                legal_name="Vesper Dining Limited",
                company_number="01234567",
                is_operator=True,
                reason="官网明确运营公司",
                citations=[rj.Citation(document_id="legal0", quote=TEXT, kind="identity")],
            )

    monkeypatch.setattr(rj, "ResearchJudge", Judge)
    response = client.post(f"/api/leads/{lead.id}/auto-admission")
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["allowed"] == 1
    db.refresh(row)
    assert row.eligibility == Eligibility.allowed and row.contact_usable == ContactUsable.unknown


def test_real_task_gate_rechecks_auto_permission(client, db):
    import uuid

    from app.core.models import Operator
    from app.modules.content.models import ContentPiece
    from tests.test_sales import _ready

    lead_id, _, content = _ready(client, db)
    lead = db.get(Lead, uuid.UUID(lead_id))
    lead.website = SITE
    row = ChannelEligibility(
        lead_id=lead.id,
        channel=Channel.email,
        contact_ref="info@vesper.example",
        contact_usable=ContactUsable.unknown,
        eligibility=Eligibility.unknown,
    )
    db.add(row)
    evidence(lead)
    db.commit()
    admission.apply(db, lead)
    db.commit()
    piece = db.get(ContentPiece, uuid.UUID(content["id"]))
    service.check_can_contact(db, row, piece)
    p = policy.current(db).model_copy(update={"auto_admission_enabled": False})
    policy.save_policy(p, db, db.scalar(select(Operator)))
    with pytest.raises(service.SalesError, match="自动准入已关闭"):
        service.check_can_contact(db, row, piece)


def test_named_person_with_role_word_does_not_count_as_generic_mailbox():
    assert not admission.role_mailbox("jane.manager@company.test")
    assert not admission.role_mailbox("info@gmail.com")
    assert admission.role_mailbox("procurement@company.test")


def test_manual_api_cannot_claim_system_rule_version(client, db, eligible):
    lead, row = eligible
    response = client.post(
        f"/api/leads/{lead.id}/eligibility",
        json={
            "channel": "email",
            "contact_ref": row.contact_ref,
            "eligibility": "allowed",
            "evidence": "不能伪装成 AI 的人工依据",
            "rule_version": admission.VERSION,
        },
    )
    assert response.status_code == 400
