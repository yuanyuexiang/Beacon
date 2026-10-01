"""从餐厅官网找公开的联系方式：邮箱、电话、WhatsApp、社媒账号、联系表单。
只做规则匹配并给出所在页面；页面里也可能是建站公司、订位平台等第三方的联系方式，是否属于门店由人工确认。
找到联系方式不等于允许使用：渠道准入另行逐条核对。"""

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from app.integrations import website_entity

# 联系页优先，其次关于/订位，再到法律页
PAGE_PRIORITY = ["contact", "find-us", "find us", "visit", "about", "book", "reserv", "privacy", "terms"]
MAX_CONTACTS = 40

EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+\-]*@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
ASSET_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
# 模板占位或平台自身的地址，不是门店邮箱
IGNORED_EMAIL_DOMAINS = {
    "example.com",
    "domain.com",
    "email.com",
    "yourdomain.com",
    "mysite.com",
    "sentry.io",
    "wixpress.com",
    "sentry.wixpress.com",
    "squarespace.com",
    "godaddy.com",
}
FREE_MAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "hotmail.co.uk",
    "outlook.com",
    "live.co.uk",
    "live.com",
    "yahoo.com",
    "yahoo.co.uk",
    "icloud.com",
    "me.com",
    "aol.com",
    "btinternet.com",
}
# 通用职能前缀：指向岗位或门店而非个人
GENERIC_LOCAL = {
    "info",
    "hello",
    "hi",
    "hey",
    "contact",
    "enquiries",
    "enquiry",
    "inquiries",
    "bookings",
    "booking",
    "reservations",
    "reservation",
    "reserve",
    "events",
    "office",
    "admin",
    "sales",
    "team",
    "mail",
    "email",
    "eat",
    "restaurant",
    "kitchen",
    "orders",
    "order",
    "feedback",
    "support",
    "press",
    "marketing",
    "careers",
    "jobs",
    "manager",
    "management",
    "accounts",
    "privatehire",
    "parties",
    "catering",
}
PHONE_TEXT = re.compile(r"(?<![\d+])(?:\+44[\s\-.]?\(?0?\)?[\s\-.]?|\(?0)\d(?:[\s\-.()]{0,2}\d){8,9}(?!\d)")

SOCIAL_HOSTS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "tiktok.com": "tiktok",
    "twitter.com": "x",
    "x.com": "x",
    "linkedin.com": "linkedin",
    "youtube.com": "youtube",
}
# 分享、登录、单条内容等路径不是账号
NOT_ACCOUNT = {
    "instagram": {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "share", "direct"},
    "facebook": {
        "sharer",
        "sharer.php",
        "share",
        "share.php",
        "dialog",
        "tr",
        "plugins",
        "login",
        "login.php",
        "policies",
        "privacy",
        "help",
        "hashtag",
        "watch",
        "events",
        "groups",
    },
    "tiktok": {"share", "tag", "discover", "music"},
    "x": {"intent", "share", "home", "hashtag", "search", "i", "login"},
    "linkedin": {"sharing", "sharearticle", "share", "feed", "login"},
    "youtube": {"watch", "embed", "results", "playlist", "shorts"},
}
CANONICAL = {
    "instagram": "https://www.instagram.com/",
    "facebook": "https://www.facebook.com/",
    "tiktok": "https://www.tiktok.com/",
    "x": "https://x.com/",
    "linkedin": "https://www.linkedin.com/",
    "youtube": "https://www.youtube.com/",
}


def normalize_uk_phone(raw: str) -> str | None:
    """规范为 +44 开头的写法；不像英国号码的返回 None。"""
    d = re.sub(r"[^\d+]", "", raw or "")
    if d.startswith("+44"):
        n = d[3:]
    elif d.startswith("0044"):
        n = d[4:]
    elif d.startswith("44") and len(d) >= 11:
        n = d[2:]
    elif d.startswith("0"):
        n = d[1:]
    else:
        return None
    n = n.lstrip("0")  # +44 (0)20 …
    return f"+44{n}" if len(n) in (9, 10) and n[0] in "12378" else None


def is_personal_email(email: str) -> bool:
    """可能指向个人的邮箱：免费邮箱域名，或前缀不是通用职能词。只是提示，交人工判断。"""
    local, _, domain = email.partition("@")
    if domain in FREE_MAIL_DOMAINS:
        return True
    return not any(t in GENERIC_LOCAL for t in re.split(r"[._\-+\d]+", local) if t)


def _email(raw: str) -> str | None:
    e = unquote(raw).strip().strip(".").lower()
    if not EMAIL.fullmatch(e) or e.endswith(ASSET_SUFFIX):
        return None
    return None if e.partition("@")[2] in IGNORED_EMAIL_DOMAINS else e


def classify_link(href: str, base_url: str = "") -> tuple[str, str] | None:
    """把链接归为联系方式：（类型，规范化的值）。不是联系方式返回 None。"""
    href = (href or "").strip()
    low = href.lower()
    if low.startswith("mailto:"):
        e = _email(href[7:].split("?")[0])
        return ("email", e) if e else None
    if low.startswith("tel:"):
        n = normalize_uk_phone(unquote(href[4:]))
        return ("phone", n) if n else None
    u = urlparse(urljoin(base_url, href))
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    host = u.hostname.lower()
    if host == "wa.me" or (host.endswith("whatsapp.com") and "phone=" in u.query):
        digits = re.sub(r"\D", "", u.path if host == "wa.me" else (parse_qs(u.query).get("phone") or [""])[0])
        number = normalize_uk_phone(digits) or (f"+{digits}" if len(digits) >= 8 else None)
        return ("whatsapp", number) if number else None
    kind = next((k for h, k in SOCIAL_HOSTS.items() if host == h or host.endswith("." + h)), None)
    if kind is None:
        return None
    segs = [s for s in u.path.split("/") if s]
    if not segs or segs[0].lower() in NOT_ACCOUNT[kind]:
        return None
    if kind == "facebook" and segs[0].lower() == "profile.php":
        fid = (parse_qs(u.query).get("id") or [""])[0]
        return ("facebook", f"{CANONICAL[kind]}profile.php?id={fid}") if fid else None
    if kind == "tiktok" and not segs[0].startswith("@"):
        return None
    if kind == "linkedin" and (len(segs) < 2 or segs[0].lower() not in ("company", "in")):
        return None
    if kind == "youtube" and not (segs[0].startswith("@") or segs[0].lower() in ("channel", "c", "user")):
        return None
    # 账号路径：多数平台取第一段；LinkedIn、YouTube 的 channel/c/user、Facebook 的 pages/名称/ID 取到账号为止
    keep = 1
    if kind == "linkedin" or (kind == "youtube" and not segs[0].startswith("@")):
        keep = 2
    elif kind == "facebook" and segs[0].lower() in ("pages", "p", "people"):
        keep = 3
    if len(segs) < keep:
        return None
    return kind, CANONICAL[kind] + "/".join(segs[:keep]).lower()


def extract_contacts(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """一页里的联系方式：先看链接（mailto/tel/社媒），再从正文补邮箱与电话。"""
    found: dict[tuple[str, str], dict[str, Any]] = {}

    def add(kind: str, value: str) -> None:
        found.setdefault((kind, value), {"kind": kind, "value": value, "page_url": doc["url"]})

    for href, _label in doc["links"]:
        hit = classify_link(href, doc.get("base_url") or doc["url"])
        if hit:
            add(*hit)
    for m in EMAIL.finditer(doc["text"]):
        e = _email(m.group(0))
        if e:
            add("email", e)
    for m in PHONE_TEXT.finditer(doc["text"]):
        n = normalize_uk_phone(m.group(0))
        if n:
            add("phone", n)
    if doc.get("has_message_form") and "contact" in urlparse(doc["url"]).path.lower():
        add("contact_form", doc["url"])
    return list(found.values())


def scan(website: str, fetch: Callable[[str], Any]) -> dict[str, Any]:
    """抓首页与同站的联系/关于等页面并提取联系方式；同一联系方式只留首次出现的页面。"""
    pages, docs = website_entity.crawl(website, fetch, PAGE_PRIORITY)
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for doc in docs:
        for c in extract_contacts(doc):
            found.setdefault((c["kind"], c["value"]), c)
    return {"url": website, "pages": pages, "contacts": list(found.values())[:MAX_CONTACTS]}
