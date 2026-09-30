"""把一个批次的线索分层随机分成纯人工组（A）与工具辅助组（B），生成计时工作表。

用法：python3 scripts/assign_arms.py data/records/v2_leads_snapshot.json --seed 20261002 --prefix data/records/v2

输入为 GET /api/leads?batch_key=… 的 JSON。分层依据：Overture 是否已补到官网（只用于分组平衡，不写入人工工作表）。
输出：
  <prefix>_arms.csv            分组与分层（含 lead_id），人工组操作者在完成前不要打开
  <prefix>_human_worksheet.csv 纯人工组：只含 FSA 字段与空白记录列，不含官网/预筛结果
  <prefix>_tool_worksheet.csv  工具辅助组：lead_id、工作台路径与空白记录列
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
            arms[l["id"]] = "A" if i % 2 == 0 else "B"

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
        w.writerow(["order", "lead_id", "source_key", "name", "workbench_path", *TOOL_COLS])
        n = 0
        for l in leads:
            if arms[l["id"]] != "B":
                continue
            n += 1
            w.writerow([n, l["id"], l["source_key"], l["name"], f"/leads/{l['id']}", *[""] * len(TOOL_COLS)])

    a_n = sum(1 for v in arms.values() if v == "A")
    print(f"leads={len(leads)} A={a_n} B={len(leads)-a_n} strata(website yes/no)={len(strata[True])}/{len(strata[False])} seed={a.seed} sha256={sha[:12]}")


if __name__ == "__main__":
    sys.exit(main())
