"""名单流水线：持久化检查点；请求一次推进一步，关闭页面后可接续。

专用连接的 advisory lock 跨业务 commit 保持，进程退出自动释放。
FSA 写入和检查点同一事务，避免追加时崩溃重抽。联系方式沿用同一个 BatchRun。
"""

import re
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.orm.attributes import set_committed_value

from app.core.models_base import Base, Timestamped, UUIDPk
from app.integrations.ai_runtime import revision as ai_revision
from app.integrations.ai_runtime import workflow_scope
from app.modules.directory import service as directory
from app.modules.leads import policy, runs, service
from app.modules.leads.models import Batch


class Workflow(UUIDPk, Timestamped, Base):
    __tablename__ = "list_workflow"
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps: Mapped[list] = mapped_column(JSONB, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    contact_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch_run.id", ondelete="SET NULL")
    )
    history_scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by: Mapped[str] = mapped_column(String(64), nullable=False)


class WorkflowIn(BaseModel):
    kind: Literal["create", "enrich", "append"] = "enrich"
    phase: Literal["sync", "review"] = "sync"
    lead_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=5000)
    authority_id: int | None = Field(default=None, gt=0)
    authority_name: str | None = None
    business_type_ids: list[Literal[1, 7843, 7844]] = Field(default=[1], min_length=1, max_length=3)
    sample_n: int | None = Field(default=None, ge=1, le=5000)
    exclude_awaiting: bool = False


class WorkflowOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    kind: str
    status: str
    step: int
    steps: list[str]
    params: dict
    results: list[dict]
    error: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


def latest(db: Session, batch: Batch) -> Workflow | None:
    return db.scalar(
        select(Workflow)
        .where(Workflow.batch_id == batch.id, Workflow.kind != "single")
        .order_by(Workflow.created_at.desc(), Workflow.id.desc())
        .limit(1)
    )


@contextmanager
def lock(db: Session, batch: Batch):
    # 独立连接，防止 service 内 commit 意外释放锁。
    key = int.from_bytes(batch.id.bytes[:8], "big", signed=True)
    engine = db.get_bind()
    with engine.connect() as connection:  # type: ignore[union-attr]
        if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
            raise HTTPException(409, "这份名单正在处理，请稍后查看进度")
        try:
            db.expire_all()
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            connection.commit()


def ensure_no_single(db: Session, batch: Batch) -> None:
    from app.modules.leads.models import BatchLead

    members = select(BatchLead.lead_id).where(BatchLead.batch_id == batch.id)
    singles = db.scalars(
        select(Workflow).where(Workflow.kind == "single", Workflow.status.in_(["pending", "running"]))
    ).all()
    identities = {str(x) for x in db.scalars(members)}
    if any(identities.intersection(t.params.get("lead_ids", [])) for t in singles):
        raise HTTPException(409, "名单中的门店正在单家完善，请完成或结束该任务后再开始批量处理")


def ensure_idle(db: Session, batch: Batch) -> None:
    ensure_no_single(db, batch)
    task = latest(db, batch)
    if task and task.status in {"pending", "running"}:
        raise HTTPException(409, "名单有未完成任务，请先继续任务，或结束任务后再操作")


def start(db: Session, batch: Batch, body: WorkflowIn, by: str) -> Workflow:
    ensure_idle(db, batch)
    if body.kind != "enrich":
        if body.authority_id is None or not batch.region or body.authority_name != batch.region:
            raise HTTPException(422, "追加或获取商户必须使用名单所属地区；其他地区请建立新名单")
        if body.kind == "create" and (batch.candidate_count or 0):
            raise HTTPException(409, "名单已有商户，请使用追加商户")
        previous = db.scalar(
            select(Workflow)
            .where(Workflow.batch_id == batch.id, Workflow.kind.in_(["create", "append"]))
            .order_by(Workflow.created_at.desc())
            .limit(1)
        )
        # 已记录地区 ID 的名单，不允许客户端另选一个同名地区。
        authority = previous.params.get("authority_id") if previous else None
        if authority is None:
            match = re.search(r"localAuthorityId=(\d+)", batch.sampling_method or "")
            authority = int(match.group(1)) if match else None
        if authority is not None and authority != body.authority_id:
            raise HTTPException(422, "地区与已保存任务不一致")
    if body.kind != "enrich":
        if batch.country != "GB":
            raise HTTPException(422, "FSA 门店池仅支持英国名单")
        assert body.authority_id is not None
        region = directory.require_pool(db, body.authority_id, list(body.business_type_ids))
        if region.name != batch.region:
            raise HTTPException(422, "门店池地区与名单不一致")
    previous_task = latest(db, batch)
    if previous_task and previous_task.status == "failed":
        # 开始新任务时归档旧失败任务，保留成果和错误，避免旧任务后来重入。
        previous_task.status = "cancelled"
    params = body.model_dump(exclude={"kind"}) if body.kind != "enrich" else {}
    if body.kind != "enrich":
        params["seed"] = None
        params["selection"] = "ordered"
        params["source"] = "directory"
    if body.lead_ids is not None:
        members = {x.id for x in service.list_leads(db, batch.id, None, None, 0)}
        if body.kind != "enrich" or body.phase != "review" or not set(body.lead_ids) <= members:
            raise HTTPException(422, "Selected stores must belong to this review list")
        params["lead_ids"] = [str(x) for x in dict.fromkeys(body.lead_ids)]
    if body.kind == "enrich":
        scope_ids = params.get("lead_ids") or [str(x.id) for x in service.list_leads(db, batch.id, None, None, 0)]
        params["history_scope"] = {
            "kind": "selected" if body.lead_ids else "batch",
            "count": len(scope_ids),
            "lead_ids": scope_ids,
        }
    params["ai_revision"] = ai_revision(db)
    params["phase"] = body.phase if body.kind == "enrich" else "sync"
    params["policy"] = policy.current(db).model_dump()
    task = Workflow(
        batch_id=batch.id,
        kind=body.kind,
        steps=(
            ["google", "screen", "contacts"]
            if params["phase"] == "review"
            else (["pool"] if body.kind != "enrich" else []) + ["overture", "google_sync"]
        ),
        params={k: v for k, v in params.items() if k != "history_scope"},
        history_scope=params.get("history_scope"),
        results=[],
        started_by=by,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def cancelled(db: Session, task_id: uuid.UUID) -> bool:
    with db.no_autoflush:
        return db.scalar(select(Workflow.status).where(Workflow.id == task_id)) == "cancelled"


def save_progress(db: Session, task: Workflow) -> None:
    """条件更新防止晚到的执行结果覆盖并发取消；业务结果照常提交。"""
    fields = {key: getattr(task, key) for key in ("status", "error", "step", "results", "history_scope")}
    if task.status in {"completed", "failed"}:
        fields["finished_at"] = datetime.now(UTC)
    for key, value in fields.items():
        set_committed_value(task, key, value)
    with db.no_autoflush:
        db.execute(
            update(Workflow).where(Workflow.id == task.id, Workflow.status != "cancelled").values(**fields),
            execution_options={"synchronize_session": False},
        )
    db.commit()
    db.refresh(task)


@workflow_scope
def advance(db: Session, batch: Batch, task: Workflow) -> Workflow:
    if task.status in {"completed", "cancelled"}:
        return task
    retry = task.status == "failed" or task.params.get("retry_requested", False)
    if task.params.get("retry_requested"):
        task.params = {**task.params, "retry_requested": False}
    task.status, task.error = "running", None
    save_progress(db, task)
    if task.status == "cancelled":
        return task
    stage = task.steps[task.step]
    try:
        if stage == "pool":
            p = task.params
            result = directory.add_to_batch(
                db,
                batch,
                p["authority_id"],
                p["business_type_ids"],
                p["exclude_awaiting"],
                p["sample_n"],
                task.started_by,
            )
        elif stage == "fsa":
            p = task.params
            result = service.sync_fsa(
                db,
                batch,
                p["authority_id"],
                business_type_ids=p["business_type_ids"],
                exclude_awaiting=p["exclude_awaiting"],
                sample_n=p["sample_n"],
                seed=p["seed"],
                random_sample=p.get("selection") != "ordered",
                operator=task.started_by,
                only_new=True,
                commit=False,
            )
        elif stage == "overture":
            try:
                result = service.enrich_overture(db, batch)
            except Exception:
                if task.params.get("phase") != "sync":
                    raise
                db.rollback()
                result = {"note": "Overture 补充未完成，已有资料保留；继续 Google 补充，可稍后再次同步"}
        elif stage == "google_sync":
            from app.modules.leads import source_sync

            result = source_sync.advance(db, batch, task)
            if not result["done"]:
                task.results = task.results[: task.step] + [result]
                task.status = "pending"
                save_progress(db, task)
                return task
        elif stage == "google":
            from app.modules.leads import places_enrichment

            result = places_enrichment.advance(db, batch, task)
            if not result["done"]:
                task.results = task.results[: task.step] + [result]
                task.status = "pending"
                save_progress(db, task)
                return task
        elif stage == "screen":
            result = service.auto_screen(
                db, batch, policy_data=task.params.get("policy"), lead_ids=task.params.get("lead_ids")
            )
        else:
            if task.contact_run_id is None:
                run = runs.BatchRun(
                    batch_id=batch.id,
                    steps=["contacts"],
                    status=runs.RunStatus.running,
                    started_by=task.started_by,
                    started_at=datetime.now(UTC),
                )
                db.add(run)
                db.flush()
                task.contact_run_id = run.id
                save_progress(db, task)
            saved_run = db.get(runs.BatchRun, task.contact_run_id)
            assert saved_run is not None
            run = saved_run
            # 取得名单锁后，该 task 的 running job 已没有其他执行者，可恢复崩溃中的 job。
            for job in db.scalars(select(runs.BatchJob).where(runs.BatchJob.run_id == run.id)).all():
                if job.status == runs.JobStatus.running or (retry and job.status == runs.JobStatus.failed):
                    job.status, job.error = runs.JobStatus.pending, None
            save_progress(db, task)
            runs.plan_jobs(db, run, batch, lead_ids=task.params.get("lead_ids"))
            runs.execute(db, run, max_jobs=20, should_stop=lambda: cancelled(db, task.id))
            result = {"totals": run.totals, "run_id": str(run.id)}
            if (run.totals or {}).get("pending"):
                task.status = "pending"
                task.results = task.results[: task.step] + [result]
                save_progress(db, task)
                return task
            if (run.totals or {}).get("failed"):
                task.results = task.results[: task.step] + [result]
                save_progress(db, task)
                counts = run.totals or {}
                raise ValueError(
                    f"部分读取 {counts.get('read_partial', 0)} 家，读取失败 {counts.get('read_failed', 0)} 家；"
                    "成功结果已保留，可以继续使用名单，或只重试未完成项"
                )
        if cancelled(db, task.id):
            db.refresh(task)
            return task
        if not task.history_scope and task.steps[task.step] in {"pool", "fsa"}:
            ids = [str(x.id) for x in service.list_leads(db, batch.id, None, None, 0)]
            task.history_scope = {"kind": "batch", "count": len(ids), "lead_ids": ids}
        task.results = task.results[: task.step] + [result]
        task.step += 1
        task.status = "completed" if task.step == len(task.steps) else "pending"
        save_progress(db, task)
    except Exception as exc:
        db.rollback()
        db.refresh(task)
        task.status, task.error = "failed", str(exc)[:2000]
        save_progress(db, task)
    db.refresh(task)
    return task
