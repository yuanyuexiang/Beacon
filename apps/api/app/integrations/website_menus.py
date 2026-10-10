"""有界官网菜单发现：候选只读，不下载候选文件，不调用模型。"""

import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit

from app.integrations.fetcher import FetchBlocked, check_url

MENU = re.compile(r"menu|food|drink|wine|cocktail|餐单|菜单", re.IGNORECASE)
IGNORE = re.compile(r"privacy|terms|cookie|allergen|careers", re.IGNORECASE)


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.images: list[tuple[str, str]] = []
        self.href: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a":
            self.href = values.get("href")
            self.label = []
        if tag == "img":
            self.images.append((values.get("src") or values.get("data-src") or "", values.get("alt") or ""))
        if tag == "iframe" and values.get("src"):
            self.links.append((values["src"] or "", "embedded menu"))

    def handle_data(self, data: str) -> None:
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.label).strip()))
            self.href = None


def discover(website: str, fetch: Callable[[str], Any]) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    candidates: dict[str, dict[str, str]] = {}
    queue = [website]
    seen: set[str] = set()
    site_host: str | None = None

    def candidate(url: str, kind: str, label: str, source: str) -> None:
        if len(candidates) < 30:
            candidates.setdefault(url, {"url": url, "kind": kind, "label": label[:150], "source_url": source})

    while queue and len(pages) < 5:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            result = fetch(url)
            if result.status != 200 or result.kind != "html":
                raise ValueError(f"HTTP {result.status} ({result.kind})")
            base = result.final_url
            if site_host is None:
                site_host = (urlsplit(base).hostname or "").removeprefix("www.")
            parser = Page()
            parser.feed(result.body.decode("utf-8", errors="replace"))
            pages.append({"url": url, "final_url": base, "ok": True, "error": None})
            for href, label in parser.links:
                target = urldefrag(urljoin(base, href)).url
                path = urlsplit(target).path
                if not MENU.search(path + " " + label) or IGNORE.search(path + " " + label):
                    continue
                try:
                    check_url(target, resolve=False)
                except (FetchBlocked, ValueError):
                    continue
                if re.search(r"\.pdf$", path, re.IGNORECASE):
                    candidate(target, "pdf", label, base)
                elif re.search(r"\.(png|jpe?g|webp)$", path, re.IGNORECASE):
                    candidate(target, "image", label, base)
                elif (urlsplit(target).hostname or "").removeprefix("www.") == site_host:
                    candidate(target, "html", label, base)
                    if target not in seen and target not in queue:
                        queue.append(target)
            for src, alt in parser.images:
                target = urldefrag(urljoin(base, src)).url
                if not src or not re.search(r"menu|菜单|餐单", src + " " + alt, re.IGNORECASE):
                    continue
                try:
                    check_url(target, resolve=False)
                except (FetchBlocked, ValueError):
                    continue
                candidate(target, "image", alt or "菜单图片", base)
        except Exception as e:
            pages.append({"url": url, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]})
    return {
        "website": website,
        "pages": pages,
        "candidates": sorted(candidates.values(), key=lambda c: {"pdf": 0, "image": 1, "html": 2}[c["kind"]]),
        "notice": (
            "候选尚未核对分店、完整性和日期；PDF 优先，点击原链接核对后再抓取。最多读取 5 个页面，不执行网页脚本。"
        ),
    }
