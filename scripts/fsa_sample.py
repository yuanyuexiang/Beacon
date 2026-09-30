#!/usr/bin/env python3
"""从 FSA 原始 JSON 抽取技术探索候选，固定种子，可复现。

用法：python3 scripts/fsa_sample.py data/raw/<fsa>.json --seed 20260930 --n 30 --out data/records/t1_candidates.csv
只用标准库。输出含原始文件 sha256、extractDate、筛选表达式，便于复现。
"""
import argparse, csv, hashlib, json, random, sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--exclude-awaiting", action="store_true", help="排除 AwaitingInspection（新登记，官网/菜单常未就绪）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    raw = Path(a.raw).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    d = json.loads(raw)
    meta, es = d["meta"], d["establishments"]
    pool = [e for e in es if e["BusinessTypeID"] == 1]
    filt = "BusinessTypeID==1"
    if a.exclude_awaiting:
        pool = [e for e in pool if e["RatingValue"] != "AwaitingInspection"]
        filt += " and RatingValue!='AwaitingInspection'"
    pool.sort(key=lambda e: e["FHRSID"])  # 抽样前固定顺序
    rnd = random.Random(a.seed)
    picks = rnd.sample(pool, min(a.n, len(pool)))

    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order", "fhrsid", "business_name", "address", "postcode", "rating", "rating_date", "lat", "lng",
                    "raw_sha256", "extract_date", "filter", "seed", "pool_size"])
        for i, e in enumerate(picks, 1):
            addr = ", ".join(x for x in (e.get("AddressLine1"), e.get("AddressLine2"), e.get("AddressLine3"), e.get("AddressLine4")) if x)
            g = e.get("geocode") or {}
            w.writerow([i, e["FHRSID"], e["BusinessName"], addr, e.get("PostCode"), e["RatingValue"], e.get("RatingDate"),
                        g.get("latitude"), g.get("longitude"), sha, meta["extractDate"], filt, a.seed, len(pool)])
    print(f"pool={len(pool)} picked={len(picks)} seed={a.seed} raw_sha256={sha[:16]}… extract={meta['extractDate']}")
    print(f"written {out}")

if __name__ == "__main__":
    sys.exit(main())
