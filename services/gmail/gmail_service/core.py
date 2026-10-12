#!/usr/bin/env python3
"""Adapted from the user-owned OPC Business OS gmail_core.py (0.5.0).
OAuth, immutable previews, duplicate checks and durable send audit.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import http.client
import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from contextlib import contextmanager
from contextvars import ContextVar
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SCOPES = (GMAIL_SEND_SCOPE, GMAIL_READONLY_SCOPE)
DEFAULT_DIR = Path.home() / ".config" / "opc-business-os" / "gmail"
DEFAULT_AUDIT_DB = Path.home() / ".opc-business-os" / "gmail-audit.db"
TOKEN_TTL_SECONDS = 30 * 60
REQUEST_DEADLINE = ContextVar("gmail_request_deadline", default=None)
SAFE_HTTP_ATTEMPTS = 3
SAFE_HTTP_BACKOFF_SECONDS = (0.5, 1.5)


class GmailError(ValueError):
    pass


@contextmanager
def request_budget(seconds: int):
    token = REQUEST_DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        REQUEST_DEADLINE.reset(token)


def request_timeout() -> float:
    deadline = REQUEST_DEADLINE.get()
    if deadline is None:
        return 30
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GmailError("Gmail 只读操作已达到时间上限，请稍后再试")
    return min(30, remaining)


def credentials_path() -> Path:
    return Path(os.environ.get("GMAIL_CREDENTIALS_PATH", DEFAULT_DIR / "credentials.json")).expanduser()


def token_path() -> Path:
    return Path(os.environ.get("GMAIL_TOKEN_PATH", DEFAULT_DIR / "token.json")).expanduser()


def secret_path() -> Path:
    return Path(os.environ.get("GMAIL_APPROVAL_SECRET_PATH", DEFAULT_DIR / "approval-secret")).expanduser()


def audit_path() -> Path:
    return Path(os.environ.get("GMAIL_AUDIT_DB", DEFAULT_AUDIT_DB)).expanduser()


def _private_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp." + secrets.token_hex(8))
    temporary.write_text(data, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _client_config() -> dict[str, str]:
    path = credentials_path()
    if not path.is_file():
        raise GmailError(f"找不到 Gmail OAuth 凭据：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cfg = raw.get("installed") or raw.get("web")
        return {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "token_uri": cfg.get("token_uri", "https://oauth2.googleapis.com/token"),
            "auth_uri": cfg.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GmailError(f"Gmail OAuth 凭据格式无效：{path}") from exc


def _post_form(url: str, values: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    last_error: Exception | None = None
    for attempt in range(SAFE_HTTP_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=request_timeout()) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code not in {429, 500, 502, 503, 504}:
                raise GmailError(f"Google OAuth 请求失败（HTTP {exc.code}）：{detail[:500]}") from exc
            last_error = exc
        except (urllib.error.URLError, OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < SAFE_HTTP_ATTEMPTS - 1:
            time.sleep(SAFE_HTTP_BACKOFF_SECONDS[attempt])
    raise GmailError(
        f"Google OAuth 请求连续 {SAFE_HTTP_ATTEMPTS} 次失败：{last_error}。"
        "请检查代理对 oauth2.googleapis.com:443 的连接；不要删除 Token 或重复授权。"
    ) from last_error


def authorize(timeout_seconds: int = 300) -> Path:
    cfg = _client_config()
    result: dict[str, str] = {}
    state = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_error(400, "OAuth state mismatch")
                result["error"] = "OAuth state 不匹配"
            elif query.get("error"):
                result["error"] = query["error"][0]
                self.send_error(400, result["error"])
            else:
                result["code"] = query.get("code", [""])[0]
                body = b"Gmail authorization complete. You can close this tab."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = cfg["auth_uri"] + "?" + urllib.parse.urlencode(params)
    print(f"请在浏览器完成 Gmail 授权：\n{url}", file=os.sys.stderr)
    webbrowser.open(url)
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    server.server_close()
    if thread.is_alive():
        raise GmailError("Gmail 授权等待超时")
    if result.get("error") or not result.get("code"):
        raise GmailError(result.get("error", "Gmail 授权未返回授权码"))
    token = _post_form(
        cfg["token_uri"],
        {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "code": result["code"],
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    token["obtained_at"] = int(time.time())
    _private_write(token_path(), json.dumps(token, ensure_ascii=False, indent=2))
    return token_path()


def _granted_scopes(token: dict[str, Any]) -> set[str]:
    return set(str(token.get("scope", "")).split())


def _access_token(required_scope: str | None = None) -> str:
    cfg = _client_config()
    path = token_path()
    if not path.is_file():
        raise GmailError(f"尚未授权 Gmail，请先运行 gmail_mcp_server.py auth；Token 路径：{path}")
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GmailError(f"Gmail Token 无法读取：{path}") from exc
    if required_scope and required_scope not in _granted_scopes(token):
        raise GmailError("当前 Gmail Token 没有收件箱只读权限，请运行 gmail_mcp_server.py auth 重新授权")
    expires_at = int(token.get("obtained_at", 0)) + int(token.get("expires_in", 0)) - 60
    if token.get("access_token") and time.time() < expires_at:
        return token["access_token"]
    if not token.get("refresh_token"):
        raise GmailError("Gmail Token 已过期且没有 refresh_token，请重新授权")
    fresh = _post_form(
        cfg["token_uri"],
        {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        },
    )
    token.update(fresh)
    token["obtained_at"] = int(time.time())
    _private_write(path, json.dumps(token, ensure_ascii=False, indent=2))
    return token["access_token"]


def auth_status() -> dict[str, Any]:
    path = token_path()
    granted: set[str] = set()
    if path.is_file():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            granted = _granted_scopes(json.loads(path.read_text(encoding="utf-8")))
    return {
        "credentials_path": str(credentials_path()),
        "credentials_present": credentials_path().is_file(),
        "token_path": str(path),
        "token_present": path.is_file(),
        "requested_scopes": list(GMAIL_SCOPES),
        "send_authorized": GMAIL_SEND_SCOPE in granted,
        "readonly_authorized": GMAIL_READONLY_SCOPE in granted,
        "test_sender": os.environ.get("GMAIL_SENDER_EMAIL"),
        "local_daily_send_limit": daily_send_limit(),
    }


def _gmail_get(path: str, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    query = "?" + urllib.parse.urlencode(params or [], doseq=True) if params else ""
    req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/" + path + query,
        headers={"Authorization": f"Bearer {_access_token(GMAIL_READONLY_SCOPE)}"},
    )
    last_error: Exception | None = None
    for attempt in range(SAFE_HTTP_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=request_timeout()) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code not in {429, 500, 502, 503, 504}:
                raise GmailError(f"Gmail 读取失败（HTTP {exc.code}）：{detail[:500]}") from exc
            last_error = exc
        except (urllib.error.URLError, OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < SAFE_HTTP_ATTEMPTS - 1:
            time.sleep(SAFE_HTTP_BACKOFF_SECONDS[attempt])
    raise GmailError(
        f"Gmail 读取连续 {SAFE_HTTP_ATTEMPTS} 次失败：{last_error}。请检查代理对 gmail.googleapis.com:443 的连接。"
    ) from last_error


def _headers(message: dict[str, Any]) -> dict[str, str]:
    wanted = {
        "from",
        "to",
        "cc",
        "subject",
        "date",
        "message-id",
        "in-reply-to",
        "references",
    }
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in message.get("payload", {}).get("headers", [])
        if str(item.get("name", "")).lower() in wanted
    }


def check_replies(message_ids: list[str]) -> dict[str, Any]:
    if not isinstance(message_ids, list) or not message_ids or len(message_ids) > 20:
        raise GmailError("message_ids 必须包含 1 到 20 个 Gmail message ID")
    cleaned = []
    for value in message_ids:
        message_id = str(value).strip()
        if (
            not message_id
            or len(message_id) > 128
            or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in message_id)
        ):
            raise GmailError(f"无效的 Gmail message ID：{message_id}")
        if message_id not in cleaned:
            cleaned.append(message_id)
    profile = _gmail_get("profile")
    self_email = str(profile.get("emailAddress", "")).casefold()
    header_params = [("format", "metadata")] + [
        ("metadataHeaders", name)
        for name in (
            "From",
            "To",
            "Cc",
            "Subject",
            "Date",
            "Message-ID",
            "In-Reply-To",
            "References",
        )
    ]
    results = []
    for sent_id in cleaned:
        original = _gmail_get("messages/" + urllib.parse.quote(sent_id, safe=""), header_params)
        thread_id = str(original.get("threadId", ""))
        if not thread_id:
            raise GmailError(f"Gmail message {sent_id} 没有 threadId")
        thread = _gmail_get("threads/" + urllib.parse.quote(thread_id, safe=""), header_params)
        original_time = int(original.get("internalDate", 0) or 0)
        replies = []
        for message in thread.get("messages", []):
            if message.get("id") == sent_id or int(message.get("internalDate", 0) or 0) <= original_time:
                continue
            headers = _headers(message)
            sender = parseaddr(headers.get("from", ""))[1].casefold()
            if self_email and sender == self_email:
                continue
            replies.append(
                {
                    "id": message.get("id"),
                    "threadId": message.get("threadId", thread_id),
                    "internalDate": message.get("internalDate"),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "cc": headers.get("cc", ""),
                    "subject": headers.get("subject", ""),
                    "date": headers.get("date", ""),
                    "messageId": headers.get("message-id", ""),
                }
            )
        results.append(
            {
                "sent_message_id": sent_id,
                "threadId": thread_id,
                "has_reply": bool(replies),
                "replies": replies,
            }
        )
    return {
        "checked": len(results),
        "results": results,
        "metadata_only": True,
        "notice": "只返回邮件头元数据，不返回正文或附件。",
    }


def _addresses(values: list[str] | None, field: str) -> list[str]:
    result = []
    for name, address in getaddresses(values or []):
        parsed = parseaddr(f"{name} <{address}>" if name else address)[1]
        if not parsed or "@" not in parsed or any(ch in parsed for ch in "\r\n"):
            raise GmailError(f"{field} 中包含无效邮箱地址：{address or name}")
        result.append(parsed)
    return result


def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    out = {
        "to": _addresses(payload.get("to"), "to"),
        "cc": _addresses(payload.get("cc"), "cc"),
        "bcc": _addresses(payload.get("bcc"), "bcc"),
        "subject": str(payload.get("subject", "")).strip(),
        "body": str(payload.get("body", "")),
        "opportunity_id": str(payload.get("opportunity_id", "")).strip(),
        "contact_id": str(payload.get("contact_id", "")).strip(),
    }
    if not out["to"]:
        raise GmailError("to 至少需要一个收件人")
    if not out["subject"]:
        raise GmailError("subject 不能为空")
    if not out["body"].strip():
        raise GmailError("body 不能为空")
    return out


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _secret() -> bytes:
    path = secret_path()
    if not path.exists():
        _private_write(path, secrets.token_hex(32))
    return bytes.fromhex(path.read_text(encoding="utf-8").strip())


def preview(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize(payload)
    issued = int(time.time())
    fingerprint = _fingerprint(normalized)
    data = f"{issued}.{fingerprint}"
    signature = hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()
    return {
        **normalized,
        "approval_token": f"{data}.{signature}",
        "expires_at": issued + TOKEN_TTL_SECONDS,
        "notice": "该令牌只批准以上完全相同的邮件内容；发送前必须获得用户明确确认。",
    }


def _verify(payload: dict[str, Any], approval_token: str) -> str:
    try:
        issued_text, fingerprint, signature = approval_token.split(".", 2)
        issued = int(issued_text)
    except (ValueError, AttributeError) as exc:
        raise GmailError("approval_token 格式无效，请重新预览") from exc
    expected_fingerprint = _fingerprint(payload)
    data = f"{issued}.{fingerprint}"
    expected = hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected) or not hmac.compare_digest(fingerprint, expected_fingerprint):
        raise GmailError("邮件内容与批准预览不一致，请重新预览")
    if time.time() - issued > TOKEN_TTL_SECONDS or issued > time.time() + 60:
        raise GmailError("批准令牌已过期，请重新预览")
    return fingerprint


def _audit_connect() -> sqlite3.Connection:
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS sends(id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, "
        "recipients TEXT NOT NULL, subject TEXT NOT NULL, gmail_message_id TEXT, "
        "gmail_thread_id TEXT, status TEXT NOT NULL, created_at INTEGER NOT NULL)"
    )
    db.commit()
    path.chmod(0o600)
    return db


def daily_send_limit() -> int | None:
    """Optional local budget, separate from Google's account-wide limits."""
    value = os.environ.get("GMAIL_DAILY_SEND_LIMIT", "").strip()
    if not value:
        return None
    try:
        limit = int(value)
    except ValueError as exc:
        raise GmailError("GMAIL_DAILY_SEND_LIMIT 必须为非负整数；0 表示不设本地每日限额") from exc
    if limit < 0:
        raise GmailError("GMAIL_DAILY_SEND_LIMIT 必须为非负整数；0 表示不设本地每日限额")
    return limit or None


def _check_limits(db: sqlite3.Connection, fingerprint: str, allow_duplicate: bool) -> None:
    now = int(time.time())
    daily_limit = daily_send_limit()
    if daily_limit is not None:
        count = db.execute(
            "SELECT COUNT(*) FROM sends WHERE status IN ('sent','pending','unknown') AND created_at>=?",
            (now - 86400,),
        ).fetchone()[0]
        if count >= daily_limit:
            raise GmailError(f"已达到用户配置的过去24小时本地发送上限：{daily_limit} 封")
    unresolved = db.execute(
        "SELECT id FROM sends WHERE status IN ('pending','unknown') AND fingerprint=?",
        (fingerprint,),
    ).fetchone()
    if unresolved:
        raise GmailError(
            f"相同邮件存在未核对的发送尝试 {unresolved['id']}；请先核对已发送邮件并使用 resolve-send 记录结果"
        )
    duplicate = db.execute(
        "SELECT 1 FROM sends WHERE status='sent' AND fingerprint=? AND created_at>=?",
        (fingerprint, now - 86400),
    ).fetchone()
    if duplicate and not allow_duplicate:
        raise GmailError("相同邮件在过去24小时内已发送；如确需重发，请重新预览并设置 allow_duplicate=true")


def _raw_message(payload: dict[str, Any]) -> str:
    msg = EmailMessage()
    sender = os.environ.get("GMAIL_SENDER_EMAIL", "").strip()
    if sender:
        msg["From"] = sender
    msg["To"] = ", ".join(payload["to"])
    if payload["cc"]:
        msg["Cc"] = ", ".join(payload["cc"])
    if payload["bcc"]:
        msg["Bcc"] = ", ".join(payload["bcc"])
    msg["Subject"] = payload["subject"]
    msg.set_content(payload["body"])
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_approved(payload: dict[str, Any], approval_token: str, allow_duplicate: bool = False) -> dict[str, Any]:
    normalized = normalize(payload)
    fingerprint = _verify(normalized, approval_token)
    body = json.dumps({"raw": _raw_message(normalized)}).encode()
    req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        data=body,
        headers={
            "Authorization": f"Bearer {_access_token(GMAIL_SEND_SCOPE)}",
            "Content-Type": "application/json",
        },
    )
    db = _audit_connect()
    attempt_id = None
    result = None
    try:
        # Reserve before the network request; competing processes must see it.
        db.execute("BEGIN IMMEDIATE")
        _check_limits(db, fingerprint, allow_duplicate)
        sent_at = int(time.time())
        recipients = json.dumps(normalized["to"] + normalized["cc"] + normalized["bcc"], ensure_ascii=False)
        cursor = db.execute(
            "INSERT INTO sends(fingerprint,recipients,subject,status,created_at) VALUES(?,?,?,'pending',?)",
            (fingerprint, recipients, normalized["subject"], sent_at),
        )
        attempt_id = cursor.lastrowid
        db.commit()
        try:
            with urllib.request.urlopen(req, timeout=request_timeout()) as response:
                result = json.loads(response.read())
            if not isinstance(result, dict) or not result.get("id"):
                raise GmailError("Gmail 未返回有效的 message ID")
        except Exception as exc:
            # Only explicit client rejection establishes that no mail was sent.
            rejected = isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 and exc.code != 408
            state = "failed" if rejected else "unknown"
            db.execute("UPDATE sends SET status=? WHERE id=?", (state, attempt_id))
            db.commit()
            if rejected:
                if exc.code == 429:
                    raise GmailError(
                        f"Gmail 触发发送限额或请求频率限制（HTTP 429）；尝试 {attempt_id}。"
                        "这是 Google 服务端限制，不是插件本地预算；请稍后再试，插件不会自动重发。"
                    ) from exc
                raise GmailError(f"Gmail 发送失败（HTTP {exc.code}）；尝试 {attempt_id}") from exc
            raise GmailError(
                f"发送结果未知（尝试 {attempt_id}），已保留审计且不会自动重试或写入 outbound。"
                "请先核对 Gmail 已发送邮件，再使用 resolve-send 记录结果。"
            ) from exc
        db.execute(
            "UPDATE sends SET status='sent',gmail_message_id=?,gmail_thread_id=? WHERE id=?",
            (result["id"], result.get("threadId"), attempt_id),
        )
        db.commit()
    except sqlite3.Error as exc:
        raise GmailError(
            f"发送审计写入失败；尝试 {attempt_id}。若已调用 Gmail，结果须人工核对，禁止直接重发。"
            f" Gmail message ID：{result.get('id') if isinstance(result, dict) else None}"
        ) from exc
    finally:
        db.close()
    return {
        "status": "sent",
        "id": result.get("id"),
        "threadId": result.get("threadId"),
        "to": normalized["to"],
        "subject": normalized["subject"],
        "sent_at": sent_at,
        "attempt_id": attempt_id,
        "audit_db": str(audit_path()),
    }


def resolve_send(attempt_id: int, status: str, note: str, message_id: str = ""):
    """Maintenance only: record a manually verified result, without sending mail."""
    if status not in ("sent", "failed") or not note.strip():
        raise GmailError("核对结果必须为 sent/failed，并填写核对依据")
    if status == "sent" and not message_id.strip():
        raise GmailError("确认已发送时必须提供 Gmail message ID")
    db = _audit_connect()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sends WHERE id=?", (attempt_id,)).fetchone()
            if not row or row["status"] not in ("pending", "unknown"):
                raise GmailError("只能核对 pending/unknown 发送尝试")
            db.execute(
                "CREATE TABLE IF NOT EXISTS send_resolutions(id INTEGER PRIMARY KEY, "
                "attempt_id INTEGER NOT NULL, previous_status TEXT NOT NULL, "
                "status TEXT NOT NULL, note TEXT NOT NULL, created_at INTEGER NOT NULL)"
            )
            db.execute(
                "INSERT INTO send_resolutions(attempt_id,previous_status,status,note,created_at) VALUES(?,?,?,?,?)",
                (attempt_id, row["status"], status, note.strip(), int(time.time())),
            )
            db.execute(
                "UPDATE sends SET status=?,gmail_message_id=? WHERE id=?",
                (status, message_id.strip() or None, attempt_id),
            )
        return {"attempt_id": attempt_id, "status": status}
    finally:
        db.close()
