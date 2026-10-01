"""联系方式查找：官网页面 + 已存的 Overture 数据 → 候选；人工勾选后只新增为 unknown/unknown 的准入行，
不放行任何渠道、不覆盖已有审核结果。不访问网络。"""

import functools

import httpx
import pytest
from sqlalchemy import select

from app.integrations import fetcher
from app.integrations import website_contacts as wc
from app.modules.leads.models import Lead
from app.modules.sales import contacts
from tests.test_imports import CSV_A, create_batch, login, upload

SITE = "https://vesper.example"
HOME = """<html><body><h1>Vesper</h1>
<a href="/contact-us">Contact</a> <a href="/menu">Menu</a>
<a href="https://www.instagram.com/VesperLondon/?hl=en">Instagram</a>
<a href="https://www.instagram.com/p/Cabc123/">Latest post</a>
<a href="https://www.facebook.com/sharer/sharer.php?u=https://vesper.example">Share</a>
<a href="https://m.facebook.com/vesperlondon">Facebook</a>
<a href="https://www.tiktok.com/@vesper.london">TikTok</a>
<a href="https://twitter.com/intent/tweet?text=hi">Tweet</a>
<a href="https://wa.me/447700900123">WhatsApp us</a>
<a href="mailto:Bookings@Vesper.example?subject=Table">Book</a>
<a href="tel:+44 (0)20 7946 0123">Call</a>
<footer>Call 020 7946 0123 or 07700 900123. logo@2x.png. Site errors: abc@sentry.io. VAT 123456789.</footer>
</body></html>"""
CONTACT = """<html><body><p>Owner: jane.smith@vesper.example or vesperlondon@gmail.com</p>
<form><textarea name="message"></textarea></form></body></html>"""


def _web_transport(pages=None):
    pages = {"/": HOME, "/contact-us": CONTACT} if pages is None else pages

    def handler(req):
        if req.url.host == "vesper.example" and req.url.path in pages:
            return httpx.Response(200, text=pages[req.url.path], headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def _lead_id(client, db, website=SITE, overture=None):
    login(client, db)
    create_batch(client, "b1")
    upload(client, "b1", CSV_A)
    lead_id = next(x["id"] for x in client.get("/api/leads").json() if x["name"] == "Vesper")
    if website:
        assert client.patch(f"/api/leads/{lead_id}", json={"website": website}).status_code == 200
    if overture:
        lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
        lead.raw = {**(lead.raw or {}), "overture": overture}
        db.commit()
    return lead_id


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h, resolve=True: True)
    monkeypatch.setattr(
        contacts, "find_contacts", functools.partial(contacts.find_contacts, web_transport=_web_transport())
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("020 7946 0123", "+442079460123"),
        ("+44 (0)20 7946 0123", "+442079460123"),
        ("0044 7700 900123", "+447700900123"),
        ("07700-900-123", "+447700900123"),
        ("12345678", None),  # 公司编号之类的数字串
        ("0123", None),
        ("+33 1 23 45 67 89", None),
    ],
)
def test_normalize_uk_phone(raw, expected):
    assert wc.normalize_uk_phone(raw) == expected


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://www.instagram.com/VesperLondon/?hl=en", ("instagram", "https://www.instagram.com/vesperlondon")),
        ("https://instagram.com/p/Cabc/", None),  # 单条帖子不是账号
        ("https://m.facebook.com/vesperlondon", ("facebook", "https://www.facebook.com/vesperlondon")),
        (
            "https://www.facebook.com/profile.php?id=1000123",
            ("facebook", "https://www.facebook.com/profile.php?id=1000123"),
        ),
        ("https://www.facebook.com/sharer/sharer.php?u=x", None),
        ("https://www.tiktok.com/@vesper.london/video/1", ("tiktok", "https://www.tiktok.com/@vesper.london")),
        ("https://x.com/vesperldn", ("x", "https://x.com/vesperldn")),
        ("https://twitter.com/intent/tweet?text=hi", None),
        (
            "https://www.linkedin.com/company/vesper-dining/about",
            ("linkedin", "https://www.linkedin.com/company/vesper-dining"),
        ),
        ("https://www.youtube.com/watch?v=abc", None),
        ("https://wa.me/447700900123", ("whatsapp", "+447700900123")),
        ("https://api.whatsapp.com/send?phone=447700900123&text=hi", ("whatsapp", "+447700900123")),
        ("mailto:Bookings@Vesper.example?subject=Table", ("email", "bookings@vesper.example")),
        ("mailto:user@example.com", None),  # 模板占位
        ("tel:02079460123", ("phone", "+442079460123")),
        ("https://vesper.example/menu", None),
        ("javascript:void(0)", None),
    ],
)
def test_classify_link(href, expected):
    assert wc.classify_link(href) == expected


def test_personal_email_hint():
    assert wc.is_personal_email("jane.smith@vesper.example") is True
    assert wc.is_personal_email("vesperlondon@gmail.com") is True  # 免费邮箱
    assert wc.is_personal_email("bookings@vesper.example") is False
    assert wc.is_personal_email("info2@vesper.example") is False


def test_candidates_merge_website_and_overture(client, db, web):
    lead_id = _lead_id(
        client,
        db,
        overture={
            "matched": True,
            "place_id": "ov-1",
            "similarity": 1.0,
            "distance_m": 12,
            "phones": ["+442079460123", "+442070000000"],
            "socials": ["https://www.facebook.com/VesperLondon/", "https://www.facebook.com/otherplace"],
        },
    )
    r = client.get(f"/api/leads/{lead_id}/contact-candidates")
    assert r.status_code == 200, r.text
    j = r.json()
    got = {(c["kind"], c["value"]): c for c in j["candidates"]}
    assert set(got) == {
        ("email", "bookings@vesper.example"),
        ("email", "jane.smith@vesper.example"),
        ("email", "vesperlondon@gmail.com"),
        ("phone", "+442079460123"),
        ("phone", "+447700900123"),
        ("phone", "+442070000000"),
        ("whatsapp", "+447700900123"),
        ("instagram", "https://www.instagram.com/vesperlondon"),
        ("facebook", "https://www.facebook.com/vesperlondon"),
        ("facebook", "https://www.facebook.com/otherplace"),
        ("tiktok", "https://www.tiktok.com/@vesper.london"),
        ("contact_form", f"{SITE}/contact-us"),
    }  # 分享链接、单条帖子、图片文件名、sentry 地址、增值税号都不算
    # 同一联系方式官网与 Overture 都有：合并为一条，两个来源都保留
    both = got[("phone", "+442079460123")]["sources"]
    assert [s["type"] for s in both] == ["website", "overture"] and both[0]["ref"] == SITE
    assert [s["type"] for s in got[("facebook", "https://www.facebook.com/vesperlondon")]["sources"]] == [
        "website",
        "overture",
    ]
    assert [s["type"] for s in got[("phone", "+442070000000")]["sources"]] == ["overture"]
    assert "ov-1" in got[("phone", "+442070000000")]["sources"][0]["ref"]
    assert got[("email", "jane.smith@vesper.example")]["personal"] is True
    assert got[("email", "bookings@vesper.example")]["personal"] is False
    assert got[("phone", "+447700900123")]["mobile"] is True and got[("phone", "+442079460123")]["mobile"] is False
    assert got[("tiktok", "https://www.tiktok.com/@vesper.london")]["channel"] == "tiktok"
    assert [p["ok"] for p in j["website"]["pages"]] == [True, True]
    assert all(c["recorded"] is False and c["eligibility"] is None for c in j["candidates"])
    # 只读：没有写入任何准入行
    assert client.get(f"/api/leads/{lead_id}/eligibility").json() == []


def test_record_creates_unknown_rows_and_never_overwrites(client, db, web):
    lead_id = _lead_id(client, db)
    items = [
        {"channel": "email", "contact_ref": "bookings@vesper.example", "contact_source": f"官网 {SITE}"},
        {"channel": "instagram", "contact_ref": "https://www.instagram.com/vesperlondon", "contact_source": SITE},
    ]
    r = client.post(f"/api/leads/{lead_id}/contacts", json={"items": items})
    assert r.status_code == 200 and r.json() == {"created": 2, "skipped": 0}
    rows = {e["channel"]: e for e in client.get(f"/api/leads/{lead_id}/eligibility").json()}
    assert rows["email"]["contact_usable"] == "unknown" and rows["email"]["eligibility"] == "unknown"
    assert rows["email"]["contact_source"] == f"官网 {SITE}" and rows["email"]["contact_collected_at"]
    assert rows["instagram"]["eligibility"] == "unknown"
    # 记录后的联系方式仍不能建任务：unknown 不放行
    cands = {
        (c["kind"], c["value"]): c for c in client.get(f"/api/leads/{lead_id}/contact-candidates").json()["candidates"]
    }
    assert cands[("email", "bookings@vesper.example")]["recorded"] is True
    assert cands[("email", "bookings@vesper.example")]["eligibility"] == "unknown"
    assert cands[("tiktok", "https://www.tiktok.com/@vesper.london")]["recorded"] is False
    # 人工审核为 blocked 后再次“记录”：跳过，不把审核结果冲回 unknown
    client.post(
        f"/api/leads/{lead_id}/eligibility",
        json={"channel": "email", "contact_ref": "bookings@vesper.example", "eligibility": "blocked"},
    )
    r = client.post(
        f"/api/leads/{lead_id}/contacts",
        json={"items": items + [{"channel": "tiktok", "contact_ref": "https://www.tiktok.com/@vesper.london"}]},
    )
    assert r.json() == {"created": 1, "skipped": 2}
    rows = {e["channel"]: e for e in client.get(f"/api/leads/{lead_id}/eligibility").json()}
    assert rows["email"]["eligibility"] == "blocked" and len(rows) == 3


def test_no_website_uses_overture_only_and_fetch_failure_is_reported(client, db, monkeypatch):
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h, resolve=True: True)
    lead_id = _lead_id(
        client, db, website=None, overture={"matched": True, "place_id": "ov-1", "phones": ["020 7946 0123"]}
    )
    j = client.get(f"/api/leads/{lead_id}/contact-candidates").json()
    assert j["website"] is None and [(c["kind"], c["value"]) for c in j["candidates"]] == [("phone", "+442079460123")]
    client.patch(f"/api/leads/{lead_id}", json={"website": SITE})
    monkeypatch.setattr(
        contacts, "find_contacts", functools.partial(contacts.find_contacts, web_transport=_web_transport(pages={}))
    )
    j = client.get(f"/api/leads/{lead_id}/contact-candidates").json()
    assert j["website"]["pages"][0]["ok"] is False and len(j["candidates"]) == 1


def test_contacts_endpoints_validate_and_require_login(client, db):
    zero = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/leads/{zero}/contact-candidates").status_code == 401
    assert client.post(f"/api/leads/{zero}/contacts", json={"items": []}).status_code == 401
    lead_id = _lead_id(client, db, website=None)
    assert client.get(f"/api/leads/{zero}/contact-candidates").status_code == 404
    assert client.post(f"/api/leads/{lead_id}/contacts", json={"items": []}).status_code == 422
    bad = {"items": [{"channel": "fax", "contact_ref": "x"}]}
    assert client.post(f"/api/leads/{lead_id}/contacts", json=bad).status_code == 422


# ---------- 批量查找（批次运行的 contacts 步骤） ----------


def test_batch_contacts_step_records_automatically_and_skips_excluded(client, db, monkeypatch):
    from app.modules.leads import runs

    monkeypatch.setattr(fetcher, "_is_public_host", lambda h, resolve=True: True)
    monkeypatch.setattr(
        contacts, "find_contacts", functools.partial(contacts.find_contacts, web_transport=_web_transport())
    )
    lead_id = _lead_id(client, db)  # Vesper：有官网
    other = next(x["id"] for x in client.get("/api/leads").json() if x["name"] == "Fish Central")
    # Fish Central：有官网但已被筛选排除 → 不查
    client.patch(f"/api/leads/{other}", json={"website": SITE, "screening_class": "excluded_chain"})
    # 审核过的联系方式不被批量覆盖
    client.post(
        f"/api/leads/{lead_id}/eligibility",
        json={"channel": "email", "contact_ref": "bookings@vesper.example", "eligibility": "blocked"},
    )
    r = client.post("/api/batches/b1/runs", json={"steps": ["contacts"], "max_jobs": 5})
    assert r.status_code == 201, r.text
    run = r.json()
    assert [(j["lead_id"], j["step"], j["status"], j["error"]) for j in run["jobs"]] == [
        (lead_id, "contacts", "succeeded", None)
    ]
    assert run["status"] == "completed"
    rows = client.get(f"/api/leads/{lead_id}/eligibility").json()
    by = {(e["channel"], e["contact_ref"]): e for e in rows}
    assert by[("email", "bookings@vesper.example")]["eligibility"] == "blocked"  # 原审核结果保留
    assert by[("instagram", "https://www.instagram.com/vesperlondon")]["eligibility"] == "unknown"
    assert by[("phone", "+442079460123")]["contact_usable"] == "unknown" and len(rows) == 10
    assert client.get(f"/api/leads/{other}/eligibility").json() == []
    # 列表带出联系方式数量
    counts = {x["name"]: x["contact_count"] for x in client.get("/api/leads", params={"batch_key": "b1"}).json()}
    assert counts == {"Vesper": 10, "Fish Central": 0}
    # 摘要写在门店上；再跑一次不重复查同一个官网
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    db.refresh(lead)
    scan = lead.raw["contacts_scan"]
    assert (scan["found"], scan["recorded"], scan["pages_ok"], scan["website"]) == (10, 9, 2, SITE)
    again = client.post("/api/batches/b1/runs", json={"steps": ["contacts"]}).json()
    assert again["jobs"] == [] and runs.STEPS == ("fetch", "analyze", "contacts")


def test_batch_contacts_holds_back_long_lists_and_continue_runs_in_chunks(client, db, monkeypatch):
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h, resolve=True: True)
    phones = " ".join(f"020 7946 01{i:02d}" for i in range(8))  # 分店列表：8 个电话
    pages = {"/": f"<html><body><a href='mailto:info@vesper.example'>mail</a><p>{phones}</p></body></html>"}
    monkeypatch.setattr(
        contacts, "find_contacts", functools.partial(contacts.find_contacts, web_transport=_web_transport(pages))
    )
    lead_id = _lead_id(client, db, overture={"matched": True, "place_id": "ov-1", "phones": ["020 7946 0103"]})
    other = next(x["id"] for x in client.get("/api/leads").json() if x["name"] == "Fish Central")
    client.patch(f"/api/leads/{other}", json={"website": SITE})
    run = client.post("/api/batches/b1/runs", json={"steps": ["contacts"], "max_jobs": 1}).json()
    assert run["status"] == "running" and run["totals"]["pending"] == 1 and run["totals"]["succeeded"] == 1
    run = client.post(f"/api/runs/{run['id']}/continue", json={"max_jobs": 1}).json()
    assert run["status"] == "completed" and run["totals"]["succeeded"] == 2
    assert client.post("/api/runs/00000000-0000-0000-0000-000000000000/continue", json={}).status_code == 404
    # 电话超过 5 个：只自动记 Overture 也有的那一个，其余留给人工；邮箱照常记录
    got = {(e["channel"], e["contact_ref"]) for e in client.get(f"/api/leads/{lead_id}/eligibility").json()}
    assert got == {("email", "info@vesper.example"), ("phone", "+442079460103")}
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    db.refresh(lead)
    assert lead.raw["contacts_scan"]["held_for_review"] == 7
