"""官网 HTML 短期证据缓存；不缓存 Google API、错误、菜单文件或带凭证 URL。"""

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.integrations import fetcher

TTL = 3600
MAX_ENTRIES = 500


def fetch(url: str, **kwargs) -> fetcher.FetchResult:
    settings = get_settings()
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise fetcher.FetchBlocked("不接受含凭证的 URL")
    # 测试 transport 不读写真实缓存；仅复用公开网页无查询参数请求。
    if kwargs.get("transport") is not None or parsed.query:
        return fetcher.fetch(url, **kwargs)
    fetcher.check_url(url, resolve=kwargs.get("resolve_check", True))
    directory = settings.data_dir / "page-cache"
    key = hashlib.sha256(url.encode()).hexdigest()
    path = directory / f"{key}.json"
    now = time.time()
    try:
        cached = json.loads(path.read_text())
        body = cached["body"].encode("latin1")
        if (
            0 <= now - cached["fetched_at"] < TTL
            and cached["url"] == url
            and len(body) <= kwargs["max_bytes"]
            and hashlib.sha256(body).hexdigest() == cached["sha256"]
        ):
            fetcher.check_url(cached["final_url"], resolve=kwargs.get("resolve_check", True))
            return fetcher.FetchResult(
                **{k: cached[k] for k in ("url", "final_url", "status", "content_type", "kind")}, body=body
            )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = fetcher.fetch(url, **kwargs)
    if result.status == 200 and result.kind == "html" and len(result.body) <= 2 * 1024 * 1024:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            entries = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
            for entry in entries:
                if now - entry.stat().st_mtime >= TTL or len(entries) >= MAX_ENTRIES:
                    entry.unlink(missing_ok=True)
                    if len(entries) >= MAX_ENTRIES:
                        entries = entries[1:]
            record = {
                **asdict(result),
                "body": result.body.decode("latin1"),
                "fetched_at": now,
                "sha256": hashlib.sha256(result.body).hexdigest(),
            }
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            with temporary.open("x") as handle:
                os.chmod(temporary, 0o600)
                json.dump(record, handle)
            temporary.replace(path)
        except OSError:
            pass  # 缓存不可写不能使有效网页读取失败。
    return result
