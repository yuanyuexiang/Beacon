"""D4：URL 抓取阻断内网/协议/端口；重定向逐跳检查；超限/超时/404 有原因且可重试；上传按魔数识别；文件落受控目录。"""

from pathlib import Path

import httpx
import pytest

from app.integrations import fetcher
from app.integrations.fetcher import FetchBlocked
from app.modules.menus import service
from tests.test_imports import create_batch, login, upload

FIX = Path(__file__).parent / "fixtures"
CSV = "fhrsid,name\n1,Test Restaurant\n"


def setup_lead(client, db):
    login(client, db)
    create_batch(client, "b1")
    upload(client, "b1", CSV)
    return client.get("/api/leads").json()[0]["id"]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/menu.pdf",
        "http://127.0.0.1/menu",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://[::1]/x",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://intranet/x",
        "http://example.com:5432/x",
    ],
)
def test_check_url_blocks_private_and_bad_targets(url):
    with pytest.raises(FetchBlocked):
        fetcher.check_url(url)


def _transport(handler):
    return httpx.MockTransport(handler)


def test_redirect_to_private_is_blocked(monkeypatch):
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h: h == "example.com")

    def handler(req):
        if req.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=b"%PDF-1.4 secret")

    with pytest.raises(FetchBlocked, match="公网"):
        fetcher.fetch(
            "http://example.com/m.pdf", max_bytes=10_000, timeout=5, user_agent="t", transport=_transport(handler)
        )


def test_size_limit_and_sniff(monkeypatch):
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h: True)
    big = b"%PDF-1.4" + b"x" * 5000
    tr = _transport(lambda req: httpx.Response(200, content=big, headers={"content-type": "application/pdf"}))
    with pytest.raises(FetchBlocked, match="大小上限"):
        fetcher.fetch("http://example.com/m.pdf", max_bytes=1000, timeout=5, user_agent="t", transport=tr)
    r = fetcher.fetch("http://example.com/m.pdf", max_bytes=10_000, timeout=5, user_agent="t", transport=tr)
    assert r.kind == "pdf" and r.status == 200
    assert fetcher.sniff_kind(b"\x89PNG....", None) == "image"
    assert fetcher.sniff_kind(b"<!doctype html><html>", "text/html") == "html"
    assert fetcher.sniff_kind(b"hello", "text/plain") == "unknown"


def test_add_url_records_failure_and_retry(client, db, monkeypatch):
    lead_id = setup_lead(client, db)
    monkeypatch.setattr(fetcher, "_is_public_host", lambda h: True)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(404)
        if calls["n"] == 2:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, content=(FIX / "mini.pdf").read_bytes(), headers={"content-type": "application/pdf"})

    # 直接调用服务层，注入 transport（路由层不暴露 transport）
    asset = service.add_url(
        db, __import__("uuid").UUID(lead_id), "http://example.com/menu.pdf", "tester", transport=_transport(handler)
    )
    assert asset.fetch_status == "failed" and "HTTP 404" in (asset.fetch_error or "") and asset.fetch_attempts == 1
    asset = service.fetch_asset(db, asset, transport=_transport(handler))
    assert asset.fetch_status == "failed" and "超时" in (asset.fetch_error or "") and asset.fetch_attempts == 2
    asset = service.fetch_asset(db, asset, transport=_transport(handler))
    assert asset.fetch_status == "fetched" and asset.kind == "pdf" and asset.sha256 and asset.storage_path
    assert asset.fetch_attempts == 3
    from app.core.files import resolve_within

    assert resolve_within(asset.storage_path).read_bytes().startswith(b"%PDF")
    # 受控下载需登录且可用
    r = client.get(f"/api/files/{asset.storage_path}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_url_endpoint_blocks_private_without_network(client, db):
    lead_id = setup_lead(client, db)
    r = client.post(f"/api/leads/{lead_id}/assets", json={"url": "http://127.0.0.1/menu.pdf"})
    assert r.status_code == 201 and r.json()["fetch_status"] == "failed" and "公网" in r.json()["fetch_error"]
    assets = client.get(f"/api/leads/{lead_id}/assets").json()
    assert len(assets) == 1 and assets[0]["fetch_attempts"] == 1


def test_upload_sniffs_kind_and_rejects_unknown(client, db):
    lead_id = setup_lead(client, db)
    r = client.post(
        f"/api/leads/{lead_id}/assets/upload",
        files={"file": ("m.pdf", (FIX / "mini.pdf").read_bytes(), "application/pdf")},
    )
    assert r.status_code == 201 and r.json()["kind"] == "pdf" and r.json()["fetch_status"] == "fetched"
    r = client.post(
        f"/api/leads/{lead_id}/assets/upload", files={"file": ("m.png", (FIX / "mini.png").read_bytes(), "image/png")}
    )
    assert r.status_code == 201 and r.json()["kind"] == "image"
    r = client.post(f"/api/leads/{lead_id}/assets/upload", files={"file": ("m.txt", b"plain text", "text/plain")})
    assert r.status_code == 400
    aid = client.get(f"/api/leads/{lead_id}/assets").json()[0]["id"]
    assert client.post(f"/api/assets/{aid}/retry").status_code == 400  # 上传件不可重试抓取
