"""Companies House 主体候选：官网披露、注册邮编、名称检索三路合并；只给候选与登记事实，不改主体状态；
密钥缺失/被拒明确报错；官网抓取失败不影响其余两路。不访问网络。"""

import base64
import functools

import httpx
import pytest

from app.core import config as cfg
from app.integrations import companies_house as ch
from app.integrations import fetcher
from app.integrations import website_entity as we
from app.modules.leads import entity
from tests.test_imports import CSV_A, create_batch, login, upload

FAKE_KEY = "test-key-not-real"
SITE = "https://vesper.example"

# 名称检索结果（不含 SIC）
SEARCH = {
    "Vesper": [
        {
            "title": "VESPER TRADING LIMITED",
            "company_number": "00000001",
            "company_status": "dissolved",
            "company_type": "ltd",
            "date_of_creation": "2010-01-01",
            "date_of_cessation": "2015-01-01",
            "address_snippet": "1 Accountant Row, Leeds, LS1 1AA",
            "address": {"postal_code": "LS1 1AA"},
        },
        {
            "title": "VESPER EXMOUTH LTD",
            "company_number": "00000002",
            "company_status": "active",
            "company_type": "ltd",
            "address_snippet": "8-10 Exmouth Market, London, EC1R 4QA",
            "address": {"postal_code": "ec1r4qa"},
        },
        {
            "title": "VESPER AI LTD",
            "company_number": "00000006",
            "company_status": "active",
            "company_type": "ltd",
            "address": {"postal_code": "E1 1AA"},
        },
        {
            "title": "GREEN GARDEN SUPPLIES LTD",
            "company_number": "00000005",
            "company_status": "active",
            "company_type": "ltd",
            "address": {"postal_code": "M1 1AA"},
        },
        {"title": "NO NUMBER", "address": {}},
    ],
    "Copyright Market Dining Limited": [
        {
            "title": "MARKET DINING LTD",
            "company_number": "00000004",
            "company_status": "active",
            "company_type": "ltd",
            "address": {"postal_code": "SW1A 1AA"},
        },
        {
            "title": "OTHER MARKET DINING HOLDINGS LTD",
            "company_number": "00000009",
            "company_status": "active",
            "company_type": "ltd",
            "address": {},
        },
    ],
}
# 详情（按编号精确查）
PROFILES = {
    "00000006": {"company_name": "VESPER AI LTD", "company_number": "00000006", "sic_codes": ["62012"]},
    "00000002": {
        "company_name": "VESPER EXMOUTH LTD",
        "company_number": "00000002",
        "company_status": "active",
        "type": "ltd",
        "registered_office_address": {"address_line_1": "8-10 Exmouth Market", "postal_code": "EC1R 4QA"},
        "sic_codes": ["56101"],
    },
    "01234567": {
        "company_name": "EXMOUTH HOSPITALITY GROUP LIMITED",
        "company_number": "01234567",
        "company_status": "active",
        "type": "ltd",
        "registered_office_address": {
            "address_line_1": "5 Agent Street",
            "locality": "Leeds",
            "postal_code": "LS1 1AA",
        },
        "sic_codes": ["56101"],
    },
    "00000004": {"company_name": "MARKET DINING LTD", "company_number": "00000004", "sic_codes": ["70100"]},
}
# 高级搜索：注册在门店邮编的餐饮类在营公司；location 也会命中地址其他部分，返回里混入一条别的邮编
BY_POSTCODE = {
    "EC1R 4QA": [
        {
            "company_name": "VESPER EXMOUTH LTD",
            "company_number": "00000002",
            "company_status": "active",
            "company_type": "ltd",
            "registered_office_address": {"address_line_1": "8-10 Exmouth Market", "postal_code": "EC1R 4QA"},
            "sic_codes": ["56101"],
        },
        {
            "company_name": "NEIGHBOUR NOODLES LTD",
            "company_number": "00000003",
            "company_status": "active",
            "company_type": "ltd",
            "registered_office_address": {"address_line_1": "12 Exmouth Market", "postal_code": "EC1R 4QA"},
            "sic_codes": ["56102"],
        },
        {
            "company_name": "ELSEWHERE LTD",
            "company_number": "00000008",
            "company_status": "active",
            "registered_office_address": {"address_line_1": "EC1R 4QA House", "postal_code": "B1 1AA"},
            "sic_codes": ["56101"],
        },
    ]
}

HOME = """<html><head><script>var companyNo = 99999999;</script></head><body>
<h1>Vesper</h1><a href="/menu">Menu</a><a href="/privacy-policy">Privacy</a>
<a href="https://other.example/terms">Terms elsewhere</a><a href="/contact#map">Contact us</a>
<footer>Copyright Market Dining Limited. VAT registration number 123456789.</footer></body></html>"""
PRIVACY = """<html><body><p>This site is operated by Exmouth Hospitality Group Limited,
registered in England and Wales, Company No. 1234567. ICO registration number ZA123456.</p></body></html>"""


def _ch_transport(status=200, seen=None):
    def handler(req):
        if seen is not None:
            seen.append(req)
        if status != 200:
            return httpx.Response(status, json={"error": "Invalid Authorization", "type": "ch:service"})
        path = req.url.path
        if path == "/search/companies":
            return httpx.Response(200, json={"items": SEARCH.get(req.url.params["q"], [])})
        if path == "/advanced-search/companies":
            items = BY_POSTCODE.get(req.url.params["location"])
            return httpx.Response(200, json={"items": items}) if items else httpx.Response(404)
        if path.startswith("/company/") and path.split("/")[-1] in PROFILES:
            return httpx.Response(200, json=PROFILES[path.split("/")[-1]])
        return httpx.Response(404, json={"errors": [{"type": "ch:service"}]})

    return httpx.MockTransport(handler)


def _web_transport(pages=None):
    pages = {"/": HOME, "/privacy-policy": PRIVACY} if pages is None else pages

    def handler(req):
        if req.url.host == "vesper.example" and req.url.path in pages:
            return httpx.Response(200, text=pages[req.url.path], headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


@pytest.fixture
def ch_key(monkeypatch):
    monkeypatch.setenv("BEACON_COMPANIES_HOUSE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h, resolve=True: True)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _lead_id(client, db, website=None):
    login(client, db)
    create_batch(client, "b1")
    upload(client, "b1", CSV_A)
    lead_id = next(x["id"] for x in client.get("/api/leads").json() if x["name"] == "Vesper")
    if website:
        assert client.patch(f"/api/leads/{lead_id}", json={"website": website}).status_code == 200
    return lead_id


def _patch_transports(monkeypatch, ch_t=None, web_t=None):
    monkeypatch.setattr(
        entity,
        "find_candidates",
        functools.partial(
            entity.find_candidates, ch_transport=ch_t or _ch_transport(), web_transport=web_t or _web_transport()
        ),
    )


# ---------- Companies House 接口 ----------


def test_client_sends_key_as_basic_auth_and_maps_search():
    seen: list[httpx.Request] = []
    with ch.client(FAKE_KEY, _ch_transport(seen=seen)) as c:
        out = ch.search(c, "Vesper")
    assert seen[0].headers["authorization"] == "Basic " + base64.b64encode(f"{FAKE_KEY}:".encode()).decode()
    assert [x["company_number"] for x in out] == ["00000001", "00000002", "00000006", "00000005"]  # 无编号的丢弃
    assert out[0]["sic_codes"] is None and out[0]["food_service_sic"] is None  # 名称检索不含 SIC，保持未知
    assert out[1]["url"].endswith("/company/00000002")


def test_profile_and_postcode_search():
    with ch.client(FAKE_KEY, _ch_transport()) as c:
        p = ch.profile(c, "00000002")
        assert p and p["name"] == "VESPER EXMOUTH LTD" and p["company_type"] == "ltd" and p["food_service_sic"] is True
        assert p["registered_address"] == "8-10 Exmouth Market, EC1R 4QA"
        assert ch.profile(c, "99999999") is None  # 编号不存在
        # 邮编规范为带空格写法；返回里邮编不一致的条目剔除
        assert [x["company_number"] for x in ch.by_postcode(c, "ec1r4qa")] == ["00000002", "00000003"]
        assert ch.by_postcode(c, "N1 1AA") == [] and ch.by_postcode(c, None) == [] and ch.by_postcode(c, "N1") == []


def test_rejected_key_raises_clear_error():
    for code in (401, 429):
        with ch.client(FAKE_KEY, _ch_transport(status=code)) as c, pytest.raises(ch.CompaniesHouseError) as e:
            ch.search(c, "Vesper")
        assert str(code) in str(e.value)


# ---------- 官网披露提取 ----------


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("Company No. 1234567", ["01234567"]),  # 7 位补前导 0
        ("Company Registration Number: 12345678.", ["12345678"]),
        ("Registered in England & Wales No. 09876543", ["09876543"]),
        ("Registered in Scotland, company number SC 123456", ["SC123456"]),
        ("Registered number OC301234", ["OC301234"]),
        ("VAT registration number 123456789", []),  # 9 位是增值税号
        ("VAT Reg No. 12345678", []),
        ("Registered charity number 1234567", []),
        ("Registered in England and Wales, charity no. 1234567", []),
        ("ICO registration number ZA123456", []),
        ("Call 02071234567 or order no. 12345678", []),
    ],
)
def test_extract_company_numbers(text, numbers):
    assert [r.value for r in we.extract_refs(text, SITE) if r.kind == "number"] == numbers


def test_extract_names_and_links():
    refs = we.extract_refs("© 2026 Exmouth Hospitality Group Limited. Site by PIXEL & CO LTD today", SITE)
    assert [r.value for r in refs if r.kind == "name"] == ["Exmouth Hospitality Group Limited", "PIXEL & CO LTD"]
    # 不跨句、不把促销文案当公司名
    noisy = "Our Top 20 Teas New In & Limited editions. W10 6TR. 1.2. CHIK’N LIMITED is the operator"
    assert [r.value for r in we.extract_refs(noisy, SITE) if r.kind == "name"] == ["CHIK’N LIMITED"]
    text, links = we.parse_page(HOME)
    assert "Copyright Market Dining Limited" in text and "99999999" not in text  # 页脚保留，脚本跳过
    # 只跟同站的法律/联系页，隐私页优先；去掉锚点
    assert we.legal_links(links, SITE + "/") == [SITE + "/privacy-policy", SITE + "/contact"]


# ---------- 三路合并 ----------


def test_endpoint_merges_three_sources_without_changing_entity(client, db, ch_key, monkeypatch):
    lead_id = _lead_id(client, db, website=SITE)
    _patch_transports(monkeypatch)
    r = client.get(f"/api/leads/{lead_id}/entity-candidates")
    assert r.status_code == 200, r.text
    j = r.json()
    by_no = {c["company_number"]: c for c in j["candidates"]}
    # 排序：官网编号 > 官网公司名 > 注册邮编（名称相似者在前）> 仅名称检索
    assert [c["company_number"] for c in j["candidates"]] == [
        "01234567",
        "00000004",
        "00000002",
        "00000003",
        "00000001",
        "00000006",
        "00000005",
    ]
    assert by_no["01234567"]["sources"] == ["website_number"]
    assert by_no["00000004"]["sources"] == ["website_name"] and "00000009" not in by_no  # 名称须完全对上
    assert by_no["00000004"]["sic_codes"] == ["70100"] and by_no["00000004"]["food_service_sic"] is False
    assert by_no["00000002"]["sources"] == ["registered_postcode", "name_search"]  # 同一公司两路命中只列一次
    assert by_no["00000002"]["postcode_match"] is True and "00000008" not in by_no
    # 门店地址 8-10 Exmouth Market：同邮编且门牌号对得上才算注册在店址
    assert by_no["00000002"]["address_match"] is True and by_no["00000003"]["address_match"] is False
    assert by_no["01234567"]["address_match"] is None  # 邮编不同，不下结论
    assert "注册地址门牌号与门店地址一致" in by_no["00000002"]["suggested_evidence"]
    # 默认展示：有官网/邮编依据的全部，以及在营且名称相似的；已解散或名称不像的折叠
    assert [c["company_number"] for c in j["candidates"] if c["primary"]] == [
        "01234567",
        "00000004",
        "00000002",
        "00000003",
    ]
    ev = by_no["01234567"]["suggested_evidence"]
    assert "EXMOUTH HOSPITALITY GROUP LIMITED" in ev and f"官网 {SITE}/privacy-policy 写有公司编号 01234567" in ev
    assert "注册邮编 EC1R 4QA 与门店一致" in by_no["00000002"]["suggested_evidence"]
    assert j["postcode"] == {"query": "EC1R 4QA", "hits": 2}
    assert [p["ok"] for p in j["website"]["pages"]] == [True, True, False]  # 首页、隐私页、联系页 404
    assert {(x["kind"], x["value"]) for x in j["website"]["refs"]} >= {("number", "01234567")}
    assert "未查到不等于个体经营" in j["notice"]
    # 同名但 SIC 非餐饮的在营公司（VESPER AI LTD）默认折叠；人工输入名称检索时不按 SIC 折叠
    assert by_no["00000006"]["primary"] is False and by_no["00000006"]["sic_codes"] == ["62012"]
    manual = client.get(f"/api/leads/{lead_id}/entity-candidates", params={"q": "Vesper"}).json()["candidates"]
    assert {c["company_number"]: c["primary"] for c in manual}["00000006"] is True
    # 检索不做主体判定：状态仍为 unknown，直到人工保存
    assert client.get(f"/api/leads/{lead_id}").json()["entity_status"] == "unknown"


def test_manual_query_only_runs_name_search(client, db, ch_key, monkeypatch):
    lead_id = _lead_id(client, db, website=SITE)
    seen: list[httpx.Request] = []
    _patch_transports(monkeypatch, ch_t=_ch_transport(seen=seen))
    j = client.get(f"/api/leads/{lead_id}/entity-candidates", params={"q": " Copyright Market Dining Limited "}).json()
    assert j["query"] == "Copyright Market Dining Limited" and j["website"] is None and j["postcode"] is None
    assert [c["sources"] for c in j["candidates"]] == [["name_search"], ["name_search"]]
    assert not any(r.url.path == "/advanced-search/companies" for r in seen)


def test_no_website_or_unreachable_website_still_returns_candidates(client, db, ch_key, monkeypatch):
    lead_id = _lead_id(client, db)  # 无官网：只有注册邮编与名称两路
    _patch_transports(monkeypatch)
    j = client.get(f"/api/leads/{lead_id}/entity-candidates").json()
    assert j["website"] is None and [c["company_number"] for c in j["candidates"]][:2] == ["00000002", "00000003"]
    # 官网抓不到：记录原因，其余两路照常
    client.patch(f"/api/leads/{lead_id}", json={"website": SITE})
    _patch_transports(monkeypatch, web_t=_web_transport(pages={}))
    j = client.get(f"/api/leads/{lead_id}/entity-candidates").json()
    assert j["website"]["pages"][0]["ok"] is False and "404" in j["website"]["pages"][0]["error"]
    assert j["website"]["refs"] == [] and len(j["candidates"]) == 5


def test_endpoint_errors(client, db, monkeypatch):
    lead_id = _lead_id(client, db)
    r = client.get(f"/api/leads/{lead_id}/entity-candidates")
    assert r.status_code == 503 and "BEACON_COMPANIES_HOUSE_API_KEY" in r.json()["detail"]
    monkeypatch.setenv("BEACON_COMPANIES_HOUSE_API_KEY", FAKE_KEY)
    cfg.get_settings.cache_clear()
    _patch_transports(monkeypatch, ch_t=_ch_transport(status=401))
    r = client.get(f"/api/leads/{lead_id}/entity-candidates")
    assert r.status_code == 502 and "401" in r.json()["detail"] and FAKE_KEY not in r.text
    assert client.get("/api/leads/00000000-0000-0000-0000-000000000000/entity-candidates").status_code == 404
    cfg.get_settings.cache_clear()


def test_endpoint_requires_login(client):
    assert client.get("/api/leads/00000000-0000-0000-0000-000000000000/entity-candidates").status_code == 401


def test_many_companies_at_postcode_only_matching_ones_shown_by_default(client, db, ch_key, monkeypatch):
    lead_id = _lead_id(client, db)
    extra = [
        {
            "company_name": f"STREET FOOD {i} LTD",
            "company_number": f"0000010{i}",
            "company_status": "active",
            "registered_office_address": {"address_line_1": f"{20 + i} Exmouth Market", "postal_code": "EC1R 4QA"},
            "sic_codes": ["56103"],
        }
        for i in range(3)
    ]
    monkeypatch.setitem(BY_POSTCODE, "EC1R 4QA", BY_POSTCODE["EC1R 4QA"] + extra)
    _patch_transports(monkeypatch)
    j = client.get(f"/api/leads/{lead_id}/entity-candidates").json()
    assert j["postcode"]["hits"] == 5
    # 同邮编 5 家：只有门牌号/名称对得上的默认展示，其余折叠但仍在列表里
    assert [c["company_number"] for c in j["candidates"] if c["primary"]] == ["00000002"]
    assert len(j["candidates"]) == 8
