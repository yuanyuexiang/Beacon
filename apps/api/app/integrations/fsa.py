"""FSA（英国食品标准局 FHRS）名录接入：按地方当局与经营类型拉取，Open Government Licence v3。
只保存名录字段（名称、地址、邮编、坐标、FHRSID、评级日期作为版本）；不展示评级。"""

from dataclasses import dataclass
from time import sleep as _sleep
from typing import Any

import httpx

BASE = "https://api.ratings.food.gov.uk"
HEADERS = {"x-api-version": "2", "accept": "application/json"}
RESTAURANT_TYPE = 1


class FsaConnectionError(RuntimeError):
    pass


def _client(timeout: float, transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(
        base_url=BASE,
        headers=HEADERS,
        timeout=httpx.Timeout(timeout, connect=min(timeout, 10)),
        transport=transport,
    )


def _get(client: httpx.Client, path: str, params: dict | None = None) -> httpx.Response:
    # 仅重试上游只读 GET，每页成功后才追加结果；不会重跑名单的写入步骤。
    for attempt in range(3):
        try:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {429, 500, 502, 503, 504}:
                raise
            if attempt == 2:
                raise FsaConnectionError(
                    "FSA 服务暂不可用，已自动尝试 3 次，请稍后重试；已完成的名单步骤保留"
                ) from None
        except httpx.TransportError:
            if attempt == 2:
                raise FsaConnectionError(
                    "FSA 网络连接中断或超时，已自动尝试 3 次；请稍后重试或检查本机网络连接"
                ) from None
        _sleep(attempt + 1)
    raise AssertionError("unreachable")


@dataclass
class FsaPage:
    extract_date: str | None
    total: int
    establishments: list[dict[str, Any]]


def list_authorities(transport: httpx.BaseTransport | None = None, timeout: float = 30) -> list[dict[str, Any]]:
    with _client(timeout, transport) as c:
        r = _get(c, "/Authorities")
        r.raise_for_status()
        return [
            {
                "id": a["LocalAuthorityId"],
                "name": a["Name"],
                "region": a.get("RegionName"),
                "count": a.get("EstablishmentCount"),
            }
            for a in r.json().get("authorities", [])
        ]


def fetch_establishments(
    authority_id: int,
    business_type_id: int = RESTAURANT_TYPE,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 120,
    page_size: int = 5000,
) -> FsaPage:
    out: list[dict[str, Any]] = []
    extract = None
    total = 0
    with _client(timeout, transport) as c:
        page = 1
        while True:
            r = _get(
                c,
                "/Establishments",
                params={
                    "localAuthorityId": authority_id,
                    "businessTypeId": business_type_id,
                    "pageNumber": page,
                    "pageSize": page_size,
                },
            )
            r.raise_for_status()
            d = r.json()
            if (
                not isinstance(d, dict)
                or not isinstance(d.get("meta"), dict)
                or not isinstance(d.get("establishments"), list)
                or "totalCount" not in d["meta"]
            ):
                raise FsaConnectionError("FSA 返回的分页格式不完整，请稍后重试；已有数据保留")
            meta = d["meta"]
            extract = extract or meta.get("extractDate")
            total = int(meta.get("totalCount") or 0)
            out += d.get("establishments") or []
            if page >= int(meta.get("totalPages") or 1):
                break
            page += 1
    return FsaPage(extract_date=extract, total=total, establishments=out)


def to_lead_row(e: dict[str, Any]) -> dict[str, Any]:
    addr = ", ".join(
        x for x in (e.get("AddressLine1"), e.get("AddressLine2"), e.get("AddressLine3"), e.get("AddressLine4")) if x
    )
    g = e.get("geocode") or {}
    return {
        "source_key": f"fsa:{e['FHRSID']}",
        "source_name": "fsa",
        "name": e.get("BusinessName") or "",
        "address": addr or None,
        "postcode": e.get("PostCode") or None,
        "lat": float(g["latitude"]) if g.get("latitude") else None,
        "lng": float(g["longitude"]) if g.get("longitude") else None,
        "raw": {
            "FHRSID": e.get("FHRSID"),
            "BusinessType": e.get("BusinessType"),
            "BusinessTypeID": e.get("BusinessTypeID"),
            "RatingValue": e.get("RatingValue"),
            "RatingDate": e.get("RatingDate"),
            "LocalAuthorityName": e.get("LocalAuthorityName"),
            "NewRatingPending": e.get("NewRatingPending"),
        },
    }
