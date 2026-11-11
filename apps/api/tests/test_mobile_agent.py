"""AI execution decisions use fake models, never a phone or external messages."""

import json
from types import SimpleNamespace

import pytest

from app.modules.mobile import agent
from tests.test_mobile import enqueue, setup
from tests.test_mobile_navigation import page


def model(monkeypatch, **changes):
    value = {"action": "tap", "node_id": 2, "confidence": "high", "detail": "打开消息", **changes}
    fake = SimpleNamespace(
        model="fake-mobile",
        name="fake",
        connection_id="test",
        version="v1",
        value={"vision": False},
        complete=lambda *a: SimpleNamespace(text=json.dumps(value), usage={}),
    )
    monkeypatch.setattr(agent.ai_runtime, "client", lambda _: fake)


def test_ai_action_bound_to_real_node(monkeypatch):
    model(monkeypatch)
    r = agent.decide.__wrapped__(page(), {"channel": "whatsapp", "target": "+447700900123", "body": "hello"})
    assert r["action"] == "tap" and r["node_id"] == 2
    assert r["screen_id"] == page().screen_id


@pytest.mark.parametrize(
    "changes",
    [
        {"node_id": 500},
        {"node_id": None, "x": 30, "y": 50},
        {"action": "input"},
        {"action": "send"},
        {"action": "finish", "outcome": "sent"},
        {"action": "alternate"},
    ],
)
def test_invalid_actions_fail_closed(monkeypatch, changes):
    model(monkeypatch, **changes)
    with pytest.raises(ValueError):
        agent.decide.__wrapped__(page(), {"channel": "whatsapp", "target": "test"})


def test_sender_can_only_observe_after_send(monkeypatch):
    model(monkeypatch, action="send")
    with pytest.raises(ValueError, match="只能观察"):
        agent.decide.__wrapped__(page(), {"channel": "whatsapp"}, sending=True)
    model(monkeypatch, confidence="low")
    assert agent.decide.__wrapped__(page(), {"channel": "whatsapp"}, sending=True)["outcome"] == "unknown"


def test_input_and_send_use_frozen_content_without_model_text(monkeypatch):
    p = page()
    p.nodes.append(type(p.nodes[0])(id=3, text="Test recipient", bounds=[0, 0, 200, 40]))
    p.nodes[0].editable = True
    model(monkeypatch, action="input", target_match=True, title_node_id=3)
    value = agent.decide.__wrapped__(p, {"channel": "whatsapp", "body": "frozen"})
    assert value["action"] == "input" and "body" not in value
    p.nodes[0].editable = False
    model(monkeypatch, action="send", target_match=True, title_node_id=3)
    assert agent.decide.__wrapped__(p, {"channel": "whatsapp"})["action"] == "send"


def test_job_agent_progress_then_send_is_read_only(client, db, monkeypatch):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    claimed = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    base = f"/api/mobile/device/jobs/{job['id']}"
    args = {"lease": claimed["lease"], "attempt": claimed["attempt"]}
    model(monkeypatch)
    r = client.post(base + "/agent", headers=headers, json={**args, "screen": page().model_dump()})
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "tap"
    saved = client.get(f"/api/mobile/tasks/{tid}").json()
    assert saved["engine"] == "ai-agent-v1" and len(saved["agent_history"]) == 1
    assert client.post(base + "/start", headers=headers, json=args).status_code == 200
    r = client.post(base + "/agent", headers=headers, json={**args, "screen": page().model_dump()})
    assert r.json()["action"] == "finish" and r.json()["outcome"] == "unknown"


def test_cancel_during_model_call_discards_action(client, db, monkeypatch):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    claimed = client.post("/api/mobile/device/claim", headers=headers).json()["job"]

    def decide(*args, **kwargs):
        assert client.post(f"/api/mobile/tasks/{tid}/cancel").status_code == 200
        return {"action": "tap", "detail": "must be discarded"}

    monkeypatch.setattr(agent, "decide", decide)
    r = client.post(
        f"/api/mobile/device/jobs/{job['id']}/agent",
        headers=headers,
        json={"lease": claimed["lease"], "attempt": claimed["attempt"], "screen": page().model_dump()},
    )
    assert r.status_code == 409


def test_protocol_three_selects_agent_and_public_action_requires_new_app(client, db):
    from tests.test_mobile_channels import social_task

    tid, device, headers, heartbeat = social_task(client, db)
    url = f"/api/mobile/tasks/{tid}/preview"
    args = {"device_id": device["device_id"], "preview_hash": "0" * 64, "action": "public_comment"}
    assert client.post(url, json=args).status_code == 409
    heartbeat["protocol"] = 3
    assert client.post("/api/mobile/device/heartbeat", headers=headers, json=heartbeat).status_code == 200
    reply = client.post(url, json=args)
    assert reply.status_code == 200, reply.text
    assert reply.json()["payload"]["engine"] == "ai-agent-v1"
    assert reply.json()["payload"]["action"] == "public_comment"


def test_alternate_contact_is_recorded_without_sending(client, db, monkeypatch):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    claimed = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    model(monkeypatch, action="alternate", alternate_channel="email")
    reply = client.post(
        f"/api/mobile/device/jobs/{job['id']}/agent",
        headers=headers,
        json={"lease": claimed["lease"], "attempt": claimed["attempt"], "screen": page().model_dump()},
    )
    assert reply.status_code == 200, reply.text
    saved = client.get(f"/api/mobile/tasks/{tid}").json()
    assert saved["status"] == "claimed"
    assert saved["alternate_contact"]["channel"] == "email"


@pytest.mark.parametrize("target,expected", [("+44 7700 900123", "+44 7700 900123"), ("+441234567890", None)])
def test_alternate_number_must_be_visible(monkeypatch, target, expected):
    screen = page()
    screen.nodes[0].text = "WhatsApp +44 7700 900123"
    model(monkeypatch, action="alternate", alternate_channel="whatsapp", alternate_target=target)
    reply = agent.decide.__wrapped__(screen, {"channel": "whatsapp"})
    assert reply["alternate_target"] == expected


def test_adopt_alternate_is_idempotent_and_never_sends(client, db, monkeypatch):
    from sqlalchemy import select

    from app.modules.mobile.models import Execution
    from app.modules.sales.models import ChannelEligibility, ManualTask

    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    claimed = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    model(monkeypatch, action="alternate", alternate_channel="email")
    assert (
        client.post(
            f"/api/mobile/device/jobs/{job['id']}/agent",
            headers=headers,
            json={
                "lease": claimed["lease"],
                "attempt": claimed["attempt"],
                "screen": page().model_dump(),
            },
        ).status_code
        == 200
    )
    url = f"/api/mobile/tasks/{tid}/alternate"
    assert client.post(url, json={"contact_ref": "not an email"}).status_code == 422
    result = client.post(url, json={"contact_ref": "test@example.org"})
    assert result.status_code == 200, result.text
    assert client.post(url, json={"contact_ref": "test@example.org"}).json() == result.json()
    db.expire_all()
    task = db.get(ManualTask, tid)
    assert task is not None and task.status.value != "sent_manual"
    assert db.scalar(select(Execution).where(Execution.id == job["id"])).status == "claimed"
    saved = db.get(ChannelEligibility, result.json()["contact_id"])
    assert saved is not None and saved.contact_source == job["snapshot"]["target"]
