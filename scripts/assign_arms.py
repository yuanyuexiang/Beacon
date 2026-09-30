"""为一个批次生成真人计时工作表。

默认模式（--single-arm）：全部线索进工具组，只生成 <prefix>_tool_worksheet.csv（D33：不做纯人工对照）。
可选对照模式（--split）：按 Overture 是否补到官网分层，随机分成纯人工组 A 与工具辅助组 B，另生成
  <prefix>_arms.csv（分组表，人工组完成前不要打开）与 <prefix>_human_worksheet.csv（只含 FSA 字段）。

用法：python3 scripts/assign_arms.py data/records/v2_leads_snapshot.json --seed 20261002 --prefix data/records/v2 [--split]
输入为 GET /api/leads?batch_key=… 的 JSON。
"""
import argparse, csv, hashlib, json, random, sys

HUMAN_COLS = [
    "operator", "experience", "started_at", "finished_at",
    "screen_decision", "screen_reason", "minutes_screen",
    "website_url", "website_how", "minutes_website",
    "menu_url", "menu_format", "menu_result", "minutes_menu",
    "issues_found", "issue_evidence", "minutes_issues",
    "minutes_total", "notes",
]
TOOL_COLS = [
    "operator", "experience", "started_at", "finished_at",
    "minutes_screen_review", "minutes_website", "minutes_menu_attach",
    "minutes_analysis_review", "minutes_corrections", "retries",
    "issues_confirmed", "minutes_total", "notes",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("leads_json")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--prefix", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--single-arm", action="store_true", default=True, help="全部进工具组（默认）")
    g.add_argument("--split", action="store_true", help="分层随机分成 A/B 两组（可选对照）")
    a = ap.parse_args()
    raw = open(a.leads_json, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    leads = sorted(json.loads(raw), key=lambda l: l["source_key"])
    strata = {True: [], False: []}
    for l in leads:
        strata[bool(l.get("website"))].append(l)
    rng = random.Random(a.seed)
    arms: dict[str, str] = {}
    for has_site, group in strata.items():
        rng.shuffle(group)
        for i, l in enumerate(group):
            arms[l["id"]] = ("A" if i % 2 == 0 else "B") if a.split else "B"

    if a.split:
        with open(f"{a.prefix}_arms.csv", "w", newline="", encoding="utf-8") as f:
          w = csv.writer(f)
          w.writerow(["lead_id", "source_key", "name", "arm", "stratum_overture_website", "seed", "input_sha256"])
          for l in leads:
              w.writerow([l["id"], l["source_key"], l["name"], arms[l["id"]], int(bool(l.get("website"))), a.seed, sha])
        with open(f"{a.prefix}_human_worksheet.csv", "w", newline="", encoding="utf-8") as f:
          w = csv.writer(f)
          w.writerow(["order", "source_key", "name", "address", "postcode", *HUMAN_COLS])
          n = 0
          for l in leads:
              if arms[l["id"]] != "A":
                  continue
              n += 1
              w.writerow([n, l["source_key"], l["name"], l.get("address") or "", l.get("postcode") or "", *[""] * len(HUMAN_COLS)])

    with open(f"{a.prefix}_tool_worksheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order", "lead_id", "source_key", "name", "workbench_path", "input_sha256", *TOOL_COLS])
        n = 0
        for l in leads:
            if arms[l["id"]] != "B":
                continue
            n += 1
            w.writerow([n, l["id"], l["source_key"], l["name"], f"/leads/{l['id']}", sha, *[""] * len(TOOL_COLS)])

    a_n = sum(1 for v in arms.values() if v == "A")
    print(f"leads={len(leads)} A={a_n} B={len(leads)-a_n} strata(website yes/no)={len(strata[True])}/{len(strata[False])} seed={a.seed} sha256={sha[:12]}")


if __name__ == "__main__":
    sys.exit(main())
