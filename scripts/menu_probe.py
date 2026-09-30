#!/usr/bin/env python3
"""对受控证据目录中的菜单文件做确定性测量，输出 JSON（不做主观判断，供人工解释）。

PDF：页数、页面尺寸(pt)、文本字符数、字号分布(最小/中位/最大, 以字符为单位)、按 375px 手机宽度缩放后的等效字号、
     价格 token 统计（£前缀 / 裸数字 / 小数位一致性）、内嵌图片数、是否疑似扫描件（文本极少且有整页图）。
HTML：可见文本字符数、价格 token 统计、是否含 PDF/图片菜单链接。
图片：像素尺寸；文字内容需视觉模型或人工，本脚本只记录“需要视觉处理”。
用法：uv run --python 3.12 --no-project --with pdfplumber scripts/menu_probe.py data/evidence --out data/records/menu_probe.json
"""
import argparse, json, re, statistics, sys, html as html_mod
from pathlib import Path

PRICE_POUND = re.compile(r"£\s?(\d{1,3}(?:\.\d{1,2})?)")
PRICE_BARE_LINE_END = re.compile(r"(?:^|\s)(\d{1,3}(?:\.\d{2})?)\s*$", re.M)
PHONE_WIDTH_PX = 375.0

def price_stats(text: str):
    pound = PRICE_POUND.findall(text)
    bare = PRICE_BARE_LINE_END.findall(text)
    allp = pound + bare
    dec = {"two_decimals": sum(1 for p in allp if re.fullmatch(r"\d+\.\d{2}", p)), "no_decimals": sum(1 for p in allp if re.fullmatch(r"\d+", p)), "one_decimal": sum(1 for p in allp if re.fullmatch(r"\d+\.\d", p))}
    return {"pound_prefixed": len(pound), "bare_line_end_numbers": len(bare), "decimal_formats": dec,
            "mixed_prefix": bool(pound and bare), "mixed_decimals": sum(1 for v in dec.values() if v) > 1}

def probe_pdf(path: Path):
    import pdfplumber
    out = {"kind": "pdf", "pages": 0, "page_sizes_pt": [], "text_chars": 0, "font_sizes": None, "phone_equiv_font_px": None, "images": 0, "likely_scanned": False}
    sizes, text_all = [], []
    with pdfplumber.open(str(path)) as pdf:
        out["pages"] = len(pdf.pages)
        for p in pdf.pages:
            out["page_sizes_pt"].append([round(p.width), round(p.height)])
            out["images"] += len(p.images)
            chars = [c for c in p.chars if c.get("text", "").strip()]
            sizes += [round(float(c["size"]), 1) for c in chars]
            text_all.append(p.extract_text() or "")
    text = "\n".join(text_all); out["text_chars"] = len(text)
    if sizes:
        s = sorted(sizes); med = statistics.median(s)
        out["font_sizes"] = {"min": s[0], "p10": s[len(s)//10], "median": med, "max": s[-1], "chars_measured": len(s)}
        w = out["page_sizes_pt"][0][0]
        scale = PHONE_WIDTH_PX / w  # 整页适配手机宽度时的缩放
        out["phone_equiv_font_px"] = {"scale": round(scale, 3), "median_px": round(med * scale, 1), "p10_px": round(s[len(s)//10] * scale, 1), "note": "整页缩放到 375px 宽时的等效字号；<9px 通常难以阅读，需人工确认"}
    out["likely_scanned"] = out["text_chars"] < 50 * out["pages"] and out["images"] >= out["pages"]
    out["prices"] = price_stats(text)
    out["text_preview"] = text[:300]
    return out

def probe_html(path: Path):
    s = path.read_text(errors="ignore")
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", s, flags=re.S)
    t = html_mod.unescape(re.sub(r"<[^>]+>", "\n", t)); t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n\s*\n+", "\n", t)
    return {"kind": "html", "text_chars": len(t.strip()), "pdf_links": sorted(set(re.findall(r'href="([^"]*\.pdf[^"]*)"', s)))[:10],
            "menu_links": sorted(set(l for l in re.findall(r'href="([^"]+)"', s) if re.search(r"menu|carte", l, re.I) and "parastorage" not in l))[:10],
            "prices": price_stats(t), "text_preview": t.strip()[:300]}

def probe_image(path: Path):
    import struct
    out = {"kind": "image", "bytes": path.stat().st_size, "note": "文字内容需视觉模型或人工读取；此处仅记录尺寸"}
    try:
        import subprocess
        r = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], capture_output=True, text=True)
        m = re.findall(r"pixel(Width|Height): (\d+)", r.stdout); out["pixels"] = {k.lower(): int(v) for k, v in m}
    except Exception as e:
        out["pixels_error"] = repr(e)
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("evidence_dir"); ap.add_argument("--out", required=True); a = ap.parse_args()
    results = []
    for meta_path in sorted(Path(a.evidence_dir).glob("*/*.meta.json")):
        meta = json.loads(meta_path.read_text())
        f = meta.get("file")
        if not f or meta.get("status") != 200: 
            results.append({"fhrsid": meta_path.parent.name, "url": meta["url"], "status": meta.get("status"), "error": meta.get("error"), "kind": "fetch_failed"}); continue
        p = Path(f); ext = p.suffix.lower()
        if ext == ".pdf": r = probe_pdf(p)
        elif ext == ".html": r = probe_html(p)
        elif ext in (".png", ".jpg", ".jpeg", ".webp"): r = probe_image(p)
        else: r = {"kind": "unknown"}
        r.update({"fhrsid": meta_path.parent.name, "url": meta["url"], "file": f, "sha256": meta["sha256"], "fetched_at": meta["fetched_at"]})
        results.append(r)
    Path(a.out).write_text(json.dumps(results, ensure_ascii=False, indent=1))
    for r in results:
        line = f"{r['fhrsid']:8} {r['kind']:12} {r.get('url','')[:70]}"
        if r["kind"] == "pdf": line += f"\n           pages={r['pages']} size={r['page_sizes_pt'][0]} chars={r['text_chars']} fonts={r['font_sizes'] and {k:r['font_sizes'][k] for k in ('min','p10','median','max')}} phone={r['phone_equiv_font_px'] and (r['phone_equiv_font_px']['median_px'], r['phone_equiv_font_px']['p10_px'])} prices={r['prices']}"
        if r["kind"] == "html": line += f"\n           chars={r['text_chars']} pdf_links={len(r['pdf_links'])} prices={r['prices']}"
        if r["kind"] == "image": line += f"\n           {r.get('pixels')}"
        if r["kind"] == "fetch_failed": line += f"  status={r['status']} {r['error']}"
        print(line)
    print(f"\nwritten {a.out} ({len(results)} entries)")
if __name__ == "__main__": sys.exit(main())
