"""Single-account Gmail HTTP/MCP service. Secret files never leave management endpoints."""

import json
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from . import core

LOCK = threading.RLock()


def db():
    conn = core._audit_connect()
    conn.execute("CREATE TABLE IF NOT EXISTS oauth_states(state TEXT PRIMARY KEY, expires INTEGER NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def status() -> dict:
    result = core.auth_status()
    public = {key: value for key, value in result.items() if not key.endswith("_path")}
    connection = core.token_path().parent / "connection.json"
    if connection.exists():
        public.update(json.loads(connection.read_text()))
    account = core.token_path().parent / "account.json"
    if account.exists():
        public["email"] = json.loads(account.read_text()).get("email")
    return public


def policy() -> dict:
    path = core.token_path().parent / "policy.json"
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"sending_enabled": False, "queue_enabled": False, "daily_limit": 0}
    )


def set_policy(values: dict) -> dict:
    with LOCK:
        core._private_write(core.token_path().parent / "policy.json", json.dumps(values))
    return values


def validate_config(credentials: dict) -> dict:
    if bool(credentials.get("web")) == bool(credentials.get("installed")):
        raise HTTPException(400, "OAuth 配置必须且只能包含一种客户端类型")
    config = credentials.get("web") or credentials.get("installed")
    if not isinstance(config, dict) or not config.get("client_id") or not config.get("client_secret"):
        raise HTTPException(400, "OAuth 凭据需包含 web 或 installed 客户端")
    # 不从上传配置中调用任意 URL。
    for key, expected in (
        ("token_uri", "https://oauth2.googleapis.com/token"),
        ("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
    ):
        if config.get(key, expected) != expected:
            raise HTTPException(400, "OAuth 地址必须使用 Google 官方地址")
    return config


def import_credentials(credentials: dict, token: dict | None) -> dict:
    validate_config(credentials)
    if token is not None and (not token.get("refresh_token") or not token.get("scope")):
        raise HTTPException(400, "导入令牌缺少 refresh_token 或 scope")
    with LOCK:
        core._private_write(core.secret_path(), secrets.token_hex(32))
        (core.token_path().parent / "account.json").unlink(missing_ok=True)
        (core.token_path().parent / "connection.json").unlink(missing_ok=True)
        set_policy({**policy(), "sending_enabled": False, "queue_enabled": False})
        core._private_write(core.credentials_path(), json.dumps(credentials))
        if token is None:
            core.token_path().unlink(missing_ok=True)
        else:
            # 核对现有 access token 时间；缺失时强制通过 refresh token 刷新。
            core._private_write(core.token_path(), json.dumps(token))
        with db() as conn:
            conn.execute("DELETE FROM oauth_states")
    return status()


def safe_error(error: Exception) -> str:
    if "invalid_grant" in str(error):
        return "Google 刷新令牌无效（invalid_grant），需要重新授权"
    if "invalid_client" in str(error):
        return "Google OAuth 客户端无效，请核对客户端凭据与令牌是否匹配"
    return "Gmail 操作失败，请检查授权、网络或发送记录"


def verify_connection() -> dict:
    with LOCK, core.request_budget(100):
        try:
            core._access_token(core.GMAIL_SEND_SCOPE)
            profile = core._gmail_get("profile")
        except core.GmailError as error:
            core._private_write(
                core.token_path().parent / "connection.json",
                json.dumps(
                    {
                        "connection_error": safe_error(error),
                        "requires_reauth": "invalid_grant" in str(error),
                        "connected": False,
                    }
                ),
            )
            raise
        core._private_write(
            core.token_path().parent / "account.json", json.dumps({"email": profile.get("emailAddress")})
        )
        core._private_write(core.token_path().parent / "connection.json", json.dumps({"connected": True}))
    return {**status(), "email": profile.get("emailAddress"), "connected": True}


def begin_auth() -> dict:
    credentials = json.loads(core.credentials_path().read_text()) if core.credentials_path().exists() else {}
    config = validate_config(credentials)
    if "web" not in credentials:
        raise HTTPException(400, "服务器重新授权需上传 Web application 类型 OAuth 凭据；现有 Desktop 令牌可导入使用")
    redirect = os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:3000/api/gmail/oauth/callback")
    state = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("DELETE FROM oauth_states WHERE expires < ?", (int(time.time()),))
        conn.execute("INSERT INTO oauth_states VALUES(?,?)", (state, int(time.time()) + 600))
    return {
        "url": config.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        + "?"
        + urlencode(
            {
                "client_id": config["client_id"],
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": " ".join(core.GMAIL_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
    }


def finish_auth(code: str, state: str) -> dict:
    with LOCK, db() as conn:
        row = conn.execute(
            "DELETE FROM oauth_states WHERE state=? AND expires>=? RETURNING state", (state, int(time.time()))
        ).fetchone()
        conn.commit()
        if not row:
            raise HTTPException(400, "授权会话无效或已过期，请重新连接")
        config = core._client_config()
        token = core._post_form(
            config["token_uri"],
            {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:3000/api/gmail/oauth/callback"),
            },
        )
        if not token.get("refresh_token"):
            raise HTTPException(400, "Google 未返回 refresh_token，请重新授权")
        token["obtained_at"] = int(time.time())
        core._private_write(core.secret_path(), secrets.token_hex(32))
        (core.token_path().parent / "account.json").unlink(missing_ok=True)
        (core.token_path().parent / "connection.json").unlink(missing_ok=True)
        set_policy({**policy(), "sending_enabled": False, "queue_enabled": False})
        core._private_write(core.token_path(), json.dumps(token))
    return verify_connection()


def request_result(key: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM requests WHERE key=?", (key,)).fetchone()
        if not row:
            return {"status": "not_found"}
        result = json.loads(row["result"])
        if result.get("status") == "unknown":
            attempt = conn.execute(
                "SELECT * FROM sends WHERE fingerprint=? ORDER BY id DESC LIMIT 1", (row["fingerprint"],)
            ).fetchone()
            if attempt:
                result = {
                    "status": attempt["status"] if attempt["status"] != "pending" else "unknown",
                    "id": attempt["gmail_message_id"],
                    "threadId": attempt["gmail_thread_id"],
                    "sent_at": attempt["created_at"],
                    "attempt_id": attempt["id"],
                }
                conn.execute("UPDATE requests SET result=? WHERE key=?", (json.dumps(result), key))
        return result


def send(payload: dict, approval_token: str, key: str) -> dict:
    normalized = core.normalize(payload)
    fingerprint = core._verify(normalized, approval_token)
    with LOCK, db() as conn:
        settings = policy()
        if not settings["sending_enabled"]:
            raise HTTPException(409, "邮件发送已暂停")
        if len(normalized["to"]) != 1 or normalized["cc"] or normalized["bcc"]:
            raise HTTPException(400, "每个发送请求只允许一个客户邮箱")
        os.environ["GMAIL_DAILY_SEND_LIMIT"] = str(settings["daily_limit"])
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM requests WHERE key=?", (key,)).fetchone()
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise HTTPException(409, "发送请求键已绑定不同内容")
            return json.loads(previous["result"])
        conn.execute("INSERT INTO requests VALUES(?,?,?)", (key, fingerprint, json.dumps({"status": "unknown"})))
        # core._audit_connect 已创建 sends 表。
        before = conn.execute("SELECT coalesce(max(id),0) FROM sends").fetchone()[0]
        conn.commit()
        try:
            result = core.send_approved(normalized, approval_token)
            result.pop("audit_db", None)
        except (core.GmailError, OSError, ValueError):
            # 服务端审计是发送结果依据；错误消息不输出 OAuth 响应或凭据。
            attempt = conn.execute(
                "SELECT * FROM sends WHERE fingerprint=? AND id>? ORDER BY id DESC LIMIT 1", (fingerprint, before)
            ).fetchone()
            if attempt:
                state = attempt["status"]
                result = {
                    "status": "unknown" if state == "pending" else state,
                    "attempt_id": attempt["id"],
                    "id": attempt["gmail_message_id"],
                    "threadId": attempt["gmail_thread_id"],
                    "sent_at": attempt["created_at"],
                }
            else:
                result = {"status": "failed", "reason": "授权、预览、限额或重复检查未通过，未发起发送"}
        conn.execute("UPDATE requests SET result=? WHERE key=?", (json.dumps(result), key))
        conn.commit()
    return result


mcp = FastMCP(
    "beacon-gmail",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*", "gmail-service:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://gmail-service:*"],
    ),
)


@mcp.tool()
def gmail_auth_status() -> dict:
    """检查授权配置；不返回凭据。"""
    return status()


@mcp.tool()
def gmail_preview_email(to: list[str], subject: str, body: str) -> dict:
    """完整预览并生成批准令牌；不发送。"""
    with LOCK:
        return core.preview({"to": to, "subject": subject, "body": body})


@mcp.tool()
def gmail_send_approved_email(to: list[str], subject: str, body: str, approval_token: str, request_key: str) -> dict:
    """只发送已完整预览且用户明确批准的相同邮件；请求键防重复。"""
    return send({"to": to, "subject": subject, "body": body}, approval_token, request_key)


@mcp.tool()
def gmail_get_send_status(request_key: str) -> dict:
    """查询既有发送请求结果；不发送，不重试结果未知的邮件。"""
    return request_result(request_key)


@mcp.tool()
def gmail_check_replies(message_ids: list[str]) -> dict:
    """只读取已发送线程的回复邮件头；不返回正文附件。"""
    with LOCK, core.request_budget(100):
        return core.check_replies(message_ids)


@asynccontextmanager
async def lifespan(_):
    async with mcp.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    secret_file = Path(os.environ.get("GMAIL_SERVICE_TOKEN_FILE", "/run/secrets/gmail_service_token"))
    token = secret_file.read_text().strip() if secret_file.is_file() else ""
    if len(token) < 32 or not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
        return JSONResponse({"detail": "Gmail 服务认证失败"}, status_code=401)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(core.GmailError)
async def gmail_error(_, exc):
    return JSONResponse({"detail": safe_error(exc)}, status_code=502)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/status")
def auth_status():
    return status()


class PolicyIn(BaseModel):
    sending_enabled: bool = False
    queue_enabled: bool = False
    daily_limit: int = Field(default=0, ge=0, le=100000)


@app.get("/policy")
def get_policy():
    return policy()


@app.put("/policy")
def update_policy(body: PolicyIn):
    return set_policy(body.model_dump())


class ImportIn(BaseModel):
    credentials: dict
    token: dict | None = None


@app.post("/auth/import")
def auth_import(body: ImportIn):
    return import_credentials(body.credentials, body.token)


@app.post("/auth/check")
def auth_check():
    return verify_connection()


@app.post("/auth/start")
def auth_start():
    return begin_auth()


class CallbackIn(BaseModel):
    code: str = Field(max_length=4096)
    state: str = Field(max_length=256)


@app.post("/auth/callback")
def auth_callback(body: CallbackIn):
    return finish_auth(body.code, body.state)


@app.post("/auth/disconnect")
def auth_disconnect():
    with LOCK:
        core.token_path().unlink(missing_ok=True)
        with db() as conn:
            conn.execute("DELETE FROM oauth_states")
    return {"connected": False}


class MailIn(BaseModel):
    to: list[str] = Field(min_length=1, max_length=1)
    subject: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=50000)


class SendIn(MailIn):
    approval_token: str = Field(max_length=256)
    request_key: str = Field(min_length=1, max_length=128)


@app.post("/preview")
def mail_preview(body: MailIn):
    with LOCK:
        return core.preview(body.model_dump())


@app.post("/send")
def mail_send(body: SendIn):
    return send(body.model_dump(exclude={"approval_token", "request_key"}), body.approval_token, body.request_key)


@app.get("/requests/{key}")
def mail_result(key: str):
    return request_result(key)


class ReplyIn(BaseModel):
    message_ids: list[str] = Field(min_length=1, max_length=20)


@app.post("/replies")
def mail_replies(body: ReplyIn):
    return gmail_check_replies(body.message_ids)


app.mount("/mcp", mcp.streamable_http_app())
