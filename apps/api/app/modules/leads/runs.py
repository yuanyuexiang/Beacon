"""D10：批次处理运行。每家/每个文件一个 job，独立状态与尝试次数；一条失败不终止整批；
重启后未完成/失败的 job 可续跑；成功的 job 不重复执行（分析层本身幂等）。"""

import enum
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.models_base import Base, Timestamped, UUIDPk
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.menus import analysis as rules
from app.modules.menus import service as menu_service
from app.modules.menus.models import AnalysisStatus, FetchStatus, MenuAsset

STALE_AFTER = timedelta(minutes=30)
STEPS = ("fetch", "analyze", "contacts")


class RunStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    completed_with_failures = "completed_with_failures"


class JobStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, native_enum=False, length=40, values_callable=lambda x: [i.value for i in x])


class BatchRun(UUIDPk, Timestamped, Base):
    __tablename__ = "batch_run"
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch.id", ondelete="CASCADE"), nullable=False
    )
    steps: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus, "run_status"), default=RunStatus.running, nullable=False)
    started_by: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totals: Mapped[dict | None] = mapped_column(JSONB)


class BatchJob(UUIDPk, Base):
    __tablename__ = "batch_job"
    __table_args__ = (UniqueConstraint("run_id", "lead_id", "step", "target_id", name="uq_batch_job"),)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch_run.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # menu_asset.id
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus, "job_status"), default=JobStatus.pending, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # 例如 analysis id
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunError(ValueError):
    pass


def _needs_contact_scan(lead: Lead | None) -> bool:
    """批量查找联系方式的对象：未被筛选排除、有官网或 Overture 数据，且还没成功查过当前这个官网。"""
    if lead is None or lead.screening_class.value.startswith("excluded"):
        return False
    raw = lead.raw or {}
    if not lead.website and not (raw.get("overture") or {}).get("matched"):
        return False
    scan = raw.get("contacts_scan")
    if not scan:
        return True
    # 官网换了、没有读到页面或部分页面失败：允许再次查找，已记录联系方式不会重复新增。
    return scan.get("website") != lead.website or bool(
        lead.website and (not scan.get("pages_ok") or scan.get("pages_failed"))
    )


def plan_jobs(db: Session, run: BatchRun, batch: Batch) -> int:
    """按批次成员规划 job；已有相同 (lead, step, target) 的不重复创建。返回新增数。"""
    existing = {
        (j.lead_id, j.step, j.target_id) for j in db.scalars(select(BatchJob).where(BatchJob.run_id == run.id)).all()
    }
    added = 0
    for m in db.scalars(select(BatchLead).where(BatchLead.batch_id == batch.id)).all():
        if "contacts" in run.steps and _needs_contact_scan(db.get(Lead, m.lead_id)):
            ckey = (m.lead_id, "contacts", None)
            if ckey not in existing:
                db.add(
                    BatchJob(run_id=run.id, lead_id=m.lead_id, step="contacts", status=JobStatus.pending, attempts=0)
                )
                existing.add(ckey)
                added += 1
        assets = db.scalars(select(MenuAsset).where(MenuAsset.lead_id == m.lead_id)).all()
        for a in assets:
            if "fetch" in run.steps and a.source_url and a.fetch_status != FetchStatus.fetched:
                key = (m.lead_id, "fetch", a.id)
                if key not in existing:
                    db.add(
                        BatchJob(
                            run_id=run.id,
                            lead_id=m.lead_id,
                            step="fetch",
                            target_id=a.id,
                            status=JobStatus.pending,
                            attempts=0,
                        )
                    )
                    existing.add(key)
                    added += 1
            if "analyze" in run.steps and a.fetch_status == FetchStatus.fetched:
                latest = menu_service.latest_analysis(db, a.id)
                if (
                    latest is not None
                    and latest.status != AnalysisStatus.failed
                    and latest.input_sha256 == a.sha256
                    and not (latest.engine == "rules" and latest.engine_version != rules.RULES_VERSION)
                ):
                    continue  # 已有当前规则版本的有效结果（人工修正版本也保留）
                key = (m.lead_id, "analyze", a.id)
                if key not in existing:
                    db.add(
                        BatchJob(
                            run_id=run.id,
                            lead_id=m.lead_id,
                            step="analyze",
                            target_id=a.id,
                            status=JobStatus.pending,
                            attempts=0,
                        )
                    )
                    existing.add(key)
                    added += 1
    db.commit()
    return added


def start_run(db: Session, batch: Batch, steps: list[str], by: str) -> BatchRun:
    bad = [s for s in steps if s not in STEPS]
    if bad or not steps:
        raise RunError(f"不支持的步骤：{bad or '(空)'}；可用：{STEPS}")
    run = BatchRun(
        batch_id=batch.id, steps=steps, status=RunStatus.running, started_by=by, started_at=datetime.now(UTC)
    )
    db.add(run)
    db.flush()
    plan_jobs(db, run, batch)
    return run


def resume_run(db: Session, run: BatchRun) -> int:
    """失败或超时仍为 running 的 job 重置为 pending。返回重置数。"""
    n = 0
    stale_before = datetime.now(UTC) - STALE_AFTER
    for j in db.scalars(select(BatchJob).where(BatchJob.run_id == run.id)).all():
        if j.status == JobStatus.failed or (
            j.status == JobStatus.running and (j.started_at is None or j.started_at < stale_before)
        ):
            j.status, j.error = JobStatus.pending, None
            n += 1
    run.status = RunStatus.running
    run.finished_at = None
    db.commit()
    return n


def execute(db: Session, run: BatchRun, max_jobs: int | None = None) -> BatchRun:
    """顺序执行 pending job；抓取完成后重新规划一次，使同一轮里新抓到的文件也得到分析。"""
    _execute_pending(db, run, max_jobs)
    if "analyze" in run.steps and max_jobs is None:
        batch = db.get(Batch, run.batch_id)
        assert batch is not None
        if plan_jobs(db, run, batch):
            _execute_pending(db, run, None)
    return _finalize(db, run)


def _execute_pending(db: Session, run: BatchRun, max_jobs: int | None) -> None:
    pending = db.scalars(
        select(BatchJob)
        .where(BatchJob.run_id == run.id, BatchJob.status == JobStatus.pending)
        .order_by(BatchJob.step, BatchJob.lead_id)
    ).all()
    chunk = pending if max_jobs is None else pending[:max_jobs]
    scans = _prefetch_websites(db, chunk)  # 联系方式步骤：先并行读完这一块的官网，数据库写入仍逐条进行
    for j in chunk:
        j.status, j.started_at, j.attempts = JobStatus.running, datetime.now(UTC), j.attempts + 1
        db.commit()
        try:
            if j.step == "contacts":
                scan = _collect_contacts(db, run, j, scans)
                if scan["pages_failed"]:
                    j.status = JobStatus.failed
                    j.error = f"官网有 {scan['pages_failed']} 个页面抓取失败；已保留成功页面的联系方式，可重试"
                else:
                    j.status, j.error = JobStatus.succeeded, None
                j.finished_at = datetime.now(UTC)
                db.commit()
                continue
            asset = db.get(MenuAsset, j.target_id) if j.target_id else None
            if asset is None:
                raise RunError("目标文件不存在")
            if j.step == "fetch":
                asset = menu_service.fetch_asset(db, asset)
                if asset.fetch_status != FetchStatus.fetched:
                    raise RunError(asset.fetch_error or "抓取失败")
                j.result_id = asset.id
            elif j.step == "analyze":
                a, _ = menu_service.run_analysis(db, asset, engine="rules")
                if a.status == AnalysisStatus.failed:
                    raise RunError(a.error or "分析失败")
                j.result_id = a.id
            j.status, j.error = JobStatus.succeeded, None
        except Exception as e:  # 单个 job 失败不终止整批
            db.rollback()
            j = db.get(BatchJob, j.id)  # type: ignore[assignment]
            assert j is not None
            j.status, j.error = JobStatus.failed, f"{e.__class__.__name__}: {e}"[:2000]
        j.finished_at = datetime.now(UTC)
        db.commit()


def _prefetch_websites(db: Session, jobs: Sequence[BatchJob]) -> dict[str, Any]:
    """并行读取这一块 contacts job 涉及的官网（只有网络访问，在线程里不碰数据库会话）。"""
    urls = []
    for j in jobs:
        lead = db.get(Lead, j.lead_id) if j.step == "contacts" else None
        if lead is not None and lead.website:
            urls.append(lead.website)
    if not urls:
        return {}
    from app.modules.sales import contacts  # 延迟导入：sales 依赖 leads

    return contacts.scan_websites(urls)


def _collect_contacts(db: Session, run: BatchRun, j: BatchJob, scans: dict[str, Any]) -> dict[str, Any]:
    from app.core import audit
    from app.modules.sales import contacts  # 延迟导入：sales 依赖 leads

    lead = db.get(Lead, j.lead_id)
    if lead is None:
        raise RunError("门店不存在")
    website_scan = scans.get(lead.website) if lead.website else None
    if isinstance(website_scan, Exception):
        raise website_scan
    scan = contacts.collect(db, lead, website_scan)
    audit.record(
        db, None, "record_contacts", "lead", lead.id, after={"run_id": str(run.id), "by": run.started_by, **scan}
    )
    return scan


def _finalize(db: Session, run: BatchRun) -> BatchRun:
    jobs = db.scalars(select(BatchJob).where(BatchJob.run_id == run.id)).all()
    totals = {s.value: sum(1 for j in jobs if j.status == s) for s in JobStatus}
    run.totals = totals
    if totals["pending"] or totals["running"]:
        run.status = RunStatus.running
    else:
        run.status = RunStatus.completed_with_failures if totals["failed"] else RunStatus.completed
        run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run
