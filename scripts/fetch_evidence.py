#!/usr/bin/env python3
"""抓取单个 URL 并落盘为受控证据：<out_dir>/<fhrsid>/<n>_<slug>.<ext> + 同名 .meta.json。

记录 URL、最终 URL、状态码、Content-Type、抓取时间（UTC ISO 8601）、sha256、字节数、脚本版本。
只用标准库；失败也写 meta（status/error），不抛异常。
用法：python3 scripts/fetch_evidence.py --fhrsid 416314 --out data/evidence <url> [<url> ...]
"""
import argparse, hashlib, json, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_VERSION = "0.3"
UA = "Mozilla/5.0 (Macintosh) BeaconResearch/0.1 (+research use; contact via site form)"

def slug(u: str) -> str:
    s = re.sub(r"^https?://", "", u).strip("/")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:80] or "root"

def ext_for(ct: str, url: str) -> str:
    ct = (ct or "").split(";")[0].strip().lower()
    if ct == "application/pdf" or url.lower().endswith(".pdf"): return "pdf"
    if ct.startswith("image/"): return ct.split("/")[1].replace("jpeg", "jpg")
    if "html" in ct: return "html"
    if "json" in ct: return "json"
    return "bin"

def fetch(url: str, timeout: int = 30, ua: str = UA):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return dict(status=r.status, final_url=r.geturl(), content_type=r.headers.get("Content-Type"), body=body, error=None, seconds=round(time.time()-t0, 2))
    except urllib.error.HTTPError as e:
        return dict(status=e.code, final_url=e.geturl(), content_type=e.headers.get("Content-Type") if e.headers else None, body=e.read() if e.fp else b"", error=str(e), seconds=round(time.time()-t0, 2))
    except Exception as e:
        return dict(status=None, final_url=None, content_type=None, body=b"", error=repr(e), seconds=round(time.time()-t0, 2))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fhrsid", required=True)
    ap.add_argument("--out", default="data/evidence")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--ua", default=UA, help="User-Agent；记录进 meta，默认标识研究用途")
    ap.add_argument("urls", nargs="+")
    a = ap.parse_args()
    d = Path(a.out) / a.fhrsid; d.mkdir(parents=True, exist_ok=True)
    existing = len(list(d.glob("*.meta.json")))
    for i, url in enumerate(a.urls, existing + 1):
        r = fetch(url, a.timeout, a.ua)
        ext = ext_for(r["content_type"], r["final_url"] or url)
        base = d / f"{i:02d}_{slug(url)}"
        body_path = Path(str(base) + "." + ext)
        if r["body"]:
            body_path.write_bytes(r["body"])
        meta = dict(url=url, final_url=r["final_url"], status=r["status"], content_type=r["content_type"],
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), bytes=len(r["body"]),
                    sha256=hashlib.sha256(r["body"]).hexdigest() if r["body"] else None, error=r["error"],
                    seconds=r["seconds"], user_agent=a.ua, python=sys.version.split()[0], file=str(body_path) if r["body"] else None, script_version=SCRIPT_VERSION)
        Path(str(base) + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        print(f"{a.fhrsid} {r['status']} {ext:4} {len(r['body']):>8}B {r['seconds']:>5}s {url} {('ERR '+r['error']) if r['error'] else ''}")
        time.sleep(1.0)  # 同域名 ≤1 rps
if __name__ == "__main__":
    sys.exit(main())
