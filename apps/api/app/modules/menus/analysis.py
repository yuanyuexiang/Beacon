"""规则分析引擎：确定性测量与提取，不做主观判断。

PDF：按字符坐标分栏 → 逐行组装 → 匹配“名称 + 价格”；测量页面尺寸、字号分布、手机等效字号；判断是否无文本。
HTML：可见文本逐行匹配价格。图片：不提取，标记需人工/视觉处理。
每个 item 与 issue 都带证据位置（page/column/line/bbox 或行号），供人工核对。
"""

import html as html_mod
import re
import statistics
from dataclasses import dataclass, field
from io import BytesIO

RULES_VERSION = "0.2"
PHONE_WIDTH_PX = 375.0
SMALL_TEXT_PX = 9.0
PRICE_RE = re.compile(r"(?P<sym>£|€|\$)?\s?(?P<num>\d{1,3}(?:\.\d{1,2})?)")
LINE_END = re.compile(r"^(?P<name>.+?)\s+(?P<sym>£|€|\$)?\s?(?P<num>\d{1,3}(?:\.\d{1,2})?)\s*$")
INLINE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9&'’\-\s\(\),]{2,}?)\s+(?P<sym>£|€|\$)?\s?(?P<num>\d{1,3}(?:\.\d{1,2})?)(?=\s{2,}|\s+[A-Z]|$)"
)


@dataclass
class RulesResult:
    items: list[dict] = field(default_factory=list)
    measurements: dict = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    status: str = "succeeded"  # succeeded / needs_review
    note: str | None = None


def _item(name: str, sym: str | None, num: str, evidence: dict) -> dict:
    return {
        "name": name.strip(" -–—:·."),
        "price_text": f"{sym or ''}{num}",
        "price": float(num),
        "currency_symbol": sym,
        "decimals": len(num.split(".")[1]) if "." in num else 0,
        "evidence": evidence,
    }


def _parse_line(text: str, evidence: dict) -> list[dict]:
    text = text.strip()
    if not text or len(text) > 200:
        return []
    m = LINE_END.match(text)
    if m and len(m.group("name")) >= 2 and not re.search(r"\d\s*$", m.group("name")):
        return [_item(m.group("name"), m.group("sym"), m.group("num"), evidence)]
    found = []
    for mm in INLINE.finditer(text):
        if len(mm.group("name").strip()) >= 3:
            found.append(_item(mm.group("name"), mm.group("sym"), mm.group("num"), {**evidence, "inline": True}))
    return found


# ---------- PDF ----------


def _columns(words: list[dict], page_width: float) -> list[tuple[float, float]]:
    """找出页面上无任何词跨越的竖向空白带，作为分栏边界。返回各栏的 (x0, x1)。"""
    if not words:
        return [(0.0, page_width)]
    step = max(page_width / 200.0, 1.0)
    bins = int(page_width / step) + 1
    occ = [0] * bins
    for w in words:
        a, b = int(w["x0"] / step), min(int(w["x1"] / step), bins - 1)
        for i in range(a, b + 1):
            occ[i] += 1
    min_gap = max(int((0.06 * page_width) / step), 2)
    cols, start, i = [], None, 0
    while i < bins:
        if occ[i] > 0:
            if start is None:
                start = i
            i += 1
            continue
        j = i
        while j < bins and occ[j] == 0:
            j += 1
        if start is not None and (j - i) >= min_gap and j < bins:
            cols.append((start * step, i * step))
            start = None
        i = j
    if start is not None:
        cols.append((start * step, page_width))
    return cols or [(0.0, page_width)]


def _lines_in_column(words: list[dict], col: tuple[float, float]) -> list[dict]:
    ws = [w for w in words if w["x0"] >= col[0] - 1 and w["x0"] < col[1]]
    ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
    lines: list[dict] = []
    for w in ws:
        if lines and abs(w["top"] - lines[-1]["top"]) <= 3:
            ln = lines[-1]
            ln["text"] += " " + w["text"]
            ln["x1"] = max(ln["x1"], w["x1"])
            ln["bottom"] = max(ln["bottom"], w["bottom"])
        else:
            lines.append({"text": w["text"], "top": w["top"], "x0": w["x0"], "x1": w["x1"], "bottom": w["bottom"]})
    return lines


def analyze_pdf(data: bytes) -> RulesResult:
    import pdfplumber

    res = RulesResult()
    sizes: list[float] = []
    page_sizes: list[list[int]] = []
    text_chars = 0
    images = 0
    with pdfplumber.open(BytesIO(data)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            page_sizes.append([round(page.width), round(page.height)])
            images += len(page.images)
            sizes += [round(float(c["size"]), 1) for c in page.chars if c.get("text", "").strip()]
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            text_chars += sum(len(w["text"]) for w in words)
            cols = _columns(words, float(page.width))
            for cno, col in enumerate(cols, 1):
                for lno, ln in enumerate(_lines_in_column(words, col), 1):
                    ev = {
                        "page": pno,
                        "column": cno,
                        "line": lno,
                        "raw": ln["text"],
                        "bbox": [round(ln["x0"], 1), round(ln["top"], 1), round(ln["x1"], 1), round(ln["bottom"], 1)],
                    }
                    res.items += _parse_line(ln["text"], ev)
    res.measurements = {
        "kind": "pdf",
        "pages": len(page_sizes),
        "page_sizes_pt": page_sizes,
        "text_chars": text_chars,
        "images": images,
    }
    if sizes:
        s = sorted(sizes)
        med = statistics.median(s)
        scale = PHONE_WIDTH_PX / page_sizes[0][0]
        res.measurements["font_sizes_pt"] = {
            "min": s[0],
            "p10": s[len(s) // 10],
            "median": med,
            "max": s[-1],
            "chars": len(s),
        }
        res.measurements["phone_equiv_px"] = {
            "scale": round(scale, 3),
            "median": round(med * scale, 1),
            "p10": round(s[len(s) // 10] * scale, 1),
        }
        if med * scale < SMALL_TEXT_PX:
            res.issues.append(
                _issue(
                    "mobile_text_small",
                    f"整页缩放到 {int(PHONE_WIDTH_PX)}px 宽时，正文中位字号约 {med * scale:.1f}px"
                    f"（页面宽 {page_sizes[0][0]}pt，正文 {med}pt）",
                    {"page": 1, "measure": "phone_equiv_px.median"},
                    "candidate",
                )
            )
    if text_chars < 50 * max(len(page_sizes), 1):
        res.status = "needs_review"
        res.issues.append(
            _issue(
                "pdf_no_text",
                f"PDF 可提取文本仅 {text_chars} 字符，疑为扫描件或图片 PDF，需要人工或视觉处理",
                {"page": 1},
                "blocking",
            )
        )
    res.issues += _price_issues(res.items)
    if not res.items and res.status == "succeeded":
        res.status = "needs_review"
        res.note = "未提取到任何“名称 + 价格”行，需人工检查"
    return res


# ---------- HTML ----------


def analyze_html(data: bytes) -> RulesResult:
    res = RulesResult()
    s = data.decode("utf-8", errors="ignore")
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", s, flags=re.S | re.I)
    t = html_mod.unescape(re.sub(r"<[^>]+>", "\n", t))
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.split("\n")]
    lines = [ln for ln in lines if ln]
    for lno, ln in enumerate(lines, 1):
        res.items += _parse_line(ln, {"line": lno, "raw": ln})
    pdf_links = sorted(set(re.findall(r'href="([^"]*\.pdf[^"]*)"', s, flags=re.I)))
    res.measurements = {
        "kind": "html",
        "text_chars": sum(len(x) for x in lines),
        "lines": len(lines),
        "pdf_links": pdf_links[:10],
    }
    res.issues += _price_issues(res.items)
    if not res.items:
        res.status = "needs_review"
        res.note = "页面文本中未提取到菜品价格行；若菜单为 PDF/图片链接，请另行接入该文件"
    return res


# ---------- image ----------


def analyze_image(data: bytes) -> RulesResult:
    res = RulesResult(status="needs_review", note="图片菜单：规则引擎不读取文字，需要视觉模型或人工转录")
    res.measurements = {"kind": "image", "bytes": len(data)}
    res.issues.append(
        _issue("image_only_menu", "菜单以图片形式提供，文字需人工或视觉模型转录后才能核对", {"file": "image"}, "info")
    )
    return res


# ---------- shared ----------


def _issue(code: str, fact: str, evidence: dict, severity: str) -> dict:
    return {
        "issue_code": code,
        "fact": fact,
        "evidence": evidence,
        "severity": severity,
        "confirmed": None,
        "confirmed_by": None,
        "confirmed_at": None,
        "note": None,
    }


def _price_issues(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    if len(items) < 2:
        return out
    decs: dict[int, list[dict]] = {}
    syms: dict[str, list[dict]] = {}
    for it in items:
        decs.setdefault(it["decimals"], []).append(it)
        syms.setdefault(it["currency_symbol"] or "none", []).append(it)
    if len(decs) > 1:
        ex = [f"{v[0]['price_text']}({_loc(v[0])})" for v in decs.values()]
        out.append(
            _issue(
                "price_format_mixed_decimals",
                f"价格小数位写法混用：{', '.join(f'{k}位×{len(v)}' for k, v in sorted(decs.items()))}"
                f"；例：{'、'.join(ex)}",
                {"examples": [v[0]["evidence"] for v in decs.values()]},
                "candidate",
            )
        )
    if len(syms) > 1:
        ex = [f"{v[0]['price_text']}({_loc(v[0])})" for v in syms.values()]
        out.append(
            _issue(
                "price_format_mixed_symbol",
                f"货币符号不一致：{', '.join(f'{k}×{len(v)}' for k, v in syms.items())}；例：{'、'.join(ex)}",
                {"examples": [v[0]["evidence"] for v in syms.values()]},
                "candidate",
            )
        )
    return out


def _loc(it: dict) -> str:
    e = it["evidence"]
    return f"p{e['page']} c{e['column']} l{e['line']}" if "page" in e else f"l{e['line']}"


def analyze(kind: str, data: bytes) -> RulesResult:
    if kind == "pdf":
        return analyze_pdf(data)
    if kind == "html":
        return analyze_html(data)
    if kind == "image":
        return analyze_image(data)
    return RulesResult(status="needs_review", note=f"不支持的类型：{kind}")
