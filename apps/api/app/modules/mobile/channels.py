"""Versioned phone capabilities and canonical destinations; no network or implicit public posting."""

import re
from urllib.parse import parse_qs, urlsplit

PLATFORMS = {
    "whatsapp": {"label": "WhatsApp", "actions": ["direct_message"]},
    "facebook": {"label": "Facebook", "actions": ["direct_message", "message_request"]},
    "instagram": {"label": "Instagram", "actions": ["direct_message", "message_request"]},
    "linkedin": {"label": "LinkedIn", "actions": ["direct_message", "connection_request", "inmail"]},
    "tiktok": {"label": "TikTok", "actions": ["direct_message", "message_request"]},
    "youtube": {"label": "YouTube", "actions": ["direct_message", "contact_discovery"]},
    "x": {"label": "X", "actions": ["direct_message", "message_request"]},
}
DOMAINS = {
    "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com"},
    "instagram": {"instagram.com", "www.instagram.com"},
    "linkedin": {"linkedin.com", "www.linkedin.com"},
    "tiktok": {"tiktok.com", "www.tiktok.com"},
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com"},
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
}


def destination(channel: str, value: str | None) -> tuple[str, str]:
    value = (value or "").strip()
    if channel == "whatsapp":
        number = re.sub(r"[\s()\-]", "", value)
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", number):
            raise ValueError("请填写包含国际区号的 WhatsApp 电话号码")
        return channel, number
    try:
        u = urlsplit(value)
        if u.scheme not in {"http", "https"} or u.username or u.password or u.port not in {None, 80, 443}:
            raise ValueError
        platform = next((p for p, hosts in DOMAINS.items() if u.hostname in hosts), "")
        if not platform or channel not in {platform, "other_social"}:
            raise ValueError
        path = u.path.rstrip("/")
        valid = {
            "facebook": bool(re.fullmatch(r"/[A-Za-z0-9._-]+", path))
            and path.lower() not in {"/watch", "/reel", "/groups", "/share", "/login", "/messages"},
            "instagram": bool(re.fullmatch(r"/[A-Za-z0-9._]+", path))
            and path.lower() not in {"/direct", "/p", "/reels", "/accounts", "/explore"},
            "linkedin": bool(re.fullmatch(r"/(in|company)/[A-Za-z0-9._%-]+", path)),
            "tiktok": bool(re.fullmatch(r"/@[A-Za-z0-9._]+", path)),
            "youtube": bool(
                re.fullmatch(r"/(@[A-Za-z0-9._%-]+|channel/[A-Za-z0-9_-]+|(?:c|user)/[A-Za-z0-9._%-]+)", path)
            ),
            "x": bool(re.fullmatch(r"/[A-Za-z0-9_]+", path))
            and path.lower() not in {"/home", "/messages", "/i", "/search", "/settings", "/intent"},
        }[platform]
        query = ""
        if platform == "facebook" and path == "/profile.php":
            identity = parse_qs(u.query).get("id", [""])[0]
            valid = bool(re.fullmatch(r"[0-9]+", identity))
            query = "?id=" + identity
        if not valid:
            raise ValueError
        host = sorted(DOMAINS[platform], key=lambda h: (h.startswith(("www.", "m.")), len(h)))[0]
        return platform, "https://" + host + path + query
    except (ValueError, StopIteration):
        raise ValueError("请使用该平台完整的个人或门店主页链接，不能使用视频、帖子或短链接") from None
