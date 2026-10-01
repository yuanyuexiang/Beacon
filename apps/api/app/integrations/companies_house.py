"""Companies House（英国公司注册处）公开登记检索，供人工核对经营主体。三种查法：
按公司编号精确查、按注册邮编查餐饮类在营公司、按名称模糊检索。
只返回候选与登记字段，不做主体判定：名称相似不等于经营主体，未查到不等于个体经营；
注册地址常为代理/会计师地址，邮编不一致不能排除。检索结果不入库，人工采用后才写入线索的主体证据。"""

import re
from typing import Any

import httpx

from app.integrations.overture import similarity

BASE = "https://api.company-information.service.gov.uk"
PUBLIC_URL = "https://find-and-update.company-information.service.gov.uk/company"
FOOD_SERVICE_SIC_PREFIX = "56"  # SIC 2007 第 56 类：餐饮服务
# 第 56 类下的全部代码（56101 持牌餐厅、56102 无牌餐厅与咖啡店、56103 外卖、56210/56290 餐饮承包、56301/56302 酒吧）
FOOD_SERVICE_SIC = ["56101", "56102", "56103", "56210", "56290", "56301", "56302"]


class CompaniesHouseError(RuntimeError):
    pass


def client(api_key: str, transport: httpx.BaseTransport | None = None, timeout: float = 30) -> httpx.Client:
    # 密钥作为 Basic 认证的用户名，密码为空
    return httpx.Client(
        base_url=BASE, auth=(api_key, ""), headers={"accept": "application/json"}, timeout=timeout, transport=transport
    )


def _check(r: httpx.Response) -> None:
    if r.status_code == 401:
        raise CompaniesHouseError(
            "Companies House 拒绝了密钥（401）：确认是 live 应用下的 REST API key，且未限制来源 IP"
        )
    if r.status_code == 429:
        raise CompaniesHouseError("Companies House 限流（429），稍后重试")
    r.raise_for_status()


def _postcode(s: str | None) -> str:
    return re.sub(r"\s+", "", s or "").upper()


def format_postcode(s: str | None) -> str | None:
    """规范为带空格的写法（N7 7NS）；高级搜索的 location 只认这种写法。"""
    c = _postcode(s)
    return f"{c[:-3]} {c[-3:]}" if 5 <= len(c) <= 7 else None


def _address(a: dict[str, Any] | None) -> str | None:
    a = a or {}
    parts = [a.get(k) for k in ("premises", "address_line_1", "address_line_2", "locality", "postal_code")]
    return ", ".join(p for p in parts if p) or None


def _candidate(item: dict[str, Any]) -> dict[str, Any]:
    """统一三种接口的返回：名称检索用 title/address，详情与高级搜索用 company_name/registered_office_address。"""
    number = item.get("company_number") or ""
    addr = item.get("registered_office_address") or item.get("address") or {}
    sic = item.get("sic_codes")
    return {
        "company_number": number,
        "name": item.get("company_name") or item.get("title") or "",
        "company_status": item.get("company_status"),
        "company_type": item.get("company_type") or item.get("type"),
        "date_of_creation": item.get("date_of_creation"),
        "date_of_cessation": item.get("date_of_cessation"),
        "registered_address": item.get("address_snippet") or _address(addr),
        "registered_postcode": addr.get("postal_code"),
        "sic_codes": sic,  # None = 未取到，不当作“非餐饮”
        "food_service_sic": None if sic is None else any(s.startswith(FOOD_SERVICE_SIC_PREFIX) for s in sic),
        "url": f"{PUBLIC_URL}/{number}",
    }


def search(c: httpx.Client, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """名称模糊检索：按相关度返回至多 limit 条，不保证与门店有关。结果不含 SIC。"""
    r = c.get("/search/companies", params={"q": query, "items_per_page": limit})
    _check(r)
    return [_candidate(i) for i in r.json().get("items") or [] if i.get("company_number")]


def profile(c: httpx.Client, number: str) -> dict[str, Any] | None:
    """按公司编号精确查；编号不存在返回 None。"""
    r = c.get(f"/company/{number}")
    if r.status_code == 404:
        return None
    _check(r)
    return _candidate(r.json())


def by_postcode(c: httpx.Client, postcode: str | None, limit: int = 20) -> list[dict[str, Any]]:
    """注册邮编与给定邮编相同、SIC 为餐饮类的在营公司。同一邮编可有多家，仍需人工核对。"""
    pc = format_postcode(postcode)
    if pc is None:
        return []
    r = c.get(
        "/advanced-search/companies",
        params={"location": pc, "sic_codes": ",".join(FOOD_SERVICE_SIC), "company_status": "active", "size": limit},
    )
    if r.status_code == 404:  # 无结果
        return []
    _check(r)
    out = [_candidate(i) for i in r.json().get("items") or [] if i.get("company_number")]
    return [x for x in out if _postcode(x["registered_postcode"]) == _postcode(pc)]  # location 也会匹配地址其他部分


def _house_numbers(address: str | None, postcode: str | None) -> set[str]:
    """地址里的门牌号（138a 记作 138，8-10 记作 8 和 10）；邮编里的数字不算。"""
    s = (address or "").upper()
    for pc in {format_postcode(postcode), _postcode(postcode)} - {None, ""}:
        s = s.replace(str(pc), " ")
    return set(re.findall(r"(?<![A-Z0-9])(\d{1,4})[A-Z]?(?![A-Z0-9])", s))


def annotate(cand: dict[str, Any], name: str, postcode: str | None, address: str | None = None) -> None:
    cand["name_similarity"] = round(similarity(name, cand["name"]), 3)
    reg = _postcode(cand["registered_postcode"])
    cand["postcode_match"] = (reg == _postcode(postcode)) if reg and postcode else None
    # 注册地址就是门店地址：邮编一致且门牌号对得上。只在两边都有门牌号时下结论
    mine = _house_numbers(address, postcode)
    theirs = _house_numbers(cand["registered_address"], cand["registered_postcode"])
    cand["address_match"] = bool(mine & theirs) if cand["postcode_match"] and mine and theirs else None


def evidence_text(cand: dict[str, Any], basis: list[str], checked_on: str) -> str:
    """人工采用候选时写入主体证据的文本：登记事实 + 依据与日期，不含判断。"""
    parts = [
        f"Companies House {cand['company_number']} {cand['name']}",
        f"状态 {cand.get('company_status') or '未知'}",
        f"类型 {cand.get('company_type') or '未知'}",
    ]
    if cand.get("registered_address"):
        parts.append(f"注册地址 {cand['registered_address']}")
    if cand.get("sic_codes"):
        parts.append(f"SIC {'/'.join(cand['sic_codes'])}")
    parts.append("依据：" + "、".join(basis))
    return "；".join(parts) + f"；查询于 {checked_on}"
