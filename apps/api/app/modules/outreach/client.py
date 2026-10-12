"""Meta HTTP adapter. Credentials are kept in the independent provider service."""

import httpx

from app.core.config import get_settings


class ProviderError(ValueError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def call(method: str, path: str, body: dict | None = None) -> dict:
    settings = get_settings()
    key = settings.meta_service_token_file
    if not settings.meta_service_url or not key or not key.is_file():
        raise ProviderError("Meta 服务尚未配置")
    try:
        with httpx.Client(
            base_url=settings.meta_service_url,
            timeout=45,
            trust_env=False,
            headers={"Authorization": "Bearer " + key.read_text().strip()},
        ) as http:
            response = http.request(method, path, json=body)
        if not response.is_success:
            raise ProviderError(response.json().get("detail", "Meta 服务拒绝请求"), response.status_code)
        return response.json()
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError):
        raise ProviderError("Meta 服务请求失败，请检查连接；发送结果应先查询确认") from None
