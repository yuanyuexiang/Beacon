"""名单后台调度：数据库检查点恢复，名单 advisory lock 跨 commit 互斥。"""

import logging
import threading

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_sessionmaker
from app.core.models import Operator
from app.modules.leads import workflows
from app.modules.leads.models import Batch


def tick(db: Session) -> bool:
    tasks = db.scalars(
        select(workflows.Workflow)
        .where(
            workflows.Workflow.status.in_(["pending", "running"]),
            workflows.Workflow.params["background"].as_boolean() == True,  # noqa: E712
        )
        .order_by(workflows.Workflow.updated_at, workflows.Workflow.id)
        .limit(20)
    ).all()
    for task in tasks:
        batch = db.get(Batch, task.batch_id)
        if batch is None:
            continue
        try:
            with workflows.lock(db, batch):
                db.refresh(task)
                if task.status not in {"pending", "running"}:
                    continue
                actor = db.scalar(select(Operator).where(Operator.username == task.started_by))
                if not actor or not actor.is_active or actor.role not in {"admin", "director"}:
                    task.status = "failed"
                    task.error = "发起人的管理权限已失效，请由管理员重新继续任务"
                    workflows.save_progress(db, task)
                else:
                    workflows.advance(db, batch, task)
                return True
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            db.rollback()
    return False


def run(stop: threading.Event) -> None:
    while not stop.is_set():
        worked = False
        try:
            with get_sessionmaker()() as db:
                worked = tick(db)
        except Exception:
            # 不打印可能包含网页/凭据的异常内容；检查点在下一轮恢复。
            logging.warning("名单后台调度失败，稍后从检查点恢复")
        stop.wait(1 if worked else 5)
