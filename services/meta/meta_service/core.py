"""Meta credentials and durable send ledger. No automatic retry of an external POST."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

LOCK = threading.RLock()


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)

    return wrapped


class MetaError(ValueError):
    pass


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise MetaError("账号或收件人 ID 无效；不能使用主页 URL")
    return value


def digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Core:
    @serialized
    def __init__(self, data_dir: Path):
        self.root = data_dir
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.db_path = self.root / "ledger.db"
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, hash TEXT, result TEXT)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(requests)")}
            if "account" not in columns:
                db.execute("ALTER TABLE requests ADD COLUMN account TEXT")
            if "claimed" not in columns:
                db.execute("ALTER TABLE requests ADD COLUMN claimed REAL")
            db.execute("CREATE TABLE IF NOT EXISTS states (key TEXT PRIMARY KEY, account TEXT, expires REAL)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(states)")}
            for name in ("candidate", "binding", "base_version"):
                if name not in columns:
                    db.execute(f"ALTER TABLE states ADD COLUMN {name} TEXT")
        self.db_path.chmod(0o600)
        secret = self.root / "approval-secret"
        if not secret.exists():
            try:
                with secret.open("x") as f:
                    os.chmod(secret, 0o600)
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        self.secret = secret.read_text().strip().encode()

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def read(self, key: str) -> dict:
        path = self.root / (identifier(key) + ".json")
        return json.loads(path.read_text()) if path.exists() else {}

    def write(self, key: str, data: dict):
        path = self.root / (identifier(key) + ".json")
        tmp = path.with_suffix("." + secrets.token_hex(6) + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    def app_status(self) -> dict:
        app = self.read("app")
        return {
            "configured": bool(app.get("app_id") and app.get("app_secret")),
            "app_id": app.get("app_id"),
            "version": app.get("version", "v25.0"),
            "redirect_uri": app.get("redirect_uri"),
            "webhook_configured": bool(app.get("verify_token")),
        }

    @serialized
    def configure_app(self, data: dict) -> dict:
        if not re.fullmatch(r"v\d+\.\d+", data["version"]):
            raise MetaError("Graph API 版本格式应为 v25.0")
        redirect = urlsplit(data["redirect_uri"])
        if (
            redirect.username
            or redirect.password
            or redirect.fragment
            or not redirect.hostname
            or not (redirect.scheme == "https" or (redirect.scheme == "http" and redirect.hostname == "localhost"))
        ):
            raise MetaError("OAuth 回调需使用 HTTPS 或本机 localhost")
        identifier(data["app_id"])
        old = self.read("app")
        if old and any(old.get(k) != data.get(k) for k in ("app_id", "app_secret", "version")):
            # Old previews may not survive app or API route changes.
            for path in self.root.glob("*.json"):
                if path.stem != "app":
                    account = self.read(path.stem)
                    account.update(verified=False, sending_enabled=False, version=secrets.token_hex(16))
                    self.write(path.stem, account)
        with self.db() as db:
            db.execute("DELETE FROM states")
        self.write("app", data)
        return self.app_status()

    def account_status(self, key: str) -> dict:
        a = self.read(key)
        return {
            "configured": bool(a.get("token")),
            "verified": bool(a.get("verified")),
            "sender_id": a.get("sender_id"),
            "name": a.get("name"),
            "version": a.get("version"),
            "sending_enabled": bool(a.get("sending_enabled")),
            "daily_limit": a.get("daily_limit", 20),
            "capabilities": ["text_reply"] if a.get("verified") else [],
            "auth_mode": a.get("auth_mode"),
            "platform": a.get("platform"),
        }

    @serialized
    def configure_account(self, key: str, data: dict) -> dict:
        identifier(data["sender_id"])
        old = self.read(key)
        a = {
            **data,
            "token": data.get("token") or old.get("token"),
            "version": secrets.token_hex(16),
            "verified": False,
            "sending_enabled": False,
        }
        if not a["token"]:
            raise MetaError("请先提供 Access Token 或完成 OAuth")
        self.write(key, a)
        return self.account_status(key)

    def graph(self, a: dict, method: str, path: str, body: dict | None = None) -> dict:
        host = "graph.instagram.com" if a.get("auth_mode") == "instagram_login" else "graph.facebook.com"
        version = self.read("app").get("version", "v25.0")
        try:
            with httpx.Client(timeout=30, trust_env=True) as client:
                response = client.request(
                    method,
                    f"https://{host}/{version}/{path}",
                    headers={"Authorization": "Bearer " + a["token"]},
                    json=body,
                )
            if response.status_code >= 500:
                raise MetaError("平台服务暂不可用")
            result = response.json()
            if not response.is_success or result.get("error"):
                code = (result.get("error") or {}).get("code")
                if code == 190 or response.status_code == 401:
                    raise MetaError("授权失效，请重新连接账号")
                raise MetaError("平台拒绝请求，请核对权限、收件人及会话条件")
            return result
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            raise MetaError("平台连接失败；发送结果需对账确认") from None

    def verify_identity(self, a: dict) -> dict:
        fields = "user_id,username" if a["auth_mode"] == "instagram_login" else "id,name"
        result = self.graph(a, "GET", "me?fields=" + fields)
        actual = str(result.get("user_id") or result.get("id") or "")
        # Facebook Login Instagram uses a Page token, validate its linked professional account.
        if a["platform"] == "instagram" and a["auth_mode"] == "facebook_login":
            result = self.graph(a, "GET", "me?fields=instagram_business_account{id,username}")
            ig = result.get("instagram_business_account") or {}
            actual, result = str(ig.get("id") or ""), ig
        if actual != a["sender_id"]:
            raise MetaError("Token 所属发送账号与配置不一致")
        return result

    @serialized
    def check(self, key: str) -> dict:
        a = self.read(key)
        if not a.get("token"):
            raise MetaError("账号尚未授权")
        try:
            result = self.verify_identity(a)
        except MetaError:
            a.update(verified=False, sending_enabled=False, version=secrets.token_hex(16))
            self.write(key, a)
            raise
        a.update(verified=True, name=result.get("name") or result.get("username"))
        self.write(key, a)
        return self.account_status(key)

    @serialized
    def policy(self, key: str, enabled: bool, daily_limit: int = 20) -> dict:
        a = self.read(key)
        if enabled and not a.get("verified"):
            raise MetaError("开启发送前请先检查账号连接")
        a["sending_enabled"] = enabled
        a["daily_limit"] = daily_limit
        self.write(key, a)
        return self.account_status(key)

    @serialized
    def disconnect(self, key: str) -> dict:
        a = self.read(key)
        a.update(token=None, verified=False, sending_enabled=False, version=secrets.token_hex(16))
        self.write(key, a)
        return self.account_status(key)

    @serialized
    def preview(self, body: dict) -> dict:
        a = self.read(body["account_id"])
        if not a.get("verified"):
            raise MetaError("账号尚未通过连接检查")
        identifier(body["recipient_id"])
        identifier(body["request_key"])
        if not body["text"].strip() or len(body["text"]) > 1000:
            raise MetaError("首期只支持 1 至 1000 字符的文字回复")
        expiry = min(int(time.time()) + 1800, body["window_expires_at"])
        if expiry <= time.time():
            raise MetaError("回复窗口已过期")
        data = {**body, "version": a["version"], "expires_at": expiry}
        raw = base64.urlsafe_b64encode(json.dumps(data, sort_keys=True).encode()).decode()
        sig = hmac.new(self.secret, raw.encode(), hashlib.sha256).hexdigest()
        return {**body, "expires_at": data["expires_at"], "version": a["version"], "approval_token": raw + "." + sig}

    @serialized
    def send(self, token: str) -> dict:
        try:
            raw, sig = token.split(".", 1)
            if not hmac.compare_digest(sig, hmac.new(self.secret, raw.encode(), hashlib.sha256).hexdigest()):
                raise ValueError
            data = json.loads(base64.urlsafe_b64decode(raw))
            key = identifier(data["request_key"])
        except (ValueError, KeyError, TypeError):
            raise MetaError("发送审批凭证无效") from None
        hashed = digest(data)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT hash,result FROM requests WHERE key=?", (key,)).fetchone()
            if prior:
                if prior[0] != hashed:
                    raise MetaError("发送幂等键与内容不一致")
                return json.loads(prior[1])
            a = self.read(data["account_id"])
            if data["expires_at"] <= time.time() or a.get("version") != data["version"]:
                raise MetaError("审批或账号授权已变化，请重新预览")
            if not a.get("verified") or not a.get("sending_enabled"):
                raise MetaError("账号未连接或发送已暂停")
            attempts = db.execute(
                "SELECT count(*) FROM requests WHERE account=? AND claimed>?", (data["account_id"], time.time() - 86400)
            ).fetchone()[0]
            if attempts >= a.get("daily_limit", 20):
                raise MetaError("账号滚动 24 小时发送尝试限额已达到")
            db.execute(
                "INSERT INTO requests (key,hash,result,account,claimed) VALUES (?,?,?,?,?)",
                (key, hashed, json.dumps({"status": "unknown"}), data["account_id"], time.time()),
            )
        payload = {"recipient": {"id": data["recipient_id"]}, "message": {"text": data["text"]}}
        if a["platform"] == "facebook":
            payload["messaging_type"] = "RESPONSE"
        # Graph Send API has no generally supported application request-key deduplication.
        # Ledger is committed before this one external POST; crashes leave unknown.
        try:
            result = self.graph(a, "POST", a["sender_id"] + "/messages", payload)
            mid = result.get("message_id")
            outcome = {"status": "sent", "message_id": mid, "sent_at": time.time()} if mid else {"status": "unknown"}
        except MetaError as exc:
            definitive = str(exc).startswith(("平台拒绝", "授权失效"))
            outcome = {"status": "failed" if definitive else "unknown", "reason": str(exc)}
            if str(exc).startswith("授权失效"):
                self.disconnect(data["account_id"])
        with self.db() as db:
            db.execute("UPDATE requests SET result=? WHERE key=?", (json.dumps(outcome), key))
        return outcome

    def request_status(self, key: str) -> dict:
        with self.db() as db:
            row = db.execute("SELECT result FROM requests WHERE key=?", (identifier(key),)).fetchone()
        return json.loads(row[0]) if row else {"status": "unknown", "reason": "服务没有可确认的发送结果"}

    @serialized
    def manual_reconcile(self, key: str, result: dict) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result FROM requests WHERE key=?", (identifier(key),)).fetchone()
            if row and json.loads(row[0]).get("status") != "unknown":
                raise MetaError("已有明确发送结果，不能人工覆盖")
            if not row:
                raise MetaError("服务没有该发送请求；请检查执行日志后再处理")
            value = {**result, "source": "manual_verification"}
            db.execute("UPDATE requests SET result=? WHERE key=?", (json.dumps(value), key))
        return value

    def webhook_challenge(self, token: str, challenge: str) -> str:
        expected = self.read("app").get("verify_token")
        if not expected or not hmac.compare_digest(expected, token):
            raise MetaError("Webhook 验证失败")
        return challenge

    def webhook(self, raw: bytes, signature: str) -> list[dict]:
        secret = self.read("app").get("app_secret")
        if not secret or not hmac.compare_digest(
            "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), signature
        ):
            raise MetaError("Webhook 签名无效")
        try:
            data = json.loads(raw)
            platform = {"page": "facebook", "instagram": "instagram"}.get(data.get("object"))
            if not platform:
                return []
            events = []
            for entry in data.get("entry", []):
                for item in entry.get("messaging", []):
                    msg = item.get("message") or {}
                    if (
                        msg.get("is_echo")
                        or not msg.get("mid")
                        or str(item.get("recipient", {}).get("id")) != str(entry["id"])
                    ):
                        continue
                    ts = int(item.get("timestamp", 0)) / 1000
                    if ts <= 0 or ts > time.time() + 300:
                        continue
                    events.append(
                        {
                            "platform": platform,
                            "sender_id": str(entry["id"]),
                            "recipient_id": str(item["sender"]["id"]),
                            "message_id": str(msg["mid"]),
                            "occurred_at": ts,
                            "text": str(msg.get("text") or "")[:2000],
                        }
                    )
            return events
        except (ValueError, KeyError, TypeError):
            raise MetaError("Webhook 格式无效") from None

    @serialized
    def oauth_start(self, key: str, account: dict, binding: str) -> dict:
        app = self.read("app")
        if not app.get("app_secret"):
            raise MetaError("请先配置 Meta 应用")
        if account["auth_mode"] != "facebook_login":
            raise MetaError("首期 Instagram Login 使用已有 Token 导入；浏览器授权采用 Facebook Login")
        identifier(account["sender_id"])
        if account["platform"] == "instagram" and not account.get("page_id"):
            raise MetaError("Instagram Facebook Login 需填写关联 Page ID")
        if not binding:
            raise MetaError("授权会话缺失")
        old = self.read(key)
        state = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("DELETE FROM states WHERE account=?", (key,))
            db.execute("DELETE FROM states WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT INTO states (key,account,expires,candidate,binding,base_version) VALUES (?,?,?,?,?,?)",
                (state, key, time.time() + 600, json.dumps(account), binding, old.get("version")),
            )
        scopes = "pages_show_list,pages_messaging,pages_manage_metadata"
        if account["platform"] == "instagram":
            scopes = "pages_show_list,pages_manage_metadata,instagram_basic,instagram_manage_messages"
        return {
            "url": "https://www.facebook.com/"
            + app["version"]
            + "/dialog/oauth?"
            + urlencode(
                {
                    "client_id": app["app_id"],
                    "redirect_uri": app["redirect_uri"],
                    "state": state,
                    "response_type": "code",
                    "scope": scopes,
                }
            )
        }

    @serialized
    def oauth_finish(self, state: str, code: str, binding: str) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT account,expires,candidate,binding,base_version FROM states WHERE key=?", (state,)
            ).fetchone()
            if row and (not binding or not row[3] or not hmac.compare_digest(row[3], binding)):
                raise MetaError("授权会话不匹配")
            db.execute("DELETE FROM states WHERE key=?", (state,))
        if not row or row[1] <= time.time():
            raise MetaError("OAuth 状态已过期或已使用")
        key = row[0]
        app = self.read("app")
        if self.read(key).get("version") != row[4]:
            raise MetaError("账号已变化，请重新授权")
        a = {
            **json.loads(row[2]),
            "sending_enabled": False,
            "verified": False,
            "daily_limit": self.read(key).get("daily_limit", 20),
        }
        try:
            with httpx.Client(timeout=30, trust_env=True) as client:
                response = client.post(
                    "https://graph.facebook.com/" + app["version"] + "/oauth/access_token",
                    data={
                        "client_id": app["app_id"],
                        "client_secret": app["app_secret"],
                        "redirect_uri": app["redirect_uri"],
                        "code": code,
                    },
                )
                result = response.json()
                if not response.is_success or not result.get("access_token"):
                    raise MetaError("OAuth 交换失败，请核对应用与回调地址")
            user = {"auth_mode": "facebook_login", "token": result["access_token"]}
            page = a["sender_id"] if a["platform"] == "facebook" else a["page_id"]
            result = self.graph(user, "GET", identifier(page) + "?fields=id,access_token")
            a.update(token=result["access_token"], version=secrets.token_hex(16))
            identity = self.verify_identity(a)
            a.update(verified=True, name=identity.get("name") or identity.get("username"))
            self.write(key, a)
            return {"account_id": key, **self.account_status(key)}
        except (httpx.HTTPError, KeyError, ValueError):
            raise MetaError("OAuth 授权未完成，请重新连接并检查应用权限") from None
