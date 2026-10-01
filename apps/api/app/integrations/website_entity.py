"""从餐厅官网找公司披露信息：英国公司须在网站列明注册名称与公司编号，通常在页脚、隐私政策或条款页。
只做规则匹配，返回编号/名称及其所在页面与原文片段；是否为经营主体由 Companies House 精确核对后交人工确认。
页面里也可能出现建站公司等第三方的名称与编号，所以命中不等于主体。"""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

MAX_PAGES = 5  # 含首页
MAX_REFS = 8
# 先看最可能披露主体的页面
LINK_PRIORITY = ["privacy", "terms", "legal", "imprint", "policy", "cookie", "about", "contact"]

_NUM = r"(?P<num>(?:SC|NI|OC|SO|NC|LP|SL|NL|FC|BR)\s?\d{6}|\d{7,8})(?!\d)"
NUMBER_PATTERNS = [
    # Company No. 01234567 / Company Registration Number: 1234567 / Registered number SC123456
    re.compile(
        r"(?:compan(?:y|ies\s+house)|\bco\.?|registered|registration|\breg\.?)\s*(?:registration\s*)?"
        r"(?:number|no\.?|num\.?|#)\s*[:.\-]?\s*" + _NUM,
        re.I,
    ),
    # Registered in England and Wales No. 01234567
    re.compile(
        r"registered\s+in\s+(?:england(?:\s*(?:and|&)\s*wales)?|wales|scotland|northern\s+ireland)"
        r"\D{0,60}?" + _NUM,
        re.I,
    ),
]
NOT_COMPANY = re.compile(r"\b(?:vat|charity|ico)\b", re.I)  # 增值税号、慈善登记号、ICO 登记号不是公司编号
# 连续的大写开头词 + Limited/Ltd/LLP/PLC；词内不含句点，避免跨句；后缀前必须是实词（排除 “New In & Limited”）
NAME = re.compile(
    r"(?<![\w&])((?:[A-Z][\w&'’\-]*)(?:\s+(?:[A-Z0-9][\w&'’\-]*|&|and|of|the)){0,6}"
    r"(?<!&)(?<!\sand)(?<!\sof)(?<!\sthe)\s+(?i:limited|ltd|llp|plc))(?![\w])"
)


@dataclass
class Ref:
    kind: str  # number | name
    value: str
    page_url: str
    snippet: str


class _Page(HTMLParser):
    """展平为纯文本并收集链接。页脚不能跳过：公司披露多在页脚。"""

    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.has_message_form = False  # 页面有留言框（联系表单）
        self._skip = 0
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "a":
            self._href, self._label = dict(attrs).get("href"), []
        elif tag == "textarea":
            self.has_message_form = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._label)))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.text.append(data)
        if self._href:
            self._label.append(data)


def parse_page(html: str) -> tuple[str, list[tuple[str, str]]]:
    p = _Page()
    p.feed(html)
    return re.sub(r"\s+", " ", " ".join(p.text)).strip(), p.links


def legal_links(links: list[tuple[str, str]], base_url: str, priority: list[str] | None = None) -> list[str]:
    """同站的隐私/条款/关于/联系页，按 priority 关键词的先后排序，至多 MAX_PAGES-1 个。"""
    priority = priority or LINK_PRIORITY
    host = (urlparse(base_url).hostname or "").removeprefix("www.")
    ranked: dict[str, int] = {}
    for href, label in links:
        url = urldefrag(urljoin(base_url, href)).url
        u = urlparse(url)
        if u.scheme not in ("http", "https") or (u.hostname or "").removeprefix("www.") != host:
            continue
        hay = f"{u.path} {label}".lower()
        rank = next((i for i, k in enumerate(priority) if k in hay), None)
        if rank is not None and url.rstrip("/") != base_url.rstrip("/"):
            ranked[url] = min(rank, ranked.get(url, rank))
    return sorted(ranked, key=lambda x: ranked[x])[: MAX_PAGES - 1]


def _snippet(text: str, start: int, end: int, pad: int = 50) -> str:
    return text[max(0, start - pad) : end + pad].strip()


def extract_refs(text: str, page_url: str) -> list[Ref]:
    out: list[Ref] = []
    for pat in NUMBER_PATTERNS:
        for m in pat.finditer(text):
            if NOT_COMPANY.search(text[max(0, m.start() - 20) : m.end()]):
                continue
            num = re.sub(r"\s", "", m.group("num")).upper().zfill(8)  # 常省略前导 0
            out.append(Ref("number", num, page_url, _snippet(text, m.start(), m.end())))
    for m in NAME.finditer(text):
        out.append(Ref("name", m.group(1).strip(), page_url, _snippet(text, m.start(), m.end())))
    unique: dict[tuple[str, str], Ref] = {}  # 同一编号可被两种写法规则同时命中
    for ref in out:
        unique.setdefault((ref.kind, ref.value), ref)
    return list(unique.values())


def crawl(
    website: str, fetch: Callable[[str], Any], priority: list[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """抓首页与同站的若干相关页（至多 MAX_PAGES）。fetch(url) 返回带 status/kind/body/final_url 的结果，失败抛异常。
    返回（每页抓取结果，成功页面的文本/链接）。任何页面失败都只记录原因，不抛出。"""
    pages: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    queue = [website]
    while queue and len(pages) < MAX_PAGES:
        url = queue.pop(0)
        try:
            r = fetch(url)
            if r.status != 200 or r.kind != "html":
                raise ValueError(f"HTTP {r.status}（{r.kind}）")
        except Exception as e:
            pages.append({"url": url, "ok": False, "error": f"{e.__class__.__name__}: {e}"[:200]})
            continue
        page = _Page()
        page.feed(r.body.decode("utf-8", errors="replace"))
        pages.append({"url": url, "ok": True, "error": None})
        docs.append(
            {
                "url": url,
                "base_url": r.final_url,
                "text": re.sub(r"\s+", " ", " ".join(page.text)).strip(),
                "links": page.links,
                "has_message_form": page.has_message_form,
            }
        )
        if url == website:
            queue += legal_links(page.links, r.final_url, priority)
    return pages, docs


def scan(website: str, fetch: Callable[[str], Any]) -> dict[str, Any]:
    """抓首页与同站的法律/关于页并提取公司披露信息。"""
    pages, docs = crawl(website, fetch)
    refs: dict[tuple[str, str], Ref] = {}
    for doc in docs:
        for ref in extract_refs(doc["text"], doc["url"]):
            refs.setdefault((ref.kind, ref.value.lower()), ref)  # 同一编号/名称只留首次出现的页面
    ordered = sorted(refs.values(), key=lambda x: x.kind != "number")  # 编号比名称可靠，优先保留
    return {"url": website, "pages": pages, "refs": [asdict(x) for x in ordered[:MAX_REFS]]}
