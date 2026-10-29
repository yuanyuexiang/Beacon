"""只读完善记录；完成时间仅取明确检查点，不用普通更新时间推断。"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.leads.workflows import Workflow


def serialize(task: Workflow) -> dict:
    params = task.params
    scope = task.history_scope or {}
    selected = params.get("lead_ids")
    phase = params.get("phase")
    pending_keys = ("retry", "failed", "remaining", "ai_unavailable", "insufficient", "conflict", "review")
    partial = any(
        isinstance(result.get(key), (int, float)) and result[key] > 0 for result in task.results for key in pending_keys
    ) or any(
        any(result.get("totals", {}).get(key, 0) > 0 for key in ("failed", "read_partial", "read_failed", "ai_pending"))
        for result in task.results
    )
    return {
        "id": str(task.id),
        "phase": phase if phase in ("sync", "review") else "legacy",
        "status": "partial" if task.status == "completed" and partial else task.status,
        "created_at": task.created_at.isoformat(),
        "finished_at": task.finished_at.isoformat()
        if task.finished_at and task.status in ("completed", "failed", "cancelled")
        else None,
        "scope": scope.get("kind", "selected" if selected else "unknown"),
        "scope_count": scope.get("count", len(selected) if selected else None),
        "step": task.step,
        "steps": task.steps,
        "results": task.results,
        "error": task.error,
        "operator": task.started_by,
    }


def history(db: Session, batch_id: uuid.UUID | None = None, lead_id: uuid.UUID | None = None) -> list[dict]:
    query = select(Workflow).where(Workflow.kind != "single")
    if batch_id:
        query = query.where(Workflow.batch_id == batch_id)
    if lead_id:
        key = str(lead_id)
        query = query.where(
            Workflow.history_scope["lead_ids"].contains([key]) | Workflow.params["lead_ids"].contains([key])
        )
    tasks = db.scalars(query.order_by(Workflow.created_at.desc(), Workflow.id.desc()).limit(100)).all()
    return [serialize(task) for task in tasks]
