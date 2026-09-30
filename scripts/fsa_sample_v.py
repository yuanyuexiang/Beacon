#!/usr/bin/env python3
"""V 阶段抽样：从同一原始 JSON 的池中排除已用过的 FHRSID（T1 探索集），用新种子抽 N 家，并标记冻结验收集（每 5 家取 1，20%）。
用法：python3 scripts/fsa_sample_v.py <raw.json> --exclude data/records/t1_candidates_60.csv --seed 20261001 --n 50 --out data/records/v_candidates.csv
"""
import argparse, csv, hashlib, json, random, sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw"); ap.add_argument("--exclude", required=True); ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=50); ap.add_argument("--holdout-every", type=int, default=5); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    raw = Path(a.raw).read_bytes(); sha = hashlib.sha256(raw).hexdigest(); d = json.loads(raw)
    used = {r["fhrsid"] for r in csv.DictReader(open(a.exclude, encoding="utf-8"))}
    pool = [e for e in d["establishments"] if e["BusinessTypeID"] == 1 and e["RatingValue"] != "AwaitingInspection" and str(e["FHRSID"]) not in used]
    pool.sort(key=lambda e: e["FHRSID"])
    picks = random.Random(a.seed).sample(pool, min(a.n, len(pool)))
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_order", "fhrsid", "name", "address", "postcode", "rating", "lat", "lng", "holdout", "raw_sha256", "extract_date", "seed", "pool_size", "excluded_count"])
        for i, e in enumerate(picks, 1):
            addr = ", ".join(x for x in (e.get("AddressLine1"), e.get("AddressLine2"), e.get("AddressLine3"), e.get("AddressLine4")) if x)
            g = e.get("geocode") or {}
            w.writerow([i, e["FHRSID"], e["BusinessName"], addr, e.get("PostCode"), e["RatingValue"], g.get("latitude"), g.get("longitude"),
                        "yes" if i % a.holdout_every == 0 else "no", sha, d["meta"]["extractDate"], a.seed, len(pool), len(used)])
    print(f"pool={len(pool)} (excluded {len(used)}) picked={len(picks)} holdout={sum(1 for i in range(1,len(picks)+1) if i % a.holdout_every == 0)} seed={a.seed}")
    print(f"written {out}")

if __name__ == "__main__":
    sys.exit(main())
