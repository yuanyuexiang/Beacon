"""Overture 补全：名称相似度 + 距离匹配；只填空缺官网；来源与置信度写入线索；不下载网络数据。"""

from app.integrations import overture
from app.integrations.overture import Place
from tests.test_imports import create_batch, login, upload

PLACES = [
    Place(
        "p1",
        "Fish Central",
        -0.0951,
        51.5272,
        0.97,
        ["http://fishcentral.co.uk/"],
        ["+442072534970"],
        [],
        "restaurant",
        "EC1V 8AP",
    ),
    Place("p2", "The Fish Shop", -0.0951, 51.5272, 0.5, ["http://other.example/"], [], [], "restaurant", None),
    Place(
        "p3",
        "Vesper Finsbury",
        -0.1090,
        51.5260,
        0.9,
        [],
        ["+44123"],
        ["https://instagram.com/vesper"],
        "restaurant",
        None,
    ),
    Place("p4", "Fish Central", -0.20, 51.60, 0.9, ["http://far.example/"], [], [], "restaurant", None),
]


def test_similarity_and_match_prefers_similar_then_near():
    assert overture.similarity("Fish Central", "Fish Central Ltd") == 1.0
    assert overture.similarity("Zia Lucia & Berto", "Zia Lucia") > 0.5
    m = overture.match("Fish Central", 51.5272, -0.0951, PLACES)
    assert m and m["place_id"] == "p1" and m["websites"] == ["http://fishcentral.co.uk/"] and m["distance_m"] == 0
    assert overture.match("Fish Central", 51.60, -0.21, PLACES, max_m=100) is None  # 太远
    assert overture.match("Totally Different", 51.5272, -0.0951, PLACES) is None  # 不相似


def test_enrich_sets_only_missing_websites_with_provenance(client, db):
    login(client, db)
    create_batch(client, "b1")
    csv = (
        "fhrsid,name,postcode,lat,lng,website\n416314,Fish Central,EC1V 8AP,51.5272,-0.0951,\n"
        "1408999,Vesper,EC1R 4QA,51.5260,-0.1090,https://vesper.restaurant/\n3,No Coords,N1,,,\n"
    )
    upload(client, "b1", csv)
    from sqlalchemy import select

    from app.modules.leads import service
    from app.modules.leads.models import Batch

    b = db.scalar(select(Batch).where(Batch.batch_key == "b1"))
    r = service.enrich_overture(db, b, places=PLACES)
    assert r["leads"] == 3 and r["matched"] == 2 and r["website_set"] == 1
    leads = {x["source_key"]: x for x in client.get("/api/leads?batch_key=b1").json()}
    assert leads["fsa:416314"]["website"] == "http://fishcentral.co.uk/"
    assert leads["fsa:1408999"]["website"] == "https://vesper.restaurant/"  # 已有官网不覆盖
    full = db.get(type(b), b.id)  # 触发会话
    from app.modules.leads.models import Lead

    fc = db.scalar(select(Lead).where(Lead.source_key == "fsa:416314"))
    assert fc.website_source.startswith("overture:p1") and fc.raw["overture"]["licence"] == "CDLA-Permissive-2.0"
    assert fc.raw["overture"]["phones"] == ["+442072534970"]
    nc = db.scalar(select(Lead).where(Lead.source_key == "fsa:3"))
    assert nc.raw is None or "overture" not in (nc.raw or {})  # 无坐标不匹配
    assert full is not None


def test_enrich_endpoint_uses_bbox_and_cache(client, db, monkeypatch):
    login(client, db)
    create_batch(client, "b1")
    upload(client, "b1", "fhrsid,name,lat,lng\n416314,Fish Central,51.5272,-0.0951\n")
    monkeypatch.setattr(overture, "ensure_places", lambda bbox, data_dir, release=None: data_dir)
    monkeypatch.setattr(overture, "load_places", lambda path: PLACES)
    r = client.post("/api/batches/b1/enrich/overture", json={})
    assert r.status_code == 200 and r.json()["website_set"] == 1 and len(r.json()["bbox"]) == 4
    assert client.post("/api/batches/nope/enrich/overture", json={}).status_code == 404


def test_auto_screen_rules_and_brand(client, db):
    login(client, db)
    create_batch(client, "b1")
    upload(
        client,
        "b1",
        "fhrsid,name\n1,Starbucks Angel\n2,Rosa's Thai Cafe\n3,Mola Cafe\n4,St Mary's School Kitchen\n"
        "5,The Compton Arms\n6,Fish Central\n7,Brandy Place\n",
    )
    from sqlalchemy import select

    from app.modules.leads.models import Lead

    lead7 = db.scalar(select(Lead).where(Lead.source_key == "fsa:7"))
    lead7.raw = {"overture": {"brand": "Some Chain"}}
    db.commit()
    r = client.post("/api/batches/b1/screen")
    assert r.status_code == 200, r.text
    c = r.json()["counts"]
    assert c == {"excluded_chain": 3, "excluded_cafe": 1, "excluded_institution": 1, "excluded_pub": 1, "unchecked": 1}
    leads = {x["name"]: x for x in client.get("/api/leads?batch_key=b1").json()}
    assert leads["Fish Central"]["screening_class"] == "unchecked"
    assert (
        leads["Brandy Place"]["screening_class"] == "excluded_chain"
        and "brand=Some Chain" in leads["Brandy Place"]["screening_reason"]
    )
    # 人工已改的不再覆盖
    client.patch(
        f"/api/leads/{leads['Mola Cafe']['id']}", json={"screening_class": "candidate", "screening_reason": "实为餐厅"}
    )
    client.post("/api/batches/b1/screen")
    assert client.get(f"/api/leads/{leads['Mola Cafe']['id']}").json()["screening_class"] == "candidate"
