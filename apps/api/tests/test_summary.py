"""D9：成本三类分列；汇总按门店去重、零分母写不适用；导出 CSV 含分类原因与状态。"""

from datetime import UTC, datetime

from tests.test_sales import _elig, _ready


def test_summary_zero_denominators_and_costs(client, db):
    lead_id, a, c = _ready(client, db)  # 批次 b1，1 家；有确认问题与审批内容，但未准入、未发送
    s = client.get("/api/batches/b1/summary").json()
    assert s["counts"] == {"N": 1, "M": 1, "I": 1, "E": 0, "S": 0, "R": 0, "P": 0, "Q": 0}
    assert s["ratios"]["R/S"]["value"] is None and "不适用" in s["ratios"]["R/S"]["note"]
    assert s["commercial_status"].startswith("未验证")
    # 成本：三类分列
    for cat, amt, mins in [("setup", "120.00", 60), ("processing", None, 25), ("outreach", "3.50", 10)]:
        body = {
            "lead_id": lead_id,
            "category": cat,
            "currency": "GBP" if amt else None,
            "amount": amt,
            "minutes": mins,
            "basis": "test",
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        r = client.post("/api/costs", json=body)
        assert r.status_code == 201, r.text
    assert (
        client.post(
            "/api/costs", json={"lead_id": lead_id, "category": "setup", "occurred_at": datetime.now(UTC).isoformat()}
        ).status_code
        == 400
    )
    s = client.get("/api/batches/b1/summary").json()
    assert s["costs"]["setup"]["amount_by_currency"] == {"GBP": "120.00"} and s["costs"]["processing"]["minutes"] == 25
    assert s["unit_costs"]["cost_per_contactable"] is None  # E=0


def test_summary_counts_after_eligibility_send_and_reply(client, db):
    lead_id, a, c = _ready(client, db)
    # 把线索标为候选，准入 allowed → E=1
    client.patch(f"/api/leads/{lead_id}", json={"screening_class": "candidate", "screening_reason": "独立堂食"})
    e = _elig(client, lead_id).json()
    s = client.get("/api/batches/b1/summary").json()
    assert s["counts"]["E"] == 1 and s["ratios"]["E/N"]["value"] == 1.0
    t = client.post(f"/api/leads/{lead_id}/tasks", json={"eligibility_id": e["id"], "content_id": c["id"]}).json()
    client.post(f"/api/tasks/{t['id']}/open")
    client.post(f"/api/tasks/{t['id']}/sent", json={"sent_at": datetime.now(UTC).isoformat()})
    client.post(
        f"/api/leads/{lead_id}/events",
        json={"event_key": "m1", "kind": "reply", "channel": "email", "payload": {"intent": "quote"}},
    )
    client.post(
        f"/api/leads/{lead_id}/events",
        json={"event_key": "m2", "kind": "reply", "channel": "phone", "payload": {"intent": "positive"}},
    )
    s = client.get("/api/batches/b1/summary").json()
    assert (
        s["counts"]["S"] == 1 and s["counts"]["R"] == 1 and s["counts"]["P"] == 1 and s["counts"]["Q"] == 1
    )  # 两渠道回复按门店去重
    assert s["by_channel"] == {"email": {"sent": 1, "replied": 1}, "phone": {"sent": 0, "replied": 1}}
    assert s["ratios"]["P/S"]["value"] == 1.0
    csv_text = client.get("/api/batches/b1/export.csv").text
    assert "source_key" in csv_text.splitlines()[0] and "fsa:1" in csv_text and "True" in csv_text
    assert client.get("/api/batches/nope/summary").status_code == 404
