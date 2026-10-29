"""AI sales drafting uses local evidence and never approves/sends. No real model calls."""

import pytest

from app.integrations.llm import ProviderUnavailable
from app.modules.content import outreach_ai
from tests.test_assets import setup_lead
from tests.test_content import IDENT, OPTOUT, _reviewed


def configure(client):
    p = client.get("/api/outreach-profile").json()
    p.update(company="Menu Studio", services="Menu design and printing", proof="", constraints="No price promises")
    response = client.put("/api/outreach-profile", json=p)
    assert response.status_code == 200, response.text
    return response.json()


def request(client, lead, **extra):
    return client.post(
        f"/api/leads/{lead}/outreach-message",
        json={
            "sender_identity": IDENT,
            "opt_out_text": OPTOUT,
            "channel": "email",
            **extra,
        },
    )


def result(**extra):
    return outreach_ai.GeneratedMessage(
        **{
            "subject": "Menu design and printing",
            "body": "Could you connect us with the person responsible for menus?",
            "cited_ids": ["store", "services"],
            "rationale": "结合门店与真实服务，询问菜单负责人",
            "missing": ["当前菜单"],
            **extra,
        }
    ), "test-model"


def test_profile_required_and_model_failure_does_not_create_content(client, db, monkeypatch):
    identity = setup_lead(client, db)
    monkeypatch.setattr(outreach_ai, "generate", lambda _: pytest.fail("must not call before profile"))
    assert request(client, identity).status_code == 409
    configure(client)

    def fail(_):
        raise ProviderUnavailable("模型暂不可用")

    monkeypatch.setattr(outreach_ai, "generate", fail)
    assert request(client, identity).status_code == 503
    assert client.get(f"/api/leads/{identity}/content").json() == []


def test_inquiry_subject_revision_and_profile_change_invalidate_confirmation(client, db, monkeypatch):
    identity = setup_lead(client, db)
    configure(client)
    seen = []

    def capture(task):
        seen.append(task)
        return result()

    monkeypatch.setattr(outreach_ai, "generate", capture)
    response = request(client, identity)
    assert response.status_code == 201, response.text
    piece = response.json()
    assert not seen[0]["has_reviewed_menu"]
    assert piece["engine"] == "ai:test-model" and not piece["approval_valid"]
    assert IDENT in piece["body_text"] and OPTOUT in piece["body_text"]
    assert piece["spec"]["subject"] == "Menu design and printing"
    approved = client.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"})
    assert approved.json()["approval_valid"]
    revised = client.post(
        f"/api/content/{piece['id']}/revise", json={"body_text": piece["body_text"], "subject": "Menu collaboration"}
    )
    assert revised.status_code == 201, revised.text
    assert not revised.json()["approval_valid"]
    client.post(f"/api/content/{revised.json()['id']}/approve", json={"decision": "approved"})
    configure(client)
    contents = client.get(f"/api/leads/{identity}/content").json()
    assert not contents[-1]["approval_valid"]


def test_reviewed_menu_without_problems_can_generate_cooperation_message(client, db, monkeypatch):
    identity, _, analysis = _reviewed(client, db, confirm_issue=False)
    configure(client)

    def generate(task):
        menu = next(s for s in task["sources"] if s["id"] == "menu")
        assert '"confirmed_problems": []' in menu["text"]
        assert task["has_reviewed_menu"]
        return result(cited_ids=["store", "services", "menu"], missing=[])

    monkeypatch.setattr(outreach_ai, "generate", generate)
    response = request(client, identity, analysis_id=analysis["id"])
    assert response.status_code == 201, response.text
    assert response.json()["spec"]["cited_issue_indexes"] == []
    assert client.post(f"/api/content/{response.json()['id']}/approve", json={"decision": "approved"}).json()[
        "approval_valid"
    ]
    context = client.get(f"/api/communication/leads/{identity}").json()
    assert context["analyses"] and context["contents"][0]["rationale"]


@pytest.mark.parametrize(
    "invalid",
    [
        {"cited_ids": ["fake_source", "services"]},
        {"body": "We prepared a sample menu for you."},
        {"body": "Your menu has layout problems."},
        {"subject": "first\nsecond"},
    ],
)
def test_invalid_output_not_saved(client, db, monkeypatch, invalid):
    identity = setup_lead(client, db)
    configure(client)
    monkeypatch.setattr(outreach_ai, "generate", lambda _: result(**invalid))
    assert request(client, identity).status_code == 409
    assert not client.get(f"/api/leads/{identity}/content").json()


def test_other_store_menu_rejected_before_model_call(client, db, monkeypatch):
    from app.modules.leads.models import Lead

    identity, _, analysis = _reviewed(client, db)
    configure(client)
    other = Lead(source_key="test:other", source_name="test", name="Other")
    db.add(other)
    db.commit()
    monkeypatch.setattr(outreach_ai, "generate", lambda _: pytest.fail("cross-store data"))
    assert request(client, other.id, analysis_id=analysis["id"]).status_code == 409


def test_social_message_and_profile_permissions(client, db, monkeypatch):
    from sqlalchemy import select

    from app.core.models import Operator

    identity = setup_lead(client, db)
    saved = configure(client)
    monkeypatch.setattr(outreach_ai, "generate", lambda task: result(subject="", missing=[]))
    response = request(client, identity, channel="linkedin")
    assert response.status_code == 201, response.text
    assert response.json()["spec"]["channel"] == "linkedin"
    assert response.json()["spec"]["subject"] == ""
    op = db.scalar(select(Operator).where(Operator.username == "tester"))
    op.role = "member"
    db.commit()
    assert client.get("/api/outreach-profile").status_code == 200
    assert client.put("/api/outreach-profile", json=saved).status_code == 403


def test_fake_provider_never_generates_ai_message(db, monkeypatch):

    with pytest.raises(ProviderUnavailable):
        outreach_ai.generate({})


def test_member_cannot_draft_for_unassigned_store(client, db, monkeypatch):
    from sqlalchemy import select

    from app.core.models import Operator

    identity = setup_lead(client, db)
    configure(client)
    op = db.scalar(select(Operator).where(Operator.username == "tester"))
    op.role = "member"
    db.commit()
    monkeypatch.setattr(outreach_ai, "generate", lambda _: pytest.fail("unassigned store reached model"))
    assert request(client, identity).status_code == 404


def test_message_cannot_be_reused_for_different_recipient(client, db, monkeypatch):
    from tests.test_sales import _elig

    identity = setup_lead(client, db)
    configure(client)
    first = _elig(client, identity).json()
    second = _elig(client, identity, contact_ref="other@example.com").json()
    monkeypatch.setattr(outreach_ai, "generate", lambda _: result())
    piece = request(client, identity, eligibility_id=first["id"]).json()
    assert client.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"}).status_code == 200
    response = client.post(
        f"/api/leads/{identity}/tasks", json={"eligibility_id": second["id"], "content_id": piece["id"]}
    )
    assert response.status_code == 409 and "联系人" in response.json()["detail"]


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_real_provider_protocol_uses_structured_output_without_network(db, monkeypatch, finish):

    import httpx

    def respond(request):
        import json

        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert "output_schema" in payload["messages"][1]["content"]
        return httpx.Response(
            200, json={"choices": [{"finish_reason": finish, "message": {"content": result()[0].model_dump_json()}}]}
        )

    monkeypatch.setattr(
        outreach_ai,
        "model_client",
        lambda purpose: __import__("app.integrations.ai_runtime", fromlist=["Client"]).Client(
            {
                "provider": "deepseek",
                "protocol": "chat",
                "model": "test-model",
                "base_url": "https://model.example",
                "key": "test",
                "json_mode": True,
            },
            httpx.MockTransport(respond),
        ),
    )
    if finish == "stop":
        assert outreach_ai.generate({"sources": []})[0].subject == "Menu design and printing"
    else:
        with pytest.raises(ProviderUnavailable):
            outreach_ai.generate({"sources": []})
