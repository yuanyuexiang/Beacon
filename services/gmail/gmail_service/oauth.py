"""Candidate OAuth validation; never overwrites the active account on network failure."""

import json
import urllib.error
import urllib.request

from . import core


def identity(access_token: str, scopes: set[str]) -> dict:
    legacy = not ({"openid", "email", "https://www.googleapis.com/auth/userinfo.email"} & scopes) and bool(
        {core.GMAIL_READONLY_SCOPE, core.GMAIL_METADATA_SCOPE} & scopes
    )
    url = (
        "https://gmail.googleapis.com/gmail/v1/users/me/profile"
        if legacy
        else "https://openidconnect.googleapis.com/v1/userinfo"
    )
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + access_token})
    for attempt in range(core.SAFE_HTTP_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=core.request_timeout()) as response:
                data = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == core.SAFE_HTTP_ATTEMPTS - 1:
                raise core.GmailError(f"account_identity_http_{exc.code}") from None
        except OSError:
            if attempt == core.SAFE_HTTP_ATTEMPTS - 1:
                raise core.GmailError("account_identity_network") from None
        except ValueError:
            raise core.GmailError("account_identity_response") from None
        core.time.sleep(core.SAFE_HTTP_BACKOFF_SECONDS[attempt])
    email = data.get("emailAddress") if legacy else data.get("email")
    if not email or ("@" not in str(email)) or (not legacy and data.get("email_verified") is not True):
        raise core.GmailError("account_identity_failed")
    return {"email": email}


def validate_token(config: dict, token: dict) -> tuple[dict, str]:
    fresh = core._post_form(
        "https://oauth2.googleapis.com/token",
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        },
    )
    candidate = {**token, **fresh, "obtained_at": core.time.time()}
    scopes = core._granted_scopes(candidate)
    if core.GMAIL_SEND_SCOPE not in scopes:
        raise core.GmailError("missing_send_scope")
    email = identity(candidate.get("access_token", ""), scopes)["email"]
    return candidate, email


def diagnostic(error: Exception | str) -> dict:
    message = str(error)
    cases = [
        (
            "account_identity_http_403",
            "account_identity_http_403",
            "Google 拒绝邮箱身份查询（403），请核对身份权限及 Gmail API 是否已启用。",
        ),
        (
            "account_identity_http_401",
            "account_identity_http_401",
            "Google 拒绝当前身份令牌（401），请重新连接并授予邮箱身份权限。",
        ),
        (
            "account_identity_network",
            "account_identity_network",
            "邮箱身份查询网络连接失败，请检查 Gmail 服务到 Google 的网络后重新连接。",
        ),
        ("account_identity_response", "account_identity_response", "Google 身份查询返回格式异常，请稍后重新连接。"),
        (
            "invalid_grant",
            "invalid_grant",
            "Google 授权已失效或授权码不可用，请重新连接；可同时核对项目 Testing 状态。",
        ),
        ("invalid_client", "invalid_client", "OAuth 客户端无效，请重新配置对应环境的 Web 客户端。"),
        (
            "redirect_uri_mismatch",
            "redirect_uri_mismatch",
            "回调地址不匹配，请将页面显示的完整地址登记到 Google 客户端。",
        ),
        ("access_denied", "access_denied", "你取消了授权，或当前账号不在 Google 项目允许的测试用户中。"),
        ("missing_send_scope", "missing_send_scope", "未授予发送权限，请重新连接并允许发送邮件。"),
        ("missing_read_scope", "missing_read_scope", "未授予邮件头读取权限，发信连接保留；可重新开启回复同步。"),
        ("account_identity_failed", "account_identity_failed", "暂时无法验证邮箱身份，请核对网络及账号身份权限。"),
        ("disallowed_useragent", "browser_blocked", "请在正常 Chrome 或 Safari 中完成 Google 登录。"),
    ]
    for match, code, text in cases:
        if match in message:
            return {"code": code, "message": text, "requires_reauth": code in {"invalid_grant", "missing_send_scope"}}
    return {
        "code": "connection_failed",
        "message": "连接 Google 失败，请检查网络后重试；原连接未替换。",
        "requires_reauth": False,
    }
