"""D3：同批次同来源键重导不新增；同一门店跨批次关联；坏行明确拒收；同名不同地址不合并。"""

import io

from tests.test_auth import make_operator

CSV_A = """fhrsid,name,address,postcode,lat,lng,sample_order
416314,Fish Central,149-155 Central Street,EC1V 8AP,51.527,-0.095,1
1408999,Vesper,8-10 Exmouth Market,EC1R 4QA,51.526,-0.109,2
,No Key Restaurant,1 Nowhere,N1 1AA,,,3
"""
CSV_B = """source_key,name,address,postcode
fsa:416314,Fish Central,149-155 Central Street,EC1V 8AP
fsa:999001,Fish Central,77 Other Road,N7 7XX
bad-key,Broken,1 Road,N1
"""


def login(client, db):
    make_operator(db)
    client.post("/api/auth/login", json={"username": "tester", "password": "pw-tester-123"})


def create_batch(client, key="b1"):
    r = client.post(
        "/api/batches",
        json={
            "batch_key": key,
            "country": "GB",
            "region": "Islington",
            "source_name": "fsa",
            "source_licence": "OGL-3.0",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, key, csv_text, name="x.csv"):
    return client.post(
        "/api/imports", data={"batch_key": key}, files={"file": (name, io.BytesIO(csv_text.encode()), "text/csv")}
    )


def test_import_requires_login(client):
    assert upload(client, "b1", CSV_A).status_code == 401


def test_import_creates_links_and_reports_errors(client, db):
    login(client, db)
    create_batch(client, "b1")
    r = upload(client, "b1", CSV_A)
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["row_count"], j["created_count"], j["linked_count"], j["skipped_count"], j["error_count"]) == (
        3,
        2,
        0,
        0,
        1,
    )
    assert j["errors"][0]["row"] == 4 and "source_key" in j["errors"][0]["reason"]
    leads = client.get("/api/leads", params={"batch_key": "b1"}).json()
    assert [x["source_key"] for x in leads] == ["fsa:416314", "fsa:1408999"]

    # 同批次重导：全部跳过，不新增
    j2 = upload(client, "b1", CSV_A).json()
    assert (j2["created_count"], j2["linked_count"], j2["skipped_count"], j2["error_count"]) == (0, 0, 2, 1)
    assert len(client.get("/api/leads", params={"batch_key": "b1"}).json()) == 2

    # 另一批次：已存在门店关联而非新建；同名不同地址（不同来源键）新建；坏键拒收
    create_batch(client, "b2")
    j3 = upload(client, "b2", CSV_B).json()
    assert (j3["created_count"], j3["linked_count"], j3["skipped_count"], j3["error_count"]) == (1, 1, 0, 1)
    all_leads = client.get("/api/leads").json()
    assert len(all_leads) == 3
    assert len([x for x in all_leads if x["name"] == "Fish Central"]) == 2  # 未按店名合并
    b2 = client.get("/api/leads", params={"batch_key": "b2"}).json()
    assert {x["source_key"] for x in b2} == {"fsa:416314", "fsa:999001"}


def test_import_unknown_batch_and_empty_file(client, db):
    login(client, db)
    assert upload(client, "nope", CSV_A).status_code == 404
    create_batch(client, "b1")
    assert upload(client, "b1", "   ").status_code == 400


def test_duplicate_batch_key_conflict(client, db):
    login(client, db)
    create_batch(client, "b1")
    r = client.post("/api/batches", json={"batch_key": "b1", "country": "GB", "source_name": "fsa"})
    assert r.status_code == 409


def test_patch_lead_records_entity_reviewer(client, db):
    login(client, db)
    create_batch(client, "b1")
    upload(client, "b1", CSV_A)
    lead = client.get("/api/leads", params={"batch_key": "b1"}).json()[0]
    r = client.patch(f"/api/leads/{lead['id']}", json={"entity_status": "company", "entity_evidence": "CH 01234567"})
    assert r.status_code == 200 and r.json()["entity_status"] == "company"
    assert r.json()["entity_evidence"] == "CH 01234567"
    assert client.get("/api/leads?screening_class=candidate").json() == []
