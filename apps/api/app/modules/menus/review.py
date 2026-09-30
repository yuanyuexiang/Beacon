"""D6：人工修正与审核。修正生成新版本（parent_version 指向来源），原版本不变；每处修正记录旧值/新值。
问题确认：confirmed=true 必须有证据；无问题也可完成审核。"""

import copy
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.menus.models import AnalysisCorrection, AnalysisStatus, MenuAnalysis

PATH_RE = re.compile(r"^(items|issues)\[(\d+)\]\.([a-zA-Z_]+)$")
NEW_RE = re.compile(r"^(items|issues)\[new\]$")
ALLOWED_ITEM_FIELDS = {"name", "price_text", "price", "currency_symbol", "decimals", "deleted"}
ALLOWED_ISSUE_FIELDS = {"confirmed", "note", "fact", "fact_zh", "deleted"}


class CorrectionError(ValueError):
    pass


def _get(doc: list, idx: int, field: str) -> Any:
    if idx >= len(doc):
        raise CorrectionError(f"索引越界：{idx}")
    return doc[idx].get(field)


def apply_corrections(db: Session, base: MenuAnalysis, corrections: list[dict], by: str) -> MenuAnalysis:
    if not corrections:
        raise CorrectionError("没有修正内容")
    items = copy.deepcopy(base.items or [])
    issues = copy.deepcopy(base.issues or [])
    now = datetime.now(UTC)
    rows: list[AnalysisCorrection] = []
    for c in corrections:
        mn = NEW_RE.match(c.get("field_path", ""))
        if mn:
            new = c.get("new_value")
            if not isinstance(new, dict):
                raise CorrectionError("新增条目必须是对象")
            if mn.group(1) == "issues":
                if not new.get("issue_code") or not new.get("fact") or not new.get("evidence"):
                    raise CorrectionError("新增问题必须包含 issue_code、fact 与 evidence（位置证据）")
                issues.append(
                    {
                        "issue_code": str(new["issue_code"]),
                        "fact": str(new["fact"]),
                        "fact_zh": new.get("fact_zh"),
                        "evidence": new["evidence"],
                        "severity": new.get("severity", "candidate"),
                        "confirmed": True,
                        "confirmed_by": by,
                        "confirmed_at": now.isoformat(),
                        "note": c.get("reason"),
                        "added_by_human": True,
                    }
                )
            else:
                mm = re.fullmatch(r"(£|€|\$)?\s?(\d{1,3}(?:\.\d{1,2})?)", str(new.get("price_text", "")).strip())
                if not new.get("name") or not mm:
                    raise CorrectionError("新增菜品必须包含 name 与可识别的 price_text")
                items.append(
                    {
                        "name": str(new["name"]),
                        "price_text": mm.group(0),
                        "price": float(mm.group(2)),
                        "currency_symbol": mm.group(1),
                        "decimals": len(mm.group(2).split(".")[1]) if "." in mm.group(2) else 0,
                        "evidence": new.get("evidence") or {"source": "human"},
                        "added_by_human": True,
                    }
                )
            rows.append(
                AnalysisCorrection(
                    field_path=c["field_path"],
                    old_value=None,
                    new_value=new,
                    reason=c.get("reason"),
                    corrected_by=by,
                    corrected_at=now,
                )
            )
            continue
        m = PATH_RE.match(c.get("field_path", ""))
        if not m:
            raise CorrectionError(f"不支持的字段路径：{c.get('field_path')}")
        coll, idx, field = m.group(1), int(m.group(2)), m.group(3)
        doc = items if coll == "items" else issues
        allowed = ALLOWED_ITEM_FIELDS if coll == "items" else ALLOWED_ISSUE_FIELDS
        if field not in allowed:
            raise CorrectionError(f"字段不可修改：{coll}.{field}")
        old = _get(doc, idx, field)
        new = c.get("new_value")
        if coll == "issues" and field == "confirmed":
            if new is True and not doc[idx].get("evidence"):
                raise CorrectionError(f"issues[{idx}] 没有证据位置，不能确认为事实")
            doc[idx]["confirmed_by"] = by if new is not None else None
            doc[idx]["confirmed_at"] = now.isoformat() if new is not None else None
        if coll == "items" and field == "price_text" and isinstance(new, str):
            mm = re.fullmatch(r"(£|€|\$)?\s?(\d{1,3}(?:\.\d{1,2})?)", new.strip())
            if not mm:
                raise CorrectionError(f"价格格式无法识别：{new}")
            doc[idx]["price"] = float(mm.group(2))
            doc[idx]["currency_symbol"] = mm.group(1)
            doc[idx]["decimals"] = len(mm.group(2).split(".")[1]) if "." in mm.group(2) else 0
        doc[idx][field] = new
        doc[idx].setdefault("corrections", []).append(
            {"field": field, "old": old, "new": new, "by": by, "at": now.isoformat()}
        )
        rows.append(
            AnalysisCorrection(
                field_path=c["field_path"],
                old_value=old,
                new_value=new,
                reason=c.get("reason"),
                corrected_by=by,
                corrected_at=now,
            )
        )
    new_version = MenuAnalysis(
        asset_id=base.asset_id,
        version=base.version + 1,
        parent_version=base.version,
        status=AnalysisStatus.succeeded if base.status != AnalysisStatus.failed else AnalysisStatus.needs_review,
        engine="human",
        engine_version=f"{base.engine}:{base.engine_version}",
        items=items,
        measurements=base.measurements,
        issues=issues,
        input_sha256=base.input_sha256,
    )
    db.add(new_version)
    db.flush()
    for r in rows:
        r.analysis_id = new_version.id
        db.add(r)
    db.commit()
    db.refresh(new_version)
    return new_version


def complete_review(db: Session, a: MenuAnalysis, by: str) -> MenuAnalysis:
    if a.status == AnalysisStatus.failed:
        raise CorrectionError("失败的分析不能标记为已审核")
    for i, iss in enumerate(a.issues or []):
        if iss.get("confirmed") is True and not iss.get("evidence"):
            raise CorrectionError(f"issues[{i}] 已确认但没有证据")
    a.review_state = "reviewed"
    a.reviewed_by = by
    a.reviewed_at = datetime.now(UTC)
    if a.status == AnalysisStatus.needs_review:
        a.status = AnalysisStatus.succeeded
    db.commit()
    db.refresh(a)
    return a


def confirmed_issues(a: MenuAnalysis) -> list[dict]:
    return [i for i in (a.issues or []) if i.get("confirmed") is True and not i.get("deleted")]


def active_items(a: MenuAnalysis) -> list[dict]:
    return [i for i in (a.items or []) if not i.get("deleted")]
