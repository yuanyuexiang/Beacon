"""显式运行真实模型的固定回复评估；不写业务数据、不发送消息。
运行：cd apps/api && uv run python ../../scripts/evaluate_reply_ai.py
输出受控 data_dir/evaluations/ 下；这些合成案例不代表真实客户准确率。
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.core.config import get_settings
from app.integrations.research_judge import ResearchJudge
from app.modules.sales.assistance import REPLY_SYSTEM, ReplyAdvice


def main():
    cases = json.loads((ROOT / "apps/api/tests/fixtures/ai-evaluation/replies.json").read_text())
    judge = ResearchJudge()
    rows = []
    for case in cases:
        try:
            result = judge._judge({}, [{"id": "reply", "text": case["text"]}], ReplyAdvice, REPLY_SYSTEM)
            rows.append({"id": case["id"], "expected": case["intent"], "actual": result.intent,
                         "correct": case["intent"] == result.intent, "citations_valid": True})
        except Exception as exc:
            rows.append({"id": case["id"], "correct": False, "error_type": type(exc).__name__})
    report = {"model": judge.model, "cases": rows, "correct": sum(r["correct"] for r in rows),
              "total": len(rows), "usage": judge.usage, "scope": "synthetic fixtures, not customer accuracy"}
    directory = get_settings().data_dir / "evaluations"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"reply-{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"{report['correct']}/{report['total']}；报告：{output}")


if __name__ == "__main__":
    main()
