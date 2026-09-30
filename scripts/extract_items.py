#!/usr/bin/env python3
"""从文本型菜单 PDF 提取“菜品名 + 价格”候选行，附页码、行号和原文（位置证据）。规则式，不用模型。

识别两种行：`Name 12` / `Name 12.50` / `Name £12.5`（价格在行尾）；`NAME £15 NAME2 £14.5`（一行多价）。
输出 JSON：items[{page,line,raw,name,price_text,price,currency_symbol,decimals}], 及 headings（全大写短行）。
用法：uv run --python 3.12 --no-project --with pdfplumber scripts/extract_items.py <pdf> --out <json>
"""
import argparse, json, re, sys
from pathlib import Path
PRICE = r"(£?)\s?(\d{1,3}(?:\.\d{1,2})?)"
LINE_END = re.compile(rf"^(?P<name>.+?)\s+{PRICE}\s*$")
MULTI = re.compile(rf"(?P<name>[A-Z][A-Z0-9&'’\-\s\(\)]{{2,}}?)\s+{PRICE}(?=\s|$)")

def parse(pdf_path: Path):
    import pdfplumber
    items, headings = [], []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            for lno, raw in enumerate((page.extract_text() or "").split("\n"), 1):
                line = raw.strip()
                if not line: continue
                if len(line) <= 40 and line.upper() == line and not re.search(r"\d", line) and re.search(r"[A-Z]{3,}", line):
                    headings.append({"page": pno, "line": lno, "text": line}); continue
                found = []
                m = LINE_END.match(line)
                if m and len(m.group("name")) >= 3 and not re.search(r"\d\s*$", m.group("name")):
                    found.append((m.group("name"), m.group(2), m.group(3)))
                else:
                    for mm in MULTI.finditer(line):
                        found.append((mm.group("name").strip(), mm.group(2), mm.group(3)))
                for name, sym, num in found:
                    dec = len(num.split(".")[1]) if "." in num else 0
                    items.append({"page": pno, "line": lno, "raw": raw, "name": name.strip(" -–—:"), "price_text": f"{sym}{num}", "price": float(num), "currency_symbol": sym or None, "decimals": dec})
    return items, headings

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("pdf"); ap.add_argument("--out", required=True); a = ap.parse_args()
    items, headings = parse(Path(a.pdf))
    decs = {}
    for it in items: decs[it["decimals"]] = decs.get(it["decimals"], 0) + 1
    syms = {}
    for it in items: syms[it["currency_symbol"] or "none"] = syms.get(it["currency_symbol"] or "none", 0) + 1
    summary = {"source": a.pdf, "items": len(items), "headings": len(headings), "decimal_style_counts": decs, "currency_symbol_counts": syms,
               "inconsistent_decimals": len(decs) > 1, "inconsistent_symbol": len(syms) > 1}
    Path(a.out).write_text(json.dumps({"summary": summary, "headings": headings, "items": items}, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False))
    for it in items[:6]: print(f"  p{it['page']} l{it['line']}: {it['name'][:50]!r} -> {it['price_text']}")
if __name__ == "__main__": sys.exit(main())
