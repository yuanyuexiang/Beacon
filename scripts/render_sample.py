#!/usr/bin/env python3
"""用 templates/partial_menu.html 渲染一个菜单分区的局部样稿（手机宽度 375px），输出 HTML 与 PNG。

输入 JSON：{"restaurant","section","source","items":[{"name","price_text","desc"?}]}
渲染用本机 Google Chrome 无头模式（无需额外依赖）；没有 Chrome 时只输出 HTML。菜名与价格原样填入，不做改写。
用法：python3 scripts/render_sample.py sample.json --out data/records/sample_<id>
"""
import argparse, html, json, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--out", required=True); ap.add_argument("--height", type=int, default=0); a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text()); tpl = Path("templates/partial_menu.html").read_text()
    rows = []
    for it in spec["items"]:
        rows.append(f'<div class="item"><span class="name">{html.escape(it["name"])}</span><span class="dots"></span><span class="price">{html.escape(it["price_text"])}</span>'
                    + (f'<p class="desc">{html.escape(it["desc"])}</p>' if it.get("desc") else "") + "</div>")
    page = tpl
    for k, v in {"restaurant": spec["restaurant"], "section": spec["section"], "source": spec.get("source", ""), "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "items": "\n".join(rows)}.items():
        page = page.replace("{{" + k + "}}", v if k == "items" else html.escape(v))
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    (out.with_suffix(".html")).write_text(page)
    h = a.height or (140 + 52 * len(spec["items"]))
    if Path(CHROME).exists():
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size=375,{h}", f"--screenshot={out.with_suffix('.png')}", f"file://{out.with_suffix('.html').resolve()}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("png:", out.with_suffix(".png"), "rc", r.returncode, (r.stderr.strip().splitlines() or [""])[-1][:120])
    else:
        print("Chrome not found; html only")
    print("html:", out.with_suffix(".html"))
if __name__ == "__main__": sys.exit(main())
