"""Navigation observations use mock models and never operate a phone."""

import json
from types import SimpleNamespace

import pytest
from app.modules.mobile import navigation

from tests.test_mobile import enqueue, setup


def page():
    return navigation.Screen.model_validate(
        {
            "screen_id": "a" * 64,
            "package": "com.whatsapp",
            "width": 1080,
            "height": 2400,
            "nodes": [{"id": 2, "text": "Message", "clickable": True, "bounds": [10, 20, 200, 100]}],
        }
    )


def checked_reply(messages, value):
    assert '"properties"' in messages[0]["content"] and '"confidence"' in messages[0]["content"]
    return SimpleNamespace(text=json.dumps(value), usage={})


def model(monkeypatch, **changes):
    value = {"action": "open_messages", "node_id": 2, "confidence": "high", "detail": "打开私信", **changes}
    fake = SimpleNamespace(
        model="mock",
        name="mock",
        connection_id="test",
        version="test",
        value={"vision": False},
        complete=lambda messages, *args: checked_reply(messages, value),
    )
    monkeypatch.setattr(navigation.ai_runtime, "client", lambda purpose: fake)


def test_navigation_returns_existing_control(monkeypatch):
    model(monkeypatch)
    result = navigation.advise.__wrapped__(page(), {"channel": "whatsapp", "target": "+447700900123"})
    assert result["node_id"] == 2 and result["screen_id"] == "a" * 64


@pytest.mark.parametrize(
    "changes",
    [
        {"node_id": 999},
        {"node_id": None, "x": 20, "y": 20},
        {"action": "ready", "title_node_id": 999, "target_match": True},
        {"action": "send"},
    ],
)
def test_invalid_or_invented_actions_rejected(monkeypatch, changes):
    model(monkeypatch, **changes)
    with pytest.raises(ValueError):
        navigation.advise.__wrapped__(page(), {"channel": "whatsapp", "target": "test"})


def test_wrong_package_and_duplicate_nodes_rejected_before_model(monkeypatch):
    monkeypatch.setattr(navigation.ai_runtime, "client", lambda purpose: pytest.fail("no model"))
    with pytest.raises(ValueError):
        navigation.advise.__wrapped__(page(), {"channel": "facebook", "target": "test"})
    p = page()
    p.nodes.append(p.nodes[0])
    with pytest.raises(ValueError):
        navigation.advise.__wrapped__(p, {"channel": "whatsapp", "target": "test"})


def test_low_confidence_does_not_click(monkeypatch):
    model(monkeypatch, confidence="low")
    assert navigation.advise.__wrapped__(page(), {"channel": "whatsapp", "target": "test"})["action"] == "needs_action"


def test_progress_and_navigation_do_not_block_final_result(client, db, monkeypatch):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    c = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    base = f"/api/mobile/device/jobs/{job['id']}"
    args = {"lease": c["lease"], "attempt": c["attempt"]}
    model(monkeypatch)
    assert client.post(base + "/progress", headers=headers, json={**args, "stage": "finding_entry"}).status_code == 200
    for _ in range(4):
        r = client.post(base + "/navigation", headers=headers, json={**args, "screen": page().model_dump()})
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "open_messages"
    r = client.post(base + "/navigation", headers=headers, json={**args, "screen": page().model_dump()})
    assert r.json()["action"] == "needs_action"
    assert client.post(base + "/start", headers=headers, json=args).status_code == 200
    result = {**args, "status": "request_submitted", "detail": "对方需要接受消息请求"}
    for _ in range(2):
        r = client.post(base + "/result", headers=headers, json=result)
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "request_submitted"
    assert (
        client.post(base + "/navigation", headers=headers, json={**args, "screen": page().model_dump()}).status_code
        == 409
    )


def test_cancelled_job_cannot_request_navigation(client, db, monkeypatch):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    claimed = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    assert client.post(f"/api/mobile/tasks/{tid}/cancel").status_code == 200
    monkeypatch.setattr(navigation.ai_runtime, "client", lambda purpose: pytest.fail("cancelled job called AI"))
    args = {"lease": claimed["lease"], "attempt": claimed["attempt"], "screen": page().model_dump()}
    r = client.post(f"/api/mobile/device/jobs/{job['id']}/navigation", headers=headers, json=args)
    assert r.status_code == 409


def test_close_popup_without_position_uses_back(monkeypatch):
    model(monkeypatch, action="close_popup", node_id=None)
    assert navigation.advise.__wrapped__(page(), {"channel": "whatsapp", "target": "test"})["action"] == "back"
