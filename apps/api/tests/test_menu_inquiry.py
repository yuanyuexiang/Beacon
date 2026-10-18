"""无菜单也能审批并准备任务，保留来源、版本及准入门禁，不发送。"""

import uuid

from app.modules.leads.models import Lead
from tests.test_assets import setup_lead
from tests.test_communication import activate, prepare
from tests.test_content import IDENT, OPTOUT, _reviewed
from tests.test_sales import _elig


def inquiry(client, identity, **kw):
    return client.post(
        f"/api/leads/{identity}/content",
        json={"kind": "message_short", "mode": "menu_inquiry", "sender_identity": IDENT, "opt_out_text": OPTOUT, **kw},
    )


def test_no_menu_approval_and_task_gates(client, db):
    identity = setup_lead(client, db)
    response = inquiry(client, identity)
    assert response.status_code == 201, response.text
    piece = response.json()
    assert piece["analysis_id"] is None and piece["spec"]["cited_issue_indexes"] == []
    assert not piece["approval_valid"] and "responsible" in piece["body_text"]
    assert "noticed" not in piece["body_text"] and "sample" not in piece["body_text"]
    elig = _elig(client, identity, eligibility="unknown", evidence=None, rule_version=None).json()
    task_body = {"eligibility_id": elig["id"], "content_id": piece["id"]}
    assert client.post(f"/api/leads/{identity}/tasks", json=task_body).status_code == 409
    approved = client.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"}).json()
    assert approved["approval_valid"]
    assert client.post(f"/api/leads/{identity}/tasks", json=task_body).status_code == 409
    _elig(client, identity)
    draft = prepare(client, identity)["draft"]
    assert draft["content_id"] == piece["id"] and not draft["blockers"]
    assert draft["context"]["contents"][0]["mode"] == "menu_inquiry"
    assert activate(client, draft["id"])["task_id"]
    assert client.get(f"/api/tasks?lead_id={identity}").json()[0]["status"] == "pending"


def test_inquiry_edit_new_version_and_identity_invalidation(client, db):
    identity = setup_lead(client, db)
    piece = inquiry(client, identity).json()
    cid = piece["id"]
    client.post(f"/api/content/{cid}/approve", json={"decision": "approved"})
    for body in [piece["body_text"].replace(OPTOUT, ""), piece["body_text"] + " We noticed your menu has errors."]:
        assert client.post(f"/api/content/{cid}/revise", json={"body_text": body}).status_code == 409
    edited = client.post(f"/api/content/{cid}/revise", json={"body_text": piece["body_text"].replace("Hello", "Dear")})
    assert edited.status_code == 201, edited.text
    assert edited.json()["version"] == 2 and not edited.json()["approval_valid"]
    assert not client.get(f"/api/content/{cid}").json()["approval_valid"]
    cid = edited.json()["id"]
    assert client.post(f"/api/content/{cid}/approve", json={"decision": "approved"}).json()["approval_valid"]
    lead = db.get(Lead, uuid.UUID(identity))
    lead.name = "Changed Restaurant"
    db.commit()
    assert not client.get(f"/api/content/{cid}").json()["approval_valid"]


def test_mode_is_explicit_and_does_not_bypass_analysis_or_sample(client, db):
    identity = setup_lead(client, db)
    assert inquiry(client, identity, kind="sample_partial").status_code == 409
    assert inquiry(client, identity, analysis_id=str(uuid.uuid4())).status_code == 409
    assert inquiry(client, identity, sender_identity="").status_code == 409
    assert inquiry(client, identity, opt_out_text="").status_code == 409
    assert inquiry(client, identity, mode="menu_analysis").status_code == 409
    assert inquiry(client, identity, mode="unknown").status_code == 422


def test_menu_analysis_path_still_available_after_inquiry(client, db):
    identity, _, analysis = _reviewed(client, db)
    piece = inquiry(client, identity).json()
    client.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"})
    diagnostic = client.post(
        f"/api/leads/{identity}/content",
        json={
            "kind": "message_short",
            "analysis_id": analysis["id"],
            "sender_identity": IDENT,
            "opt_out_text": OPTOUT,
        },
    )
    assert diagnostic.status_code == 201, diagnostic.text
    assert diagnostic.json()["analysis_id"] == analysis["id"]
    assert not client.get(f"/api/content/{piece['id']}").json()["approval_valid"]


def test_inquiry_does_not_bypass_suppression(client, db):
    identity = setup_lead(client, db)
    piece = inquiry(client, identity).json()
    client.post(f"/api/content/{piece['id']}/approve", json={"decision": "approved"})
    elig = _elig(client, identity).json()
    rejected = client.post(
        f"/api/leads/{identity}/events", json={"event_key": "inquiry-reject", "kind": "reject", "channel": "email"}
    )
    assert rejected.status_code == 200
    response = client.post(
        f"/api/leads/{identity}/tasks", json={"eligibility_id": elig["id"], "content_id": piece["id"]}
    )
    assert response.status_code == 409 and "抑制" in response.json()["detail"]
