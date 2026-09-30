"""外部 URL 抓取：逐跳阻断本机/内网/链路本地地址，限制重定向次数、大小与超时；按魔数识别类型。
不做任何解析；结果只包含字节与元数据。测试可注入 transport。"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

MAX_REDIRECTS = 5


class FetchBlocked(Exception):
    """策略阻断（非网络错误）：内网地址、协议不允许等。"""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str | None
    body: bytes
    kind: str  # pdf / image / html / unknown


def _literal_private(host: str) -> bool:
    """不查 DNS 的字面量判断：localhost、无点主机名、以及直接写成 IP 的内网/本机地址。"""
    host = host.strip("[]").lower()
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local") or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast


def _is_public_host(host: str, resolve: bool = True) -> bool:
    if _literal_private(host):
        return False
    if not resolve:
        return True
    host = host.strip("[]").lower()
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except socket.gaierror as e:
        raise FetchBlocked(f"域名无法解析：{host}") from e
    for a in addrs:
        ip = ipaddress.ip_address(str(a).split("%")[0])
        if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False
    return True


def check_url(url: str, resolve: bool = True) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise FetchBlocked(f"不允许的协议：{u.scheme or '(空)'}")
    if not u.hostname:
        raise FetchBlocked("URL 缺少主机名")
    if u.port and u.port not in (80, 443, 8080, 8443):
        raise FetchBlocked(f"不允许的端口：{u.port}")
    if not _is_public_host(u.hostname, resolve=resolve):
        raise FetchBlocked(f"目标不是公网地址：{u.hostname}")


def sniff_kind(body: bytes, content_type: str | None) -> str:
    head = body[:16]
    if head.startswith(b"%PDF"):
        return "pdf"
    if (
        head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF"))
        or head[:4] == b"RIFF"
        and body[8:12] == b"WEBP"
    ):
        return "image"
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "application/pdf":
        return "pdf"
    if ct.startswith("image/"):
        return "image"
    low = body[:2048].lower()
    if ct in ("text/html", "application/xhtml+xml") or b"<html" in low or b"<!doctype html" in low:
        return "html"
    return "unknown"


def fetch(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    user_agent: str,
    transport: httpx.BaseTransport | None = None,
    resolve_check: bool = True,
) -> FetchResult:
    check_url(url, resolve_check)
    current = url
    with httpx.Client(
        follow_redirects=False, timeout=timeout, transport=transport, headers={"User-Agent": user_agent}
    ) as c:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current, resolve_check)
            with c.stream("GET", current) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    current = urljoin(current, r.headers["location"])
                    continue
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise FetchBlocked(f"响应超过大小上限 {max_bytes} 字节")
                body = bytes(buf)
                ct = r.headers.get("content-type")
                return FetchResult(
                    url=url,
                    final_url=current,
                    status=r.status_code,
                    content_type=ct,
                    body=body,
                    kind=sniff_kind(body, ct),
                )
    raise FetchBlocked(f"重定向超过 {MAX_REDIRECTS} 次")
