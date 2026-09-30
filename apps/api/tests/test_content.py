"""D7：样稿只用确认数据；未审核不能生成；文案只引用已确认问题并含身份/退出方式；禁止新增事实；
审批绑定版本；内容或源数据修改后审批失效；编辑生成新版本。"""

from tests.test_analysis import _upload
from tests.test_assets import setup_lead

IDENT = "Beacon Menu Studio, 1 Example Street, London"
OPTOUT = "Reply STOP and we will not contact you again."


def _reviewed(client, db, confirm_issue=True):
    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, "two_col.pdf", "application/pdf")
    a = client.post(f"/api/assets/{aid}/analyses").json()
    if confirm_issue:
        a = client.patch(
            f"/api/analyses/{a['id']}", json={"corrections": [{"field_path": "issues[0].confirmed", "new_value": True}]}
        ).json()
    a = client.post(f"/api/analyses/{a['id']}/review").json()
    return lead_id, aid, a


def test_sample_requires_reviewed_and_uses_confirmed_data(client, db):
    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, "two_col.pdf", "application/pdf")
    a = client.post(f"/api/assets/{aid}/analyses").json()
    r = client.post(
        f"/api/leads/{lead_id}/content", json={"kind": "sample_partial", "analysis_id": a["id"], "section": "Starters"}
    )
    assert r.status_code == 409 and "审核" in r.json()["detail"]
    a = client.post(f"/api/analyses/{a['id']}/review").json()
    r = client.post(
        f"/api/leads/{lead_id}/content",
        json={"kind": "sample_partial", "analysis_id": a["id"], "section": "Starters", "item_indexes": [0, 1]},
    )
    assert r.status_code == 201, r.text
    c = r.json()
    assert [i["name"] for i in c["spec"]["items"]] == [a["items"][0]["name"], a["items"][1]["name"]]
    assert [i["price_text"] for i in c["spec"]["items"]] == [a["items"][0]["price_text"], a["items"][1]["price_text"]]
    html = client.get(c["html_url"]).text
    assert (
        a["items"][0]["name"] in html and "Starters" in html and c["status"] == "draft" and c["approval_valid"] is False
    )
    if c["png_url"]:
        assert client.get(c["png_url"]).content[:4] == b"\x89PNG"


def test_message_cites_only_confirmed_issues_and_requires_identity(client, db):
    lead_id, aid, a = _reviewed(client, db, confirm_issue=False)
    r = client.post(
        f"/api/leads/{lead_id}/content",
        json={"kind": "message_short", "analysis_id": a["id"], "sender_identity": IDENT, "opt_out_text": OPTOUT},
    )
    assert r.status_code == 409 and "已确认" in r.json()["detail"]
    # 确认问题 → 新版本 → 审核后才可生成
    a = client.patch(
        f"/api/analyses/{a['id']}", json={"corrections": [{"field_path": "issues[0].confirmed", "new_value": True}]}
    ).json()
    a = client.post(f"/api/analyses/{a['id']}/review").json()
    r = client.post(
        f"/api/leads/{lead_id}/content",
        json={"kind": "message_short", "analysis_id": a["id"], "sender_identity": IDENT, "opt_out_text": ""},
    )
    assert r.status_code == 409
    r = client.post(
        f"/api/leads/{lead_id}/content",
        json={"kind": "message_short", "analysis_id": a["id"], "sender_identity": IDENT, "opt_out_text": OPTOUT},
    )
    assert r.status_code == 201, r.text
    body = r.json()["body_text"]
    assert a["issues"][0]["fact"] in body and IDENT in body and OPTOUT in body
    assert r.json()["spec"]["cited_issue_indexes"] == [0]
    # 编辑：加入未经证据的表述 → 拒绝；去掉退出方式 → 拒绝；合法编辑 → 新版本草稿
    cid = r.json()["id"]
    bad = client.post(
        f"/api/content/{cid}/revise", json={"body_text": body + "\nWe visited your restaurant last week."}
    )
    assert bad.status_code == 409
    bad2 = client.post(f"/api/content/{cid}/revise", json={"body_text": body.replace(OPTOUT, "")})
    assert bad2.status_code == 409
    ok = client.post(f"/api/content/{cid}/revise", json={"body_text": body.replace("Hello", "Dear")})
    assert (
        ok.status_code == 201
        and ok.json()["version"] == 2
        and ok.json()["status"] == "draft"
        and ok.json()["engine"] == "human"
    )


def test_approval_binds_version_and_invalidates_on_change(client, db):
    lead_id, aid, a = _reviewed(client, db)
    c = client.post(
        f"/api/leads/{lead_id}/content",
        json={"kind": "message_short", "analysis_id": a["id"], "sender_identity": IDENT, "opt_out_text": OPTOUT},
    ).json()
    r = client.post(f"/api/content/{c['id']}/approve", json={"decision": "approved", "note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approval_valid"] is True
    # 编辑内容 → 新版本草稿；旧版本审批因存在更新版本而失效
    nv = client.post(f"/api/content/{c['id']}/revise", json={"body_text": c["body_text"].replace("Hello", "Hi")}).json()
    old = client.get(f"/api/content/{c['id']}").json()
    assert (
        old["status"] == "approved" and old["approval_valid"] is False and "更新版本" in old["approval_invalid_reason"]
    )
    assert (
        client.post(f"/api/content/{nv['id']}/approve", json={"decision": "approved"}).json()["approval_valid"] is True
    )
    # 源数据修正 → 新分析版本 → 审批失效，且不能再对旧内容审批
    client.patch(
        f"/api/analyses/{a['id']}",
        json={"corrections": [{"field_path": "items[0].name", "new_value": "Soup of the day (v2)"}]},
    )
    cur = client.get(f"/api/content/{nv['id']}").json()
    assert cur["approval_valid"] is False and "来源分析" in cur["approval_invalid_reason"]
    r = client.post(f"/api/content/{nv['id']}/approve", json={"decision": "approved"})
    assert r.status_code == 409
    # 拒绝总是允许
    assert (
        client.post(f"/api/content/{nv['id']}/approve", json={"decision": "rejected", "note": "stale"}).json()["status"]
        == "rejected"
    )
    items = client.get(f"/api/leads/{lead_id}/content").json()
    assert [i["version"] for i in items] == [1, 2]
