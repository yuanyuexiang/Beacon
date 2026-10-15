"""Places API (New)：实时查询，不落盘；密钥仅发送给固定 Google API 主机。"""

import re
from collections.abc import Callable
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

BASE = "https://places.googleapis.com/v1"
MAX_JSON_BYTES = 512 * 1024
MAX_PHOTO_BYTES = 10 * 1024 * 1024
PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}\Z")
PHOTO_NAME = re.compile(r"^places/([A-Za-z0-9_-]{1,256})/photos/[A-Za-z0-9_-]{1,2048}\Z")
SEARCH_FIELDS = "places.id,places.displayName,places.formattedAddress,places.googleMapsUri,places.attributions"
DETAIL_FIELDS = (
    "id,displayName,formattedAddress,googleMapsUri,businessStatus,priceLevel,priceRange,photos,attributions,"
    "websiteUri,primaryType,primaryTypeDisplayName,internationalPhoneNumber"
)


class PlacesError(ValueError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def safe_google_url(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("//"):
        value = "https:" + value
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower()
        valid = u.scheme == "https" and not u.username and not u.password and u.port in (None, 443)
    except ValueError:
        return None
    if not valid:
        return None
    if host == "google.com" or host.endswith(".google.com") or host.endswith(".googleusercontent.com"):
        return value
    return None


class Attribution(BaseModel):
    displayName: str = ""
    uri: str | None = None
    photoUri: str | None = None

    @field_validator("uri", "photoUri")
    @classmethod
    def safe_links(cls, v: str | None) -> str | None:
        return safe_google_url(v)


class ProviderAttribution(BaseModel):
    provider: str = ""
    providerUri: str | None = None

    @field_validator("providerUri")
    @classmethod
    def safe_link(cls, v: str | None) -> str | None:
        if not v:
            return None
        u = urlsplit(v)
        return v if u.scheme == "https" and u.hostname and not u.username and not u.password else None


class Money(BaseModel):
    currencyCode: str = Field(pattern=r"^[A-Z]{3}$")
    units: str = Field(default="0", pattern=r"^-?\d{1,12}$")
    nanos: int = Field(default=0, ge=-999999999, le=999999999)


class PriceRange(BaseModel):
    startPrice: Money | None = None
    endPrice: Money | None = None


class LocalizedText(BaseModel):
    text: str = ""


class Photo(BaseModel):
    name: str = Field(pattern=PHOTO_NAME)
    widthPx: int = 0
    heightPx: int = 0
    authorAttributions: list[Attribution] = Field(default_factory=list)
    googleMapsUri: str | None = None

    @field_validator("googleMapsUri")
    @classmethod
    def safe_link(cls, v: str | None) -> str | None:
        return safe_google_url(v)


class Place(BaseModel):
    id: str = Field(pattern=PLACE_ID)
    displayName: LocalizedText = Field(default_factory=LocalizedText)
    formattedAddress: str | None = None
    googleMapsUri: str | None = None
    websiteUri: str | None = None
    primaryType: str | None = None
    primaryTypeDisplayName: LocalizedText | None = None
    internationalPhoneNumber: str | None = None
    businessStatus: str | None = None
    priceLevel: str | None = None
    priceRange: PriceRange | None = None
    photos: list[Photo] = Field(default_factory=list, max_length=10)
    attributions: list[ProviderAttribution] = Field(default_factory=list)

    @field_validator("websiteUri")
    @classmethod
    def safe_website(cls, v: str | None) -> str | None:
        if not v:
            return None
        from app.integrations.fetcher import FetchBlocked, check_url

        try:
            check_url(v, resolve=False)
            u = urlsplit(v)
            if u.username or u.password or len(v) > 512:
                return None
            return v
        except (FetchBlocked, ValueError):
            return None

    @field_validator("googleMapsUri")
    @classmethod
    def safe_link(cls, v: str | None) -> str | None:
        return safe_google_url(v)


class SearchResponse(BaseModel):
    places: list[Place] = Field(default_factory=list, max_length=3)


SKU = Literal["Text Search Pro", "Place Details Enterprise", "Place Details Photos"]


class PlacesClient:
    def __init__(
        self,
        key: str | None,
        proxy: str | None = None,
        *,
        reserve: Callable[[SKU], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        if not key:
            raise PlacesError("未配置 Google Places API Key", 503)
        self.key = key
        self.proxy = proxy
        self.reserve = reserve or (lambda _: None)
        self.transport = transport

    def _request(
        self,
        method: str,
        path: str,
        sku: SKU,
        *,
        fields: str | None = None,
        payload: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        for attempt in range(2):
            self.reserve(sku)  # 每次上游尝试前计数，包括网络失败和重试
            try:
                with (
                    httpx.Client(
                        proxy=self.proxy if self.transport is None else None,
                        transport=self.transport,
                        trust_env=False,
                        timeout=httpx.Timeout(12, connect=5),
                        follow_redirects=False,
                    ) as client,
                    client.stream(
                        method,
                        BASE + path,
                        headers={"X-Goog-Api-Key": self.key, **({"X-Goog-FieldMask": fields} if fields else {})},
                        json=payload,
                        params=params,
                    ) as response,
                ):
                    if response.status_code >= 500 and attempt == 0:
                        continue
                    if response.status_code == 429:
                        raise PlacesError("Google Places 配额或速率受限，请稍后重试", 429)
                    if response.status_code in (401, 403):
                        raise PlacesError("Google Places 拒绝访问，请检查密钥、结算、API 启用和出口 IP 限制", 503)
                    if response.status_code in (400, 404):
                        raise PlacesError("Google 地点或照片已失效，请重新搜索或刷新信息", 409)
                    if response.status_code != 200:
                        raise PlacesError("Google Places 服务暂不可用")
                    buf = bytearray()
                    for chunk in response.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > MAX_JSON_BYTES:
                            raise PlacesError("Google Places 响应超过大小上限")
                import json

                value = json.loads(buf)
                if not isinstance(value, dict) or "error" in value:
                    raise PlacesError("Google Places 返回格式异常")
                return value
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == 0:
                    continue
                raise PlacesError("Google Places 连接超时或失败，请稍后重试或检查代理", 504) from e
            except (httpx.HTTPError, ValueError, ImportError) as e:
                if isinstance(e, PlacesError):
                    raise
                raise PlacesError("Google Places 连接或响应异常，请检查网络和配置") from e
        raise PlacesError("Google Places 服务暂不可用")  # pragma: no cover

    def search(self, query: str) -> list[Place]:
        value = self._request(
            "POST",
            "/places:searchText",
            "Text Search Pro",
            fields=SEARCH_FIELDS,
            payload={"textQuery": query, "pageSize": 3, "languageCode": "en", "regionCode": "GB"},
        )
        try:
            return SearchResponse.model_validate(value).places
        except ValidationError as e:
            raise PlacesError("Google Places 候选格式异常") from e

    def details(self, place_id: str) -> Place:
        if not PLACE_ID.fullmatch(place_id):
            raise PlacesError("地点标识无效", 400)
        value = self._request("GET", "/places/" + place_id, "Place Details Enterprise", fields=DETAIL_FIELDS)
        try:
            place = Place.model_validate(value)
            if place.id != place_id or any(not p.name.startswith(f"places/{place_id}/photos/") for p in place.photos):
                raise ValueError
            return place
        except ValueError as e:
            raise PlacesError("Google Places 详情格式异常") from e

    def enrichment_details(self, place_id: str) -> Place:
        if not PLACE_ID.fullmatch(place_id):
            raise PlacesError("地点标识无效", 400)
        value = self._request(
            "GET",
            "/places/" + place_id,
            "Place Details Enterprise",
            fields="id,displayName,formattedAddress,websiteUri,primaryType,primaryTypeDisplayName,internationalPhoneNumber,attributions",
        )
        try:
            place = Place.model_validate(value)
            if place.id != place_id:
                raise ValueError
            return place
        except ValueError as exc:
            raise PlacesError("Google Places 补充详情格式异常") from exc

    def photo(self, name: str) -> tuple[bytes, str]:
        if not PHOTO_NAME.fullmatch(name):
            raise PlacesError("照片标识无效", 400)
        value = self._request(
            "GET",
            "/" + name + "/media",
            "Place Details Photos",
            params={"maxWidthPx": 1600, "maxHeightPx": 1600, "skipHttpRedirect": "true"},
        )
        uri = value.get("photoUri")
        if not isinstance(uri, str) or not safe_google_url(uri):
            raise PlacesError("Google 照片链接异常")
        host = urlsplit(uri).hostname or ""
        if not host.endswith(".googleusercontent.com"):
            raise PlacesError("Google 照片链接异常")
        try:
            with (
                httpx.Client(
                    proxy=self.proxy if self.transport is None else None,
                    transport=self.transport,
                    trust_env=False,
                    timeout=httpx.Timeout(12, connect=5),
                    follow_redirects=False,
                ) as client,
                client.stream("GET", uri) as response,  # 不向照片主机转发密钥
            ):
                media_type = response.headers.get("content-type", "").split(";")[0]
                if response.status_code != 200 or media_type not in (
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                    "image/gif",
                ):
                    raise PlacesError("Google 照片无法加载，请刷新信息后重试", 409)
                buf = bytearray()
                for chunk in response.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_PHOTO_BYTES:
                        raise PlacesError("Google 照片超过大小上限")
                return bytes(buf), media_type
        except httpx.HTTPError as e:
            raise PlacesError("Google 照片连接失败，请稍后重试", 504) from e
