"""D6：修正生成新版本且原值保留；价格修改可追溯；无证据的问题不能确认；无问题可完成审核；只能在最新版本修正。"""

from tests.test_analysis import _upload
from tests.test_assets import setup_lead


def _analysed(client, db, name="two_col.pdf", ctype="application/pdf"):
    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, name, ctype)
    a = client.post(f"/api/assets/{aid}/analyses").json()
    return lead_id, aid, a


def test_correction_creates_new_version_and_keeps_original(client, db):
    _, aid, a = _analysed(client, db)
    idx = next(i for i, it in enumerate(a["items"]) if it["name"] == "Soup of the day")
    r = client.patch(
        f"/api/analyses/{a['id']}",
        json={
            "corrections": [{"field_path": f"items[{idx}].price_text", "new_value": "£5.50", "reason": "原文为 5.50"}]
        },
    )
    assert r.status_code == 200, r.text
    nv = r.json()
    assert nv["version"] == 2 and nv["parent_version"] == 1 and nv["engine"] == "human"
    assert (
        nv["items"][idx]["price_text"] == "£5.50"
        and nv["items"][idx]["price"] == 5.5
        and nv["items"][idx]["decimals"] == 2
    )
    assert nv["items"][idx]["corrections"][0]["old"] == "5"
    orig = client.get(f"/api/analyses/{a['id']}").json()
    assert orig["items"][idx]["price_text"] == "5"  # 原值未覆盖
    # 旧版本不能再修正
    r = client.patch(
        f"/api/analyses/{a['id']}", json={"corrections": [{"field_path": f"items[{idx}].name", "new_value": "X"}]}
    )
    assert r.status_code == 409


def test_confirm_issue_requires_evidence_and_review_completes(client, db):
    _, aid, a = _analysed(client, db)
    assert any(i["issue_code"] == "price_format_mixed_decimals" for i in a["issues"])
    r = client.patch(
        f"/api/analyses/{a['id']}", json={"corrections": [{"field_path": "issues[0].confirmed", "new_value": True}]}
    )
    assert (
        r.status_code == 200
        and r.json()["issues"][0]["confirmed"] is True
        and r.json()["issues"][0]["confirmed_by"] == "tester"
    )
    nv = r.json()
    # 人为清空证据后确认 → 拒绝
    r2 = client.patch(
        f"/api/analyses/{nv['id']}", json={"corrections": [{"field_path": "issues[0].fact", "new_value": "改写"}]}
    )
    assert r2.status_code == 200
    bad = client.patch(
        f"/api/analyses/{r2.json()['id']}",
        json={"corrections": [{"field_path": "issues[0].evidence", "new_value": None}]},
    )
    assert bad.status_code == 400  # evidence 不可修改
    r3 = client.post(f"/api/analyses/{r2.json()['id']}/review")
    assert r3.status_code == 200 and r3.json()["review_state"] == "reviewed" and r3.json()["reviewed_by"] == "tester"


def test_review_without_issues_ok_and_evidence_view(client, db):
    _, aid, a = _analysed(client, db, "mini.pdf")
    assert a["items"] == [
        {
            "name": "Soup",
            "price_text": "5",
            "price": 5.0,
            "currency_symbol": None,
            "decimals": 0,
            "evidence": a["items"][0]["evidence"],
        }
    ]
    r = client.post(f"/api/analyses/{a['id']}/review")
    assert r.status_code == 200 and r.json()["review_state"] == "reviewed"
    ev = client.get(f"/api/analyses/{a['id']}/evidence").json()
    assert (
        ev["kind"] == "pdf" and ev["file_url"].startswith("/api/files/evidence/") and ev["items"][0]["evidence"]["bbox"]
    )
    assert client.get(ev["file_url"]).status_code == 200


def test_bad_paths_rejected(client, db):
    _, aid, a = _analysed(client, db)
    for path in ["items[99].name", "items[0].evidence", "measurements.pages", "foo"]:
        r = client.patch(f"/api/analyses/{a['id']}", json={"corrections": [{"field_path": path, "new_value": 1}]})
        assert r.status_code == 400, path
    assert client.patch(f"/api/analyses/{a['id']}", json={"corrections": []}).status_code == 400


def test_human_can_add_issue_and_item_with_evidence(client, db):
    """图片菜单：人工转录后新增问题与菜品；新增问题必须带证据，且记为人工确认。"""
    _, aid, a = _analysed(client, db, "mini.png", "image/png")
    assert a["status"] == "needs_review"
    bad = client.patch(
        f"/api/analyses/{a['id']}",
        json={"corrections": [{"field_path": "issues[new]", "new_value": {"issue_code": "text_overlap", "fact": "x"}}]},
    )
    assert bad.status_code == 400
    r = client.patch(
        f"/api/analyses/{a['id']}",
        json={
            "corrections": [
                {
                    "field_path": "issues[new]",
                    "new_value": {
                        "issue_code": "text_overlap",
                        "fact": "Two dish descriptions overlap in the Signature panel",
                        "evidence": {"file": "1.jpg", "region": "centre panel"},
                        "severity": "candidate",
                    },
                    "reason": "人工目视",
                },
                {
                    "field_path": "items[new]",
                    "new_value": {
                        "name": "Flying Noodles",
                        "price_text": "19",
                        "evidence": {"file": "1.jpg", "region": "Signature"},
                    },
                },
            ]
        },
    )
    assert r.status_code == 200, r.text
    nv = r.json()
    added = [i for i in nv["issues"] if i["issue_code"] == "text_overlap"][0]
    assert added["confirmed"] is True and added["confirmed_by"] == "tester" and added["added_by_human"] is True
    assert nv["items"][-1]["name"] == "Flying Noodles" and nv["items"][-1]["price"] == 19.0
    assert client.post(f"/api/analyses/{nv['id']}/review").json()["review_state"] == "reviewed"
