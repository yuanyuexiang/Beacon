"""主体候选：把官网披露、注册邮编、名称检索三路 Companies House 结果合并成一张候选表，交人工核对。
只读：不修改线索；不做主体判定。
可靠性从高到低：官网写明的公司编号 > 官网写明的公司名 > 注册邮编与门店一致 > 店名相似。"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.integrations import companies_house as ch
from app.integrations import fetcher, website_entity
from app.modules.leads.models import Lead

SOURCES = ["website_number", "website_name", "registered_postcode", "name_search"]  # 按可靠性排序
MIN_NAME_SIMILARITY = 0.5  # 名称相似的默认展示门槛；经验值，未经人工核对验证
FEW_POSTCODE_HITS = 3  # 同邮编餐饮公司不超过这个数时全部默认展示；更多时只展示门牌号或名称对得上的
MAX_WEBSITE_NUMBERS = 5
MAX_WEBSITE_NAMES = 3
SIC_DETAIL_N = 10  # 名称检索结果不含 SIC，按排序补前若干个的详情
WEBSITE_TIMEOUT = 10.0
WEBSITE_MAX_BYTES = 2 * 1024 * 1024
NOTICE = (
    "候选仅供人工核对：官网写明的公司编号最可靠，但页面里也可能是建站公司等第三方；"
    "注册邮编一致或名称相似都不等于经营主体；未查到不等于个体经营。"
)


def _name_tokens(s: str) -> list[str]:
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " and "))
    return ["ltd" if t == "limited" else t for t in s.split()]


def _is_named(company_name: str, written: str) -> bool:
    """官网写的名称是否就是这家公司：登记名的词序列须是官网写法的结尾（容忍前面多抓到的词，如 Copyright）。"""
    a, b = _name_tokens(company_name), _name_tokens(written)
    return len(a) >= 2 and b[-len(a) :] == a


def site_fetch(transport: httpx.BaseTransport | None = None) -> Callable[[str], fetcher.FetchResult]:
    """读官网页面用的抓取函数：沿用菜单抓取的内网阻断与重定向检查，超时与大小上限更小。"""
    s = get_settings()

    def fetch(url: str) -> fetcher.FetchResult:
        return fetcher.fetch(
            url,
            max_bytes=WEBSITE_MAX_BYTES,
            timeout=min(WEBSITE_TIMEOUT, s.fetch_timeout_seconds),
            user_agent=s.fetch_user_agent,
            transport=transport,
            resolve_check=s.fetch_ip_check,
        )

    return fetch


def find_candidates(
    lead: Lead,
    api_key: str,
    q: str | None = None,
    *,
    ch_transport: httpx.BaseTransport | None = None,
    web_transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """q 为空：官网披露 + 注册邮编 + 店名检索三路合并。q 非空：只按人工输入的公司名检索。
    Companies House 接口失败会抛出；官网抓取失败只记录在 website.pages。"""
    query = (q or lead.name).strip()
    found: dict[str, dict[str, Any]] = {}

    def add(cand: dict[str, Any], source: str, basis: str) -> None:
        cur = found.setdefault(cand["company_number"], {**cand, "sources": [], "basis": []})
        if cur["sic_codes"] is None and cand["sic_codes"] is not None:
            cur.update(sic_codes=cand["sic_codes"], food_service_sic=cand["food_service_sic"])
        if source not in cur["sources"]:
            cur["sources"].append(source)
            cur["basis"].append(basis)

    website: dict[str, Any] | None = None
    postcode: dict[str, Any] | None = None
    with ch.client(api_key, ch_transport) as c:
        if not q:
            if lead.website:
                website = website_entity.scan(lead.website, site_fetch(web_transport))
                refs = website["refs"]
                for ref in [r for r in refs if r["kind"] == "number"][:MAX_WEBSITE_NUMBERS]:
                    cand = ch.profile(c, ref["value"])
                    if cand:
                        add(cand, "website_number", f"官网 {ref['page_url']} 写有公司编号 {ref['value']}")
                for ref in [r for r in refs if r["kind"] == "name"][:MAX_WEBSITE_NAMES]:
                    for cand in ch.search(c, ref["value"], 5):
                        if _is_named(cand["name"], ref["value"]):
                            add(cand, "website_name", f"官网 {ref['page_url']} 写有公司名“{cand['name']}”")
            pc = ch.format_postcode(lead.postcode)
            if pc:
                hits = ch.by_postcode(c, pc)
                postcode = {"query": pc, "hits": len(hits)}
                for cand in hits:
                    add(cand, "registered_postcode", f"注册邮编 {pc} 与门店一致（餐饮类 SIC、在营）")
        for cand in ch.search(c, query, 10):
            add(cand, "name_search", f"按“{query}”名称检索")

        out = list(found.values())
        few_at_postcode = postcode is not None and postcode["hits"] <= FEW_POSTCODE_HITS
        for cand in out:
            ch.annotate(cand, query, lead.postcode, lead.address)
            cand["sources"].sort(key=SOURCES.index)
            if cand["address_match"]:
                cand["basis"].append("注册地址门牌号与门店地址一致")
        out.sort(
            key=lambda x: (
                SOURCES.index(x["sources"][0]),
                x["address_match"] is not True,
                x["postcode_match"] is not True,
                -x["name_similarity"],
            )
        )
        for cand in [x for x in out if x["sic_codes"] is None][:SIC_DETAIL_N]:
            try:
                full = ch.profile(c, cand["company_number"])
            except httpx.HTTPError:
                continue  # 详情取不到时 SIC 保持未知，不影响候选
            if full:
                cand.update(sic_codes=full["sic_codes"], food_service_sic=full["food_service_sic"])

        # 默认展示：官网披露的；同邮编且门牌号或名称对得上的（同邮编公司很少时全部展示）；
        # 仅凭店名的须在营、名称相似，且 SIC 不是已知的非餐饮（人工输入公司名检索时不按 SIC 折叠）。
        # 其余折叠：一条街的邮编下常有十几家餐饮公司，模糊检索也总会填满结果
        for cand in out:
            best = cand["sources"][0]
            similar = cand["name_similarity"] >= MIN_NAME_SIMILARITY
            if best in ("website_number", "website_name"):
                cand["primary"] = True
            elif best == "registered_postcode":
                cand["primary"] = bool(cand["address_match"]) or similar or few_at_postcode
            else:
                not_food = cand["food_service_sic"] is False and not q
                cand["primary"] = cand["company_status"] == "active" and similar and not not_food

    checked_at = datetime.now(UTC)
    for cand in out:
        cand["suggested_evidence"] = ch.evidence_text(cand, cand["basis"], checked_at.date().isoformat())
    return {
        "source": "companies_house",
        "query": query,
        "checked_at": checked_at.isoformat(),
        "candidates": out,
        "website": website,
        "postcode": postcode,
        "notice": NOTICE,
    }
