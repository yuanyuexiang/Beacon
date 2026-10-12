"""Only the backend knows the Gmail service bearer token; never forward it to browsers."""

import httpx

from app.core.config import get_settings


class GmailServiceError(ValueError):
    pass


def call(method: str, path: str, body: dict | None = None) -> dict:
    settings = get_settings()
    token_file = settings.gmail_service_token_file
    if not settings.gmail_service_url or not token_file or not token_file.is_file():
        raise GmailServiceError("Gmail 服务尚未配置")
    token = token_file.read_text().strip()
    try:
        with httpx.Client(
            base_url=settings.gmail_service_url,
            headers={"Authorization": "Bearer " + token},
            trust_env=False,
            timeout=120,
        ) as client:
            response = client.request(method, path, json=body)
            if not response.is_success:
                # 服务仅返回经过清理的 detail；不会回显凭据。
                raise GmailServiceError(response.json().get("detail", "Gmail 服务请求失败"))
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, GmailServiceError):
            raise
        raise GmailServiceError("Gmail 服务暂不可达，请检查服务状态；发送结果须先查询确认") from None
