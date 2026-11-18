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
        assert (
            outreach_ai.generate(
                {"sources": [{"id": "store", "text": "Restaurant"}, {"id": "services", "text": "Design"}]}
            )[0].subject
            == "Menu design and printing"
        )
    else:
        with pytest.raises(ProviderUnavailable):
            outreach_ai.generate(
                {"sources": [{"id": "store", "text": "Restaurant"}, {"id": "services", "text": "Design"}]}
            )


@pytest.mark.parametrize("channel", ["email", "facebook", "whatsapp"])
def test_configured_company_website_is_appended_once_and_frozen(client, db, monkeypatch, channel):
    identity = setup_lead(client, db)
    offered = configure(client)
    saved = client.put("/api/outreach-profile", json={**offered, "website": "https://ai-onestep.com/zh-hans/"})
    assert saved.status_code == 200
    monkeypatch.setattr(
        outreach_ai,
        "generate",
        lambda _: result(
            body="Hi, we help restaurants with menu design and printing. Are you responsible for menu updates?"
        ),
    )
    response = request(client, identity, channel=channel, sender_identity=IDENT + "\nhttps://ai-onestep.com/")
    assert response.status_code == 201, response.text
    piece = response.json()
    assert "printing.\n\nAre you" in piece["body_text"]
    assert piece["body_text"].count("https://ai-onestep.com/en/") == 1
    assert "zh-hans" not in piece["body_text"]
    assert piece["spec"]["sender_identity"].endswith("https://ai-onestep.com/en/")
    client.put("/api/outreach-profile", json={**saved.json(), "website": "https://example.com/"})
    previous = next(p for p in client.get(f"/api/leads/{identity}/content").json() if p["id"] == piece["id"])
    assert previous["body_text"] == piece["body_text"]


def citation_client(monkeypatch, outputs, seen):
    import json

    import httpx

    from app.integrations.ai_runtime import Client

    def respond(request):
        payload = json.loads(request.content)
        seen.append(json.loads(payload["messages"][1]["content"])["data"])
        value = outputs[min(len(seen) - 1, len(outputs) - 1)]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": result(**value)[0].model_dump_json(),
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(
        outreach_ai,
        "model_client",
        lambda _: Client(
            {
                "provider": "deepseek",
                "protocol": "chat",
                "model": "citation-test",
                "base_url": "https://model.example",
                "key": "test",
                "json_mode": True,
            },
            httpx.MockTransport(respond),
        ),
    )


@pytest.mark.parametrize(
    "action,expected",
    [
        ("initial", ["menu", "services", "store"]),
        ("followup", ["conversation"]),
        ("reply", ["conversation"]),
        ("shorten", ["current_draft"]),
    ],
)
def test_citation_requirements_follow_actual_writing_action(action, expected):
    task = {
        "writing_action": action,
        "has_reviewed_menu": True,
        "sources": [
            {"id": "store", "text": "Restaurant"},
            {"id": "services", "text": "Menu design"},
            {"id": "menu", "text": "Reviewed menu"},
            {"id": "conversation", "text": '[{"body":"Thanks"}]'},
            {"id": "current_draft", "text": "Could we help?"},
        ],
    }
    policy = outreach_ai.citation_requirements(task)
    assert policy["required_ids"] == expected
    outreach_ai.validate_citations(result(cited_ids=expected)[0], task)
    with pytest.raises(outreach_ai.CitationError):
        outreach_ai.validate_citations(result(cited_ids=[*expected, "invented"])[0], task)


def test_empty_conversation_falls_back_to_store_and_services():
    task = {
        "writing_action": "reply",
        "sources": [
            {"id": "store", "text": "Restaurant"},
            {"id": "services", "text": "Design"},
            {"id": "conversation", "text": "[]"},
        ],
    }
    assert outreach_ai.citation_requirements(task)["required_ids"] == ["services", "store"]
    with pytest.raises(outreach_ai.CitationError):
        outreach_ai.validate_citations(result(cited_ids=["conversation"])[0], task)


@pytest.mark.parametrize("invalid", [["wrong", "services"], ["store"], []])
def test_invalid_citations_are_regenerated_once_with_explicit_source_ids(db, monkeypatch, invalid):
    seen: list[dict] = []
    citation_client(monkeypatch, [{"cited_ids": invalid}, {}], seen)
    task = {"sources": [{"id": "store", "text": "Restaurant"}, {"id": "services", "text": "Design"}]}
    generated, _ = outreach_ai.generate(task)
    assert generated.cited_ids == ["store", "services"]
    assert len(seen) == 2
    assert seen[1]["previous_cited_ids"] == invalid
    assert seen[1]["citation_requirements"] == {
        "allowed_ids": ["services", "store"],
        "required_ids": ["services", "store"],
    }
    assert "previous_output_error" in seen[1] and "Regenerate" in seen[1]["output_correction"]


def test_two_invalid_citation_outputs_leave_existing_draft_unchanged(client, db, monkeypatch):
    from tests.test_conversations import prepare_message, write
    from tests.test_sales import _elig, _ready

    identity, _, _ = _ready(client, db)
    configure(client)
    contact = _elig(client, identity).json()["id"]
    draft = write(client, prepare_message(client, identity, contact), "My existing draft")
    original = client.get(f"/api/leads/{identity}/content").json()
    seen: list[dict] = []
    citation_client(monkeypatch, [{"cited_ids": ["invented"]}], seen)
    response = request(
        client, identity, eligibility_id=contact, conversation_draft_id=draft["id"], writing_action="shorten"
    )
    assert response.status_code == 503, response.text
    assert "原草稿未修改" in response.json()["detail"]
    assert len(seen) == 2
    assert client.get(f"/api/leads/{identity}/content").json() == original
    assert client.get(f"/api/communication/drafts/{draft['id']}").json()["content_id"] == draft["content_id"]


@pytest.mark.parametrize(
    "action,cited", [("followup", "conversation"), ("reply", "conversation"), ("shorten", "current_draft")]
)
def test_context_only_citations_are_valid_for_followups_replies_and_shortening(client, db, monkeypatch, action, cited):
    from tests.test_conversations import prepare_message, write
    from tests.test_sales import _elig, _ready

    identity, _, _ = _ready(client, db)
    configure(client)
    contact = _elig(client, identity).json()["id"]
    draft = write(client, prepare_message(client, identity, contact))
    assert (
        client.post(
            f"/api/communication/conversations/{identity}/{contact}/reply",
            json={"event_key": "manual:context", "summary": "Please speak to our manager"},
        ).status_code
        == 200
    )
    monkeypatch.setattr(outreach_ai, "generate", lambda _: result(cited_ids=[cited]))
    response = request(
        client, identity, eligibility_id=contact, conversation_draft_id=draft["id"], writing_action=action
    )
    assert response.status_code == 201, response.text
    assert response.json()["spec"]["cited_ids"] == [cited]


def test_menu_reference_is_required_for_initial_menu_message(db, monkeypatch):
    seen: list[dict] = []
    citation_client(monkeypatch, [{}, {"cited_ids": ["store", "services", "menu"]}], seen)
    task = {
        "has_reviewed_menu": True,
        "sources": [
            {"id": "store", "text": "Restaurant"},
            {"id": "services", "text": "Design"},
            {"id": "menu", "text": "Reviewed menu"},
        ],
    }
    generated, _ = outreach_ai.generate(task)
    assert "menu" in generated.cited_ids and len(seen) == 2
    assert seen[1]["citation_requirements"]["required_ids"] == ["menu", "services", "store"]


def test_valid_context_citation_does_not_trigger_retry(db, monkeypatch):
    seen: list[dict] = []
    citation_client(monkeypatch, [{"cited_ids": ["conversation"]}], seen)
    task = {
        "writing_action": "reply",
        "sources": [
            {"id": "store", "text": "Restaurant"},
            {"id": "services", "text": "Design"},
            {"id": "conversation", "text": '[{"body":"Please speak to our manager"}]'},
        ],
    }
    assert outreach_ai.generate(task)[0].cited_ids == ["conversation"]
    assert len(seen) == 1
