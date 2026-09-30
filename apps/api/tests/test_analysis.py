"""D5：规则引擎对两栏 PDF 不跨栏合并；HTML 价格格式不一致产生带证据的问题候选；图片/无文本 PDF 进入 needs_review；
同输入同引擎不重复创建；未获取文件不能分析；FakeProvider 不产生事实。"""

from pathlib import Path

from app.integrations.llm import FakeProvider
from app.modules.menus import analysis as rules
from tests.test_assets import setup_lead

FIX = Path(__file__).parent / "fixtures"


def test_two_column_pdf_not_merged():
    r = rules.analyze_pdf((FIX / "two_col.pdf").read_bytes())
    names = sorted(i["name"] for i in r.items)
    assert names == ["Bread and butter", "Fish pie", "Soup of the day", "Steak and chips"], r.items
    cols = {i["name"]: i["evidence"]["column"] for i in r.items}
    assert cols["Soup of the day"] == 1 and cols["Steak and chips"] == 2
    assert all("bbox" in i["evidence"] and i["evidence"]["page"] == 1 for i in r.items)
    codes = {i["issue_code"] for i in r.issues}
    assert "price_format_mixed_decimals" in codes  # 5 / 3.50 混用
    assert r.status == "succeeded" and r.measurements["pages"] == 1


def test_no_text_pdf_needs_review():
    r = rules.analyze_pdf((FIX / "no_text.pdf").read_bytes())
    assert r.status == "needs_review" and any(i["issue_code"] == "pdf_no_text" for i in r.issues)


def test_html_mixed_decimals_with_line_evidence():
    r = rules.analyze_html((FIX / "mini.html").read_bytes())
    assert [i["price_text"] for i in r.items] == ["£5.00", "£2.5"]
    iss = [i for i in r.issues if i["issue_code"] == "price_format_mixed_decimals"]
    assert len(iss) == 1 and iss[0]["confirmed"] is None and iss[0]["evidence"]["examples"][0]["line"] >= 1


def test_image_needs_review():
    r = rules.analyze_image(b"\x89PNG")
    assert r.status == "needs_review" and r.issues[0]["issue_code"] == "image_only_menu" and r.items == []


def test_fake_provider_produces_no_facts():
    p = FakeProvider()
    assert p.analyze_text("Soup 5", {}).items == [] and "未调用真实模型" in (p.analyze_text("x", {}).notes or "")


def _upload(client, lead_id, name, ctype):
    r = client.post(f"/api/leads/{lead_id}/assets/upload", files={"file": (name, (FIX / name).read_bytes(), ctype)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_analysis_endpoint_versions_and_idempotency(client, db):
    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, "two_col.pdf", "application/pdf")
    r1 = client.post(f"/api/assets/{aid}/analyses")
    assert r1.status_code == 200 and r1.json()["status"] == "succeeded" and r1.json()["version"] == 1
    assert len(r1.json()["items"]) == 4 and r1.json()["engine"] == "rules"
    r2 = client.post(f"/api/assets/{aid}/analyses")
    assert r2.json()["id"] == r1.json()["id"]  # 同输入同引擎：复用
    r3 = client.post(f"/api/assets/{aid}/analyses", params={"force": "true"})
    assert r3.json()["version"] == 2 and r3.json()["id"] != r1.json()["id"]
    assert [a["version"] for a in client.get(f"/api/assets/{aid}/analyses").json()] == [1, 2]
    # fake provider 结果一律 needs_review
    r4 = client.post(f"/api/assets/{aid}/analyses", params={"engine": "fake"})
    assert r4.status_code == 200 and r4.json()["status"] == "needs_review" and r4.json()["engine"] == "fake"
    # 未知 provider → 503 明确报错
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    import os

    os.environ["BEACON_LLM_PROVIDER"] = "nonexistent"
    cfg.get_settings.cache_clear()
    r5 = client.post(f"/api/assets/{aid}/analyses", params={"engine": "provider"})
    os.environ.pop("BEACON_LLM_PROVIDER")
    cfg.get_settings.cache_clear()
    assert r5.status_code == 503


def test_analysis_rejects_unfetched_asset(client, db):
    lead_id = setup_lead(client, db)
    r = client.post(f"/api/leads/{lead_id}/assets", json={"url": "http://127.0.0.1/x.pdf"})
    aid = r.json()["id"]
    assert client.post(f"/api/assets/{aid}/analyses").status_code == 409


def test_image_asset_analysis_needs_review(client, db):
    lead_id = setup_lead(client, db)
    aid = _upload(client, lead_id, "mini.png", "image/png")
    r = client.post(f"/api/assets/{aid}/analyses").json()
    assert r["status"] == "needs_review" and r["issues"][0]["issue_code"] == "image_only_menu"


def test_multi_price_line_is_split():
    items = rules._parse_line("Bacon 3.9 / Smoked Salmon 3.9 / Feta 3", {"page": 1, "line": 7})
    assert [(i["name"], i["price_text"]) for i in items] == [("Bacon", "3.9"), ("Smoked Salmon", "3.9"), ("Feta", "3")]
    assert items[1]["evidence"]["segment"] == 2
    # 分隔符前后有非价格段时不拆（避免把描述切碎）
    assert len(rules._parse_line("Soup of the day / served with bread 5", {"line": 1})) == 1
