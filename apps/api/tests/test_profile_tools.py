"""UK service facts, isolated signatures and non-persistent AI previews."""

from sqlalchemy import func, select

from app.core.models import AuditLog
from app.modules.content import outreach_ai, profile_tools
from app.modules.content.models import ContentPiece
from app.modules.sales.models import ManualTask
from tests.test_auth import make_operator
from tests.test_imports import login
from tests.test_outreach_ai import result
from tests.test_users import session


def profile(client):
    return {
        **client.get("/api/outreach-profile").json(),
        "company": "真实菜单工作室",
        "services": "菜单排版设计",
        "english_brand": "Example Studio",
        "sender_name": "Tom",
        "sender_role": "Designer",
        "tone": "warm",
    }


def test_profile_legacy_defaults_and_english_fields(client, db):
    login(client, db)
    p = profile(client)
    assert p["language"] == "en-GB"
    assert client.put("/api/outreach-profile", json={**p, "sender_name": "中文姓名"}).status_code == 409
    assert client.put("/api/outreach-profile", json={**p, "website": "javascript:alert(1)"}).status_code == 409
    saved = client.put("/api/outreach-profile", json=p)
    assert saved.status_code == 200, saved.text
    assert saved.json()["company"] == p["company"]
    assert client.put("/api/outreach-profile", json=p).status_code == 409


def test_personal_signature_isolation_and_version(client, db):
    login(client, db)
    client.put("/api/outreach-profile", json=profile(client))
    member = make_operator(db, "salesperson")
    member.role = "member"
    db.commit()
    c = session(member)
    own = c.get("/api/outreach-identity").json()
    assert own["sender_identity"] == "Tom\nDesigner\nExample Studio"
    changed = c.put("/api/outreach-identity", json={**own, "name": "Alice"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["sender_identity"].startswith("Alice\n")
    assert client.get("/api/outreach-identity").json()["sender_identity"].startswith("Tom\n")
    assert c.put("/api/outreach-identity", json=own).status_code == 409
    assert c.post("/api/outreach-profile/preview", json=profile(client)).status_code == 403
    assert c.post("/api/outreach-profile/organise", json=profile(client)).status_code == 403
    assert c.put("/api/outreach-identity", json={**changed.json(), "name": "中文"}).status_code == 422
    viewer = make_operator(db, "reader")
    viewer.role = "viewer"
    db.commit()
    assert session(viewer).put("/api/outreach-identity", json=own).status_code == 403


def test_preview_uses_unsaved_facts_without_creating_records(client, db, monkeypatch):
    login(client, db)
    before = db.scalar(select(func.count(AuditLog.id)))
    seen = []

    def generate(task):
        seen.append(task)
        return result(translation_zh="请问谁负责菜单？")

    monkeypatch.setattr(outreach_ai, "generate", generate)
    p = profile(client)
    r = client.post("/api/outreach-profile/preview", json=p)
    assert r.status_code == 200, r.text
    assert r.json()["body"].endswith(p["opt_out_text"])
    assert "Tom\nDesigner\nExample Studio" in r.json()["body"]
    assert r.json()["translation_zh"] and r.json()["preview_only"]
    assert seen[0]["language"] == "en-GB" and seen[0]["tone"] == "warm"
    assert "fictional" in seen[0]["sources"][0]["text"]
    assert client.get("/api/outreach-profile").json()["company"] == ""
    assert db.scalar(select(func.count(AuditLog.id))) == before
    assert db.scalar(select(func.count(ContentPiece.id))) == 0
    assert db.scalar(select(func.count(ManualTask.id))) == 0
    assert client.post("/api/outreach-profile/preview", json={**p, "english_brand": ""}).status_code == 422
    monkeypatch.setattr(outreach_ai, "generate", lambda _: result(cited_ids=["invented"]))
    assert client.post("/api/outreach-profile/preview", json=p).status_code == 422


def test_organise_does_not_save_and_model_failure_keeps_facts(client, db, monkeypatch):
    login(client, db)

    class Judge:
        model = "test-model"

        def _judge(self, task, documents, schema, system):
            assert "菜单排版设计" in documents[0]["text"]
            assert "Never invent" in system
            return schema.model_validate(
                {
                    "english_summary": "We design menus.",
                    "missing": ["作品链接"],
                    "citations": [{"document_id": "profile", "quote": "菜单排版设计", "kind": "identity"}],
                }
            )

    monkeypatch.setattr(profile_tools, "ResearchJudge", Judge)
    r = client.post("/api/outreach-profile/organise", json=profile(client))
    assert r.status_code == 200, r.text
    assert r.json()["english_summary"] == "We design menus."
    assert client.get("/api/outreach-profile").json()["services"] == ""

    def unavailable():
        raise RuntimeError("offline")

    monkeypatch.setattr(profile_tools, "ResearchJudge", unavailable)
    assert client.post("/api/outreach-profile/organise", json=profile(client)).status_code == 503
    assert client.get("/api/outreach-profile").json()["services"] == ""


def test_identity_is_appended_once_without_removing_body_mentions():
    import pytest

    from app.modules.content.service import ContentError

    text = outreach_ai.append_identity(
        "I am Tom from Example Studio. Could you share a menu?\n\nKind regards,\nTom\nExample Studio\nNo more emails.",
        "Tom\nExample Studio",
        "No more emails.",
    )
    assert text == "I am Tom from Example Studio. Could you share a menu?\n\nTom\nExample Studio\n\nNo more emails."
    embedded = outreach_ai.append_identity("Could you share a menu? No more emails.", "Tom", "No more emails.")
    assert embedded.count("No more emails.") == 1
    with pytest.raises(ContentError):
        outreach_ai.append_identity("Tom", "Tom", "No more emails.")


def test_brand_misfill_is_rejected_and_legacy_identity_reports_problem(client, db, monkeypatch):
    login(client, db)
    bad = {**profile(client), "english_brand": "We help restaurants with menu layout design and printed menus."}
    assert client.put("/api/outreach-profile", json=bad).status_code == 409
    legacy = outreach_ai.ServiceProfile(**bad)
    monkeypatch.setattr(profile_tools.ai, "profile", lambda db: legacy)
    response = client.get("/api/outreach-identity")
    assert response.status_code == 200
    assert response.json()["sender_identity"] == ""
    assert "不能填写服务介绍" in response.json()["configuration_error"]
    monkeypatch.setattr(outreach_ai, "generate", lambda _: __import__("pytest").fail("invalid brand must not reach AI"))
    assert client.post("/api/outreach-profile/preview", json=bad).status_code == 422


def test_service_facts_do_not_contain_internal_instructions():
    import json

    p = outreach_ai.ServiceProfile(
        company="Studio", services="Layout", constraints="Only cite checked facts", sender_name="Tom"
    )
    facts = json.loads(outreach_ai.service_source(p))
    assert facts["services"] == "Layout"
    assert "constraints" not in facts and "sender_name" not in facts and "opt_out_text" not in facts
    assert "never customer-facing copy" in outreach_ai.SYSTEM
    assert "Never infer that an academy" in outreach_ai.SYSTEM


def test_real_generation_retries_invalid_language_once(db, monkeypatch):
    import json
    from types import SimpleNamespace

    import httpx
    import pytest

    from app.core.config import get_settings
    from app.integrations.llm import ProviderUnavailable

    calls = []
    always_bad = False

    def handle(request):
        calls.append(json.loads(request.content))
        message, _ = result()
        if len(calls) == 1 or always_bad:
            message.body = "您好，请问谁负责菜单？"
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": message.model_dump_json()}}]}
        )

    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(
        outreach_ai,
        "DeepSeekProvider",
        lambda: SimpleNamespace(
            base_url="https://model.example", key="test", model="fake-test", _transport=httpx.MockTransport(handle)
        ),
    )
    generated, _ = outreach_ai.generate({"language": "en-GB"})
    assert generated.body.startswith("Could you") and len(calls) == 2
    assert "output_correction" in calls[1]["messages"][1]["content"]
    always_bad = True
    calls.clear()
    with pytest.raises(ProviderUnavailable):
        outreach_ai.generate({"language": "en-GB"})
    assert len(calls) == 2
    message, _ = result(body="Hello, I am [Name].")
    with pytest.raises(outreach_ai.service.ContentError):
        outreach_ai.validate_generated(message)
