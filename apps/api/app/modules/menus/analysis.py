"""规则分析引擎：确定性测量与提取，不做主观判断。

PDF：按字符坐标分栏 → 逐行组装 → 匹配“名称 + 价格”；测量页面尺寸、字号分布、手机等效字号；判断是否无文本。
HTML：可见文本逐行匹配价格。图片：不提取，标记需人工/视觉处理。
每个 item 与 issue 都带证据位置（page/column/line/bbox 或行号），供人工核对。
"""

import re
import statistics
from dataclasses import dataclass, field
from io import BytesIO

RULES_VERSION = "0.5"
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


MULTI_SEP = re.compile(r"\s+/\s+|\s+\|\s+|\s+•\s+")


def _parse_line(text: str, evidence: dict) -> list[dict]:
    text = text.strip()
    if not text or len(text) > 200:
        return []
    # 一行多价："Bacon 3.9 / Smoked Salmon 3.9" → 按分隔符拆成多段，每段都以价格结尾时逐段解析
    parts = MULTI_SEP.split(text)
    if len(parts) >= 2 and all(LINE_END.match(p.strip()) for p in parts):
        out: list[dict] = []
        for k, part in enumerate(parts):
            out += _parse_line(part, {**evidence, "segment": k + 1})
        return out
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


GAP_SPLIT_PT = 14.0  # 同一行内词间距超过该值视为另一段（多栏/并排菜品）


def _lines_in_column(words: list[dict], col: tuple[float, float]) -> list[dict]:
    """把栏内的词按 top 聚成行，再按行内大间距切成段；每段是一个候选“名称 + 价格”行。"""
    ws = [w for w in words if w["x0"] >= col[0] - 1 and w["x0"] < col[1]]
    ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
    rows: list[list[dict]] = []
    for w in ws:
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= 3:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines: list[dict] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        seg: dict | None = None
        for w in row:
            if seg is not None and w["x0"] - seg["x1"] > GAP_SPLIT_PT:
                lines.append(seg)
                seg = None
            if seg is None:
                seg = {"text": w["text"], "top": w["top"], "x0": w["x0"], "x1": w["x1"], "bottom": w["bottom"]}
            else:
                seg["text"] += " " + w["text"]
                seg["x1"] = max(seg["x1"], w["x1"])
                seg["bottom"] = max(seg["bottom"], w["bottom"])
        if seg is not None:
            lines.append(seg)
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
                    f"When the full page is scaled to a {int(PHONE_WIDTH_PX)}px-wide phone screen, the body text "
                    f"measures about {med * scale:.1f}px (page width {page_sizes[0][0]}pt, body text {med}pt)",
                    {"page": 1, "measure": "phone_equiv_px.median"},
                    "candidate",
                    fact_zh=f"整页缩放到 {int(PHONE_WIDTH_PX)}px 宽时，正文中位字号约 {med * scale:.1f}px"
                    f"（页面宽 {page_sizes[0][0]}pt，正文 {med}pt）",
                )
            )
    if text_chars < 50 * max(len(page_sizes), 1):
        res.status = "needs_review"
        res.issues.append(
            _issue(
                "pdf_no_text",
                f"The PDF contains only {text_chars} characters of extractable text; "
                "it is likely a scanned or image-only PDF",
                {"page": 1},
                "blocking",
                fact_zh=f"PDF 可提取文本仅 {text_chars} 字符，疑为扫描件或图片 PDF，需要人工或视觉处理",
            )
        )
    res.issues += _price_issues(res.items)
    if not res.items and res.status == "succeeded":
        res.status = "needs_review"
        res.note = "未提取到任何“名称 + 价格”行，需人工检查"
    return res


# ---------- HTML ----------


def analyze_html(data: bytes, base_url: str | None = None) -> RulesResult:
    from app.modules.menus import html_extract

    res = RulesResult()
    s = data.decode("utf-8", errors="ignore")
    ex = html_extract.extract(s, base_url)
    res.items = ex["items"]
    res.measurements = {
        "kind": "html",
        "text_chars": ex["text_chars"],
        "leaves": ex["leaves"],
        "generator": ex["generator"],
        "pdf_links": ex["pdf_links"],
        "image_candidates": ex["image_candidates"],
        "iframes": ex["iframes"],
    }
    res.issues += _price_issues(res.items)
    if not res.items:
        res.status = "needs_review"
        hints = []
        if ex["pdf_links"]:
            hints.append(f"{len(ex['pdf_links'])} PDF link(s)")
        if ex["image_candidates"]:
            hints.append(f"{len(ex['image_candidates'])} image candidate(s)")
        if ex["iframes"]:
            hints.append(f"{len(ex['iframes'])} iframe(s)")
        res.note = "页面正文未提取到菜品价格行；候选：" + (
            "、".join(hints) if hints else "无（可能为前端渲染、图片或年龄门）"
        )
        res.issues.append(
            _issue(
                "menu_not_in_html",
                "The menu is not present as text on this page; candidates: " + (", ".join(hints) or "none found"),
                {"pdf_links": ex["pdf_links"][:5], "image_candidates": [i["src"] for i in ex["image_candidates"][:5]]},
                "info",
                fact_zh=res.note,
            )
        )
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


def _issue(code: str, fact: str, evidence: dict, severity: str, fact_zh: str | None = None) -> dict:
    """fact 为英文事实（进入对外文案）；fact_zh 供操作者阅读。"""
    return {
        "issue_code": code,
        "fact": fact,
        "fact_zh": fact_zh,
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
                "Prices are written with inconsistent decimal places: "
                + ", ".join(f"{len(v)} price(s) with {k} decimal(s)" for k, v in sorted(decs.items()))
                + f"; e.g. {', '.join(ex)}",
                {"examples": [v[0]["evidence"] for v in decs.values()]},
                "candidate",
                fact_zh=f"价格小数位写法混用：{', '.join(f'{k}位×{len(v)}' for k, v in sorted(decs.items()))}"
                f"；例：{'、'.join(ex)}",
            )
        )
    if len(syms) > 1:
        ex = [f"{v[0]['price_text']}({_loc(v[0])})" for v in syms.values()]
        out.append(
            _issue(
                "price_format_mixed_symbol",
                "Currency symbols are used inconsistently: "
                + ", ".join(f"{len(v)} price(s) with '{k}'" for k, v in syms.items())
                + f"; e.g. {', '.join(ex)}",
                {"examples": [v[0]["evidence"] for v in syms.values()]},
                "candidate",
                fact_zh=f"货币符号不一致：{', '.join(f'{k}×{len(v)}' for k, v in syms.items())}；例：{'、'.join(ex)}",
            )
        )
    return out


def _loc(it: dict) -> str:
    e = it["evidence"]
    return f"p{e['page']} c{e['column']} l{e['line']}" if "page" in e else f"l{e['line']}"


def analyze(kind: str, data: bytes, base_url: str | None = None) -> RulesResult:
    if kind == "pdf":
        return analyze_pdf(data)
    if kind == "html":
        return analyze_html(data, base_url)
    if kind == "image":
        return analyze_image(data)
    return RulesResult(status="needs_review", note=f"不支持的类型：{kind}")


def html_visible_text(data: bytes) -> str:
    """供模型转录用的可见文本（去脚本/样式/标签）。"""
    import html as html_mod

    s = data.decode("utf-8", errors="ignore")
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", s, flags=re.S | re.I)
    t = html_mod.unescape(re.sub(r"<[^>]+>", "\n", t))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", t)).strip()
