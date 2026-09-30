"""D8/D9：unknown/blocked 不生成任务；allowed 需证据；未审批内容不生成任务；抑制阻断；打开只记打开；
记录发送需操作者与时间且再次复核；事件幂等；回复暂停；拒绝抑制并取消；退信使联系失效。"""

from datetime import UTC, datetime, timedelta

from tests.test_analysis import _upload
from tests.test_assets import setup_lead
from tests.test_content import IDENT, OPTOUT


def _ready(client, db):
    """线索 + 已审核分析（含已确认问题）+ 已审批文案。"""
    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, "two_col.pdf", "application/pdf")
    a = client.post(f"/api/assets/{aid}/analyses").json()
    a = client.patch(
        f"/api/analyses/{a['id']}", json={"corrections": [{"field_path": "issues[0].confirmed", "new_value": True}]}
    ).json()
    a = client.post(f"/api/analyses/{a['id']}/review").json()
    c = client.post(
        f"/api/leads/{lead_id}/content",
        json={"kind": "message_short", "analysis_id": a["id"], "sender_identity": IDENT, "opt_out_text": OPTOUT},
    ).json()
    client.post(f"/api/content/{c['id']}/approve", json={"decision": "approved"})
    return lead_id, a, c


def _elig(client, lead_id, **kw):
    body = {
        "channel": "email",
        "contact_ref": "info@example.com",
        "contact_usable": "valid",
        "eligibility": "allowed",
        "rule_version": "uk-b2b-2026-09",
        "evidence": "公司邮箱；ICO B2B 指引；来源官网法定页 2026-09-30",
    }
    body.update(kw)
    return client.post(f"/api/leads/{lead_id}/eligibility", json=body)


def test_allowed_requires_evidence_and_unknown_blocks_task(client, db):
    lead_id, a, c = _ready(client, db)
    r = _elig(client, lead_id, evidence="")
    assert r.status_code == 400
    r = _elig(client, lead_id, eligibility="unknown", evidence=None, rule_version=None)
    assert r.status_code == 200 and r.json()["reviewed_by"] == "tester"
    e = r.json()
    r = client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]})
    assert r.status_code == 409 and "unknown" in r.json()["detail"]
    e = _elig(client, lead_id, eligibility="blocked", evidence="TPS 命中").json()
    assert (
        client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).status_code
        == 409
    )


def test_task_lifecycle_open_and_sent(client, db):
    lead_id, a, c = _ready(client, db)
    e = _elig(client, lead_id).json()
    r = client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "pending" and t["content_hash"] == c["content_hash"]
    # 重复创建
    assert (
        client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).status_code
        == 409
    )
    # 记录发送前必须先打开
    assert client.post(f"/api/tasks/{t['id']}/sent", json={"sent_at": datetime.now(UTC).isoformat()}).status_code == 409
    t = client.post(f"/api/tasks/{t['id']}/open").json()
    assert t["status"] == "opened" and t["opened_by"] == "tester" and t["sent_at"] is None
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert client.post(f"/api/tasks/{t['id']}/sent", json={"sent_at": future}).status_code == 409
    sent_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    t = client.post(f"/api/tasks/{t['id']}/sent", json={"sent_at": sent_at, "notes": "sent from work mailbox"}).json()
    assert t["status"] == "sent_manual" and t["sent_by"] == "tester" and t["sent_recorded_at"] > t["sent_at"]
    assert client.post(f"/api/tasks/{t['id']}/cancel", json={"reason": "x"}).status_code == 409


def test_unapproved_or_changed_content_blocks(client, db):
    lead_id, a, c = _ready(client, db)
    e = _elig(client, lead_id).json()
    draft = client.post(
        f"/api/content/{c['id']}/revise", json={"body_text": c["body_text"].replace("Hello", "Hi")}
    ).json()
    r = client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": draft["id"]})
    assert r.status_code == 409 and "审批" in r.json()["detail"]
    # 旧内容已有更新版本 → 审批失效 → 也不能建任务
    assert (
        client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).status_code
        == 409
    )


def test_opened_task_pauses_when_source_changes(client, db):
    lead_id, a, c = _ready(client, db)
    e = _elig(client, lead_id).json()
    t = client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).json()
    t = client.post(f"/api/tasks/{t['id']}/open").json()
    client.patch(
        f"/api/analyses/{a['id']}", json={"corrections": [{"field_path": "items[0].name", "new_value": "Changed"}]}
    )
    r = client.post(f"/api/tasks/{t['id']}/sent", json={"sent_at": datetime.now(UTC).isoformat()})
    assert r.status_code == 409 and "审批无效" in r.json()["detail"]
    assert client.get(f"/api/tasks?lead_id={lead_id}").json()[0]["status"] == "paused"


def test_events_idempotent_reply_pauses_reject_suppresses(client, db):
    lead_id, a, c = _ready(client, db)
    e = _elig(client, lead_id).json()
    t = client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).json()
    r = client.post(
        f"/api/leads/{lead_id}/events",
        json={"event_key": "mail:abc", "kind": "reply", "channel": "email", "payload": {"summary": "asked for sample"}},
    )
    assert r.status_code == 200 and r.json()["duplicate"] is False and r.json()["actions"][0]["action"] == "pause_task"
    assert client.get(f"/api/tasks?lead_id={lead_id}").json()[0]["status"] == "paused"
    r2 = client.post(
        f"/api/leads/{lead_id}/events", json={"event_key": "mail:abc", "kind": "reply", "channel": "email"}
    )
    assert r2.json()["duplicate"] is True and r2.json()["id"] == r.json()["id"]
    assert len(client.get(f"/api/leads/{lead_id}/events").json()) == 1
    # 负责人决定恢复
    assert (
        client.post(f"/api/tasks/{t['id']}/resume", json={"reason": "reply was a question"}).json()["status"]
        == "pending"
    )
    # 拒绝 → 抑制 + 取消；即使没有任务也保存抑制
    r = client.post(
        f"/api/leads/{lead_id}/events",
        json={
            "event_key": "mail:def",
            "kind": "reject",
            "channel": "email",
            "payload": {"contact_ref": "info@example.com"},
        },
    )
    acts = {x["action"] for x in r.json()["actions"]}
    assert {"suppress_lead", "suppress_contact", "cancel_task"} <= acts
    assert client.get(f"/api/tasks?lead_id={lead_id}").json()[0]["status"] == "cancelled"
    assert len(client.get("/api/suppressions").json()) == 2
    # 抑制后不能再建任务
    assert (
        client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).status_code
        == 409
    )


def test_bounce_marks_contact_invalid(client, db):
    lead_id, a, c = _ready(client, db)
    e = _elig(client, lead_id).json()
    client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]})
    r = client.post(
        f"/api/leads/{lead_id}/events",
        json={
            "event_key": "mail:bounce1",
            "kind": "bounce",
            "channel": "email",
            "payload": {"contact_ref": "info@example.com"},
        },
    )
    assert {x["action"] for x in r.json()["actions"]} == {"contact_invalid", "cancel_task"}
    assert client.get(f"/api/leads/{lead_id}/eligibility").json()[0]["contact_usable"] == "invalid"
    assert (
        client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).status_code
        == 409
    )
