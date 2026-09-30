"""HTML 菜单提取 v2：基于 DOM 的价格—菜名关联，并发现页面中的菜单文件候选（PDF/图片）。

规则：
1. 用标准库 HTMLParser 把文档展平为叶子文本节点序列，每个节点记录标签路径与序号（证据）。
2. 同一叶子内 “名称 … 价格” 直接成对；只含价格的叶子，向前找最近的非价格、非说明性文本作为名称，
   要求二者最近公共祖先距离价格节点不超过 3 层（同一卡片/行）。
3. 一个名称后连续多个价格（如 12"/18"）→ 多价条目，名称相同、evidence 不同。
4. 发现：href 指向 .pdf 的链接、位于 menu 区块或 alt/src 含 menu 的图片、以及大尺寸 CDN 图片。
"""

import contextlib
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

PRICE = re.compile(r"(?P<sym>£|€|\$)?\s?(?P<num>\d{1,3}(?:[.,]\d{1,2})?)")
PRICE_ONLY = re.compile(r"^(?:from\s+)?(?P<sym>£|€|\$)\s?(?P<num>\d{1,3}(?:[.,]\d{1,2})?)\s*(?:each|pp|p/p)?$", re.I)
PRICE_ONLY_BARE = re.compile(r"^(?P<num>\d{1,3}(?:[.,]\d{2}))$")
TRAILING = re.compile(r"^(?P<name>.{2,120}?)[\s\-–—:.·…]+(?P<sym>£|€|\$)?\s?(?P<num>\d{1,3}(?:[.,]\d{1,2})?)\s*$")
LEADING = re.compile(r"^(?P<sym>£|€|\$)\s?(?P<num>\d{1,3}(?:[.,]\d{1,2})?)\s+(?P<name>[A-Za-z].{2,120})$")
SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "head",
    "nav",
    "footer",
    "header",
    "form",
    "button",
    "select",
    "option",
}
BLOCK_TAGS = {
    "div",
    "li",
    "tr",
    "td",
    "p",
    "section",
    "article",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "dt",
    "dd",
    "span",
    "strong",
    "b",
    "em",
    "i",
    "a",
    "font",
}
NOISE = re.compile(
    r"^(subtotal|total|vat|service charge|delivery|minimum order|£0\.00|0\.00"
    r"|book|order|add to cart|menu|home|contact)$",
    re.I,
)
NAME_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "dt", "th"}
VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "track"}


class _Flat(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []  # (tag, node_id)
        self.nid = 0
        self.leaves: list[dict] = []
        self.skip = 0
        self.links: list[str] = []
        self.images: list[dict] = []
        self.iframes: list[str] = []
        self.generator: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("name") or "").lower() == "generator":
            self.generator = a.get("content")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "img":
            self.images.append(
                {
                    "src": a.get("src") or a.get("data-src") or "",
                    "alt": a.get("alt") or "",
                    "path": [t for t, _ in self.stack],
                }
            )
        if tag == "iframe" and a.get("src"):
            self.iframes.append(a["src"])
        if tag in VOID_TAGS:
            return
        if tag in SKIP_TAGS:
            self.skip += 1
        self.nid += 1
        self.stack.append((tag, self.nid))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if self.skip:
            return
        t = re.sub(r"\s+", " ", data.replace("\xa0", " ")).strip()
        if not t:
            return
        self.leaves.append({"text": t, "path": list(self.stack), "idx": len(self.leaves)})


def _norm_num(n: str) -> str:
    return n.replace(",", ".")


def _lca_distance(a: list[tuple[str, int]], b: list[tuple[str, int]]) -> int:
    """价格节点到最近公共祖先的层数。"""
    common = 0
    for x, y in zip(a, b, strict=False):
        if x == y:
            common += 1
        else:
            break
    return len(a) - common


def _item(name: str, sym: str | None, num: str, leaf: dict, extra: dict | None = None) -> dict:
    num = _norm_num(num)
    ev = {"line": leaf["idx"] + 1, "raw": leaf["text"][:200], "tag_path": "/".join(t for t, _ in leaf["path"][-6:])}
    if extra:
        ev.update(extra)
    return {
        "name": name.strip(" -–—:·."),
        "price_text": f"{sym or ''}{num}",
        "price": float(num),
        "currency_symbol": sym,
        "decimals": len(num.split(".")[1]) if "." in num else 0,
        "evidence": ev,
    }


def extract(html: str, base_url: str | None = None) -> dict:
    p = _Flat()
    with contextlib.suppress(Exception):
        p.feed(html)
    leaves = p.leaves
    items: list[dict] = []
    last_name: dict | None = None
    for leaf in leaves:
        t = leaf["text"]
        if NOISE.match(t):
            continue
        m = TRAILING.match(t)
        if m and not re.search(r"\d\s*$", m.group("name")) and len(m.group("name").split()) <= 20:
            items.append(_item(m.group("name"), m.group("sym"), m.group("num"), leaf))
            last_name = None
            continue
        m = LEADING.match(t)
        if m:
            items.append(_item(m.group("name"), m.group("sym"), m.group("num"), leaf))
            last_name = None
            continue
        m = PRICE_ONLY.match(t) or PRICE_ONLY_BARE.match(t)
        if m:
            sym = m.groupdict().get("sym")
            # 向前找名称：最近的非价格文本，且 LCA 距离 ≤ 3
            cand = None
            nearest = None
            for prev in reversed(leaves[max(0, leaf["idx"] - 8) : leaf["idx"]]):
                pt = prev["text"]
                if PRICE_ONLY.match(pt) or PRICE_ONLY_BARE.match(pt) or NOISE.match(pt) or len(pt) < 2 or len(pt) > 120:
                    continue
                if _lca_distance(leaf["path"], prev["path"]) <= 3:
                    if nearest is None:
                        nearest = prev
                    if any(t in NAME_TAGS for t, _ in prev["path"][-3:]):
                        cand = prev  # 同一卡片内优先标题/加粗文本
                        break
            if cand is None:
                cand = nearest
            if cand is None and last_name is not None and _lca_distance(leaf["path"], last_name["path"]) <= 4:
                cand = last_name
            if cand is not None:
                items.append(
                    _item(cand["text"], sym, m.group("num"), leaf, {"name_line": cand["idx"] + 1, "linked": True})
                )
                last_name = cand
            continue
        if 2 <= len(t) <= 120 and not re.search(r"\d{3,}", t):
            last_name = leaf
    # 去重：同名同价同证据行
    seen = set()
    uniq = []
    for it in items:
        k = (it["name"].lower(), it["price_text"], it["evidence"]["line"])
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    # 发现候选文件
    pdfs = sorted({urljoin(base_url or "", h) for h in p.links if re.search(r"\.pdf(\?|$)", h, re.I)})
    imgs = []
    for im in p.images:
        src = im["src"]
        if not src or src.startswith("data:"):
            continue
        blob = (im["alt"] + " " + src + " " + "/".join(im["path"][-4:])).lower()
        if "menu" in blob or "squarespace-cdn.com/content" in src or "/uploads/" in src:
            imgs.append({"src": urljoin(base_url or "", src.split("?")[0]), "alt": im["alt"][:80]})
    seen_src: set[str] = set()
    uniq_imgs = []
    for i in imgs:
        if i["src"] not in seen_src:
            seen_src.add(i["src"])
            uniq_imgs.append(i)
    imgs = uniq_imgs
    text_chars = sum(len(leaf["text"]) for leaf in leaves)
    return {
        "items": uniq,
        "leaves": len(leaves),
        "text_chars": text_chars,
        "generator": p.generator,
        "pdf_links": pdfs[:20],
        "image_candidates": imgs[:20],
        "iframes": p.iframes[:10],
    }
