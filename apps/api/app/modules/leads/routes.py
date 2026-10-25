import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import Operator
from app.modules.leads import runs, service, workflows
from app.modules.leads.models import Batch, BatchLead, Lead, ScreeningClass
from app.modules.leads.schemas import BatchIn, BatchOut, ImportResult, LeadOut, LeadPatch

router = APIRouter(tags=["leads"])


def idle_batch(batch_key: str, db: Session = Depends(get_db)):
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    with workflows.lock(db, batch):
        workflows.ensure_idle(db, batch)
        yield batch


def idle_run(run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = db.get(runs.BatchRun, run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    batch = db.get(Batch, run.batch_id)
    assert batch is not None
    with workflows.lock(db, batch):
        workflows.ensure_idle(db, batch)
        yield run


@router.get("/batches/{batch_key}/workflow", response_model=workflows.WorkflowOut | None)
def get_workflow(batch_key: str, db: Session = Depends(get_db)):
    if db.info.get("member_scope"):
        return None
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    return workflows.latest(db, batch)


@router.post("/batches/{batch_key}/workflow", response_model=workflows.WorkflowOut, status_code=201)
def start_workflow(
    batch_key: str, body: workflows.WorkflowIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    with workflows.lock(db, batch):
        task = workflows.start(db, batch, body, op.username)
        audit.record(
            db, op, "start_list_workflow", "list_workflow", task.id, after={"kind": task.kind, "params": task.params}
        )
        db.commit()
        return task


@router.post("/batches/{batch_key}/workflow/{task_id}/resume", response_model=workflows.WorkflowOut)
def resume_workflow(
    batch_key: str, task_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    batch = service.get_batch_by_key(db, batch_key)
    task = db.get(workflows.Workflow, task_id)
    if batch is None or task is None or task.batch_id != batch.id or task.kind == "single":
        raise HTTPException(404, "任务不存在")
    with workflows.lock(db, batch):
        workflows.ensure_no_single(db, batch)
        db.refresh(task)
        if task.status in {"completed", "cancelled"}:
            return task
        # 失败状态保留到 advance，联系方式阶段才能只重试失败 job。
        task.params = {**task.params, "background": True, "retry_requested": task.status == "failed"}
        if task.status == "failed":
            task.status = "pending"
        task.started_by = op.username
        audit.record(db, op, "resume_list_workflow", "list_workflow", task.id)
        db.commit()
        return task


@router.post("/batches/{batch_key}/workflow/{task_id}/advance", response_model=workflows.WorkflowOut)
def advance_workflow(
    batch_key: str, task_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    batch = service.get_batch_by_key(db, batch_key)
    task = db.get(workflows.Workflow, task_id)
    if batch is None or task is None or task.batch_id != batch.id or task.kind == "single":
        raise HTTPException(404, "任务不存在")
    with workflows.lock(db, batch):
        workflows.ensure_no_single(db, batch)
        result = workflows.advance(db, batch, task)
        audit.record(
            db, op, "advance_list_workflow", "list_workflow", task.id, after={"step": task.step, "status": task.status}
        )
        db.commit()
        return result


@router.post("/batches/{batch_key}/workflow/{task_id}/cancel", response_model=workflows.WorkflowOut)
def cancel_workflow(
    batch_key: str, task_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    batch = service.get_batch_by_key(db, batch_key)
    task = db.get(workflows.Workflow, task_id)
    if batch is None or task is None or task.batch_id != batch.id or task.kind == "single":
        raise HTTPException(404, "任务不存在")
    # 取消不能等待正在进行的外部网络请求所持有的名单锁。
    from sqlalchemy import update

    changed = db.execute(
        update(workflows.Workflow)
        .where(workflows.Workflow.id == task.id, workflows.Workflow.status.notin_(["completed", "cancelled"]))
        .values(status="cancelled", error=None)
        .returning(workflows.Workflow.id),
        execution_options={"synchronize_session": False},
    ).scalar_one_or_none()
    if changed:
        audit.record(db, op, "cancel_list_workflow", "list_workflow", task.id)
    db.commit()
    db.refresh(task)
    return task


class CreateListIn(BatchIn):
    workflow: workflows.WorkflowIn


@router.post("/lists", status_code=201)
def create_list(body: CreateListIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> dict:
    if body.workflow.kind != "create":
        raise HTTPException(422, "建立名单必须使用 create 任务")
    if service.get_batch_by_key(db, body.batch_key):
        raise HTTPException(409, "名单名称已存在")
    batch = Batch(**body.model_dump(exclude={"workflow"}))
    db.add(batch)
    db.flush()
    with workflows.lock(db, batch):
        # 新名单及任务一起落库；校验失败时不会留下空名单。
        audit.record(db, op, "create", "batch", batch.id, after=body.model_dump(exclude={"workflow"}))
        task = workflows.start(db, batch, body.workflow, op.username)
        audit.record(
            db, op, "start_list_workflow", "list_workflow", task.id, after={"kind": task.kind, "params": task.params}
        )
        db.commit()
        return {"batch": BatchOut.model_validate(batch), "workflow": workflows.WorkflowOut.model_validate(task)}


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(body: BatchIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> Batch:
    if service.get_batch_by_key(db, body.batch_key):
        raise HTTPException(status.HTTP_409_CONFLICT, "batch_key 已存在")
    b = Batch(**body.model_dump())
    db.add(b)
    db.flush()
    audit.record(db, op, "create", "batch", b.id, after=body.model_dump())
    db.commit()
    db.refresh(b)
    return b


@router.get("/batches", response_model=list[BatchOut])
def list_batches(db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    query = select(Batch).order_by(Batch.created_at.desc())
    if op.role == "member":
        query = query.where(
            Batch.id.in_(
                select(BatchLead.batch_id)
                .join(Lead, Lead.id == BatchLead.lead_id)
                .where(Lead.assigned_to == op.username)
            )
        )
    rows = list(db.scalars(query).all())
    if op.role == "member":
        return [
            BatchOut.model_validate(b).model_copy(
                update={
                    "candidate_count": db.scalar(
                        select(func.count()).select_from(BatchLead).where(BatchLead.batch_id == b.id)
                    )
                }
            )
            for b in rows
        ]
    return rows


@router.get("/batches/{batch_key}/delete-preview")
def delete_batch_preview(
    batch_key: str, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """删除批次会影响什么：将删除与保留的门店数，以及随门店一起删除的各类记录数。只读。"""
    from app.modules.leads import deletion

    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    return deletion.preview(db, batch)


@router.delete("/batches/{batch_key}", dependencies=[Depends(idle_batch)])
def delete_batch(
    batch_key: str, confirm: str = "", db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """删除批次（不可恢复）。confirm 必须等于批次键。只属于本批次的门店及其全部数据一并删除；
    属于其他批次或有抑制记录的门店保留。"""
    from app.modules.leads import deletion

    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    if confirm != batch_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "confirm 必须等于批次键")
    batch_id = batch.id
    result = deletion.delete_batch(db, batch)
    lead_ids = result.pop("deleted_lead_ids")
    audit.record(db, op, "delete", "batch", batch_id, before=result)
    db.commit()
    result["file_dirs_removed"] = deletion.remove_files(lead_ids)
    return result


def idle_import(batch_key: str = Form(...), db: Session = Depends(get_db)):
    yield from idle_batch(batch_key, db)


@router.post("/imports", response_model=ImportResult, dependencies=[Depends(idle_import)])
async def import_leads(
    batch_key: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> ImportResult:
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    content = await file.read()
    if len(content) > get_settings().max_asset_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过大小上限")
    if not content.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件为空")
    run = service.import_csv(db, batch, content, file.filename, op.username)
    audit.record(
        db,
        op,
        "import",
        "import_run",
        run.id,
        after={"rows": run.row_count, "created": run.created_count, "errors": run.error_count},
    )
    db.commit()
    return ImportResult(
        import_run_id=run.id,
        batch_key=batch.batch_key,
        file_sha256=run.file_sha256,
        row_count=run.row_count,
        created_count=run.created_count,
        linked_count=run.linked_count,
        skipped_count=run.skipped_count,
        error_count=run.error_count,
        errors=run.errors or [],
    )


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    batch_key: str | None = None,
    screening_class: ScreeningClass | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> list[LeadOut]:
    batch_id = None
    if batch_key:
        b = service.get_batch_by_key(db, batch_key)
        if b is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
        batch_id = b.id
    leads = list(service.list_leads(db, batch_id, screening_class, min(limit, 500), offset))
    from app.modules.sales.models import ChannelEligibility  # 延迟导入：sales 依赖 leads

    counts = dict(
        db.execute(
            select(ChannelEligibility.lead_id, func.count())
            .where(ChannelEligibility.lead_id.in_([x.id for x in leads]))
            .group_by(ChannelEligibility.lead_id)
        ).all()
    )
    from app.modules.leads.list_summary import summarize
    from app.modules.sales.workbench import progress

    states = progress(db, [lead.id for lead in leads])
    summaries = summarize(db, [lead.id for lead in leads])
    out = []
    for lead in leads:
        row = LeadOut.model_validate(lead)
        row.contact_count = counts.get(lead.id, 0)
        row.communication_progress = states[lead.id]
        row.list_summary = summaries[lead.id]
        out.append(row)
    return out


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> LeadOut:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    from app.modules.leads.list_summary import summarize
    from app.modules.sales.models import ChannelEligibility
    from app.modules.sales.workbench import progress

    row = LeadOut.model_validate(lead)
    row.list_summary = summarize(db, [lead.id])[lead.id]
    row.communication_progress = progress(db, [lead.id])[lead.id]
    row.contact_count = (
        db.scalar(select(func.count()).select_from(ChannelEligibility).where(ChannelEligibility.lead_id == lead.id))
        or 0
    )
    return row


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def patch_lead(
    lead_id: uuid.UUID, body: LeadPatch, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update().execution_options(populate_existing=True))
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    changes = body.model_dump(exclude_unset=True, exclude={"expected_website"})
    if "website" in changes and "expected_website" in body.model_fields_set and body.expected_website != lead.website:
        raise HTTPException(409, "官网已被更新，请重新读取后确认，避免覆盖最新结果")
    before = {k: getattr(lead, k) for k in changes}
    for k, v in changes.items():
        setattr(lead, k, v)
    if "website" in changes:
        lead.raw = {**(lead.raw or {}), "website_manual": True}
    if "screening_class" in changes or "screening_reason" in changes:
        lead.raw = {**(lead.raw or {}), "screening_manual": True}
    if "entity_status" in changes:
        lead.entity_reviewed_by = op.username
    audit.record(db, op, "patch", "lead", lead.id, before=before, after=changes)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/leads/{lead_id}/entity-candidates")
def entity_candidates(
    lead_id: uuid.UUID, q: str | None = None, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """Companies House 主体候选，供人工核对。默认合并官网披露、注册邮编、店名检索三路；
    传 q 则只按人工输入的公司名检索。只读：不修改线索的主体状态。"""
    from app.modules.leads import entity

    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    key = get_settings().companies_house_api_key
    if not key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "未配置 BEACON_COMPANIES_HOUSE_API_KEY")
    try:
        return entity.find_candidates(lead, key, (q or "").strip() or None)
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Companies House 检索失败：{e.__class__.__name__}: {e}"
        ) from e


class RunIn(BaseModel):
    steps: list[str] = ["fetch", "analyze"]
    max_jobs: int | None = None


class JobOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    step: str
    target_id: uuid.UUID | None
    status: runs.JobStatus
    attempts: int
    error: str | None
    result_id: uuid.UUID | None
    contact_result: dict | None = None

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    steps: list
    status: runs.RunStatus
    started_by: str | None
    started_at: datetime
    finished_at: datetime | None
    totals: dict | None
    jobs: list[JobOut] = []

    model_config = {"from_attributes": True}


def _run_out(db: Session, run: runs.BatchRun) -> RunOut:
    out = RunOut.model_validate(run)
    jobs = list(db.scalars(select(runs.BatchJob).where(runs.BatchJob.run_id == run.id)))
    out.jobs = [JobOut.model_validate(j) for j in jobs]
    snapshots = runs.contact_snapshots(db, jobs)
    out.totals = {**(run.totals or {}), **runs.contact_totals(db, jobs, snapshots)}
    for job, item in zip(jobs, out.jobs, strict=True):
        if job.step == "contacts":
            item.contact_result = snapshots[job.id]
    return out


@router.post("/batches/{batch_key}/runs", response_model=RunOut, status_code=201, dependencies=[Depends(idle_batch)])
def start_batch_run(
    batch_key: str, body: RunIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> RunOut:
    """规划并执行本批次的处理 job（同步，小批次）。一条失败不影响其余；成功的不重复执行。"""
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    try:
        run = runs.start_run(db, batch, body.steps, op.username)
    except runs.RunError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    audit.record(db, op, "start_run", "batch_run", run.id, after={"steps": body.steps})
    db.commit()
    run = runs.execute(db, run, body.max_jobs)
    return _run_out(db, run)


@router.post("/runs/{run_id}/resume", response_model=RunOut, dependencies=[Depends(idle_run)])
def resume_batch_run(
    run_id: uuid.UUID,
    body: RunIn | None = None,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> RunOut:
    """续跑：失败与超时的 job 重置后继续；已成功的不重做。"""
    run = db.get(runs.BatchRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "运行不存在")
    batch = db.get(Batch, run.batch_id)
    assert batch is not None
    runs.resume_run(db, run)
    runs.plan_jobs(db, run, batch)  # 导入了新文件也纳入
    audit.record(db, op, "resume_run", "batch_run", run.id)
    db.commit()
    run = runs.execute(db, run, body.max_jobs if body else None)
    return _run_out(db, run)


class ContinueIn(BaseModel):
    max_jobs: int = 5


@router.post("/runs/{run_id}/continue", response_model=RunOut, dependencies=[Depends(idle_run)])
def continue_batch_run(
    run_id: uuid.UUID, body: ContinueIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> RunOut:
    """继续执行剩余的 pending job（分块执行长任务用）。不重置失败的 job；要重试失败用 resume。"""
    run = db.get(runs.BatchRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "运行不存在")
    run = runs.execute(db, run, max(1, body.max_jobs))
    return _run_out(db, run)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> RunOut:
    run = db.get(runs.BatchRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "运行不存在")
    return _run_out(db, run)


@router.get("/batches/{batch_key}/runs", response_model=list[RunOut])
def list_runs(batch_key: str, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> list[RunOut]:
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    return [
        _run_out(db, r)
        for r in db.scalars(
            select(runs.BatchRun).where(runs.BatchRun.batch_id == batch.id).order_by(runs.BatchRun.started_at)
        ).all()
    ]


class FsaSyncIn(BaseModel):
    authority_id: int
    business_type_id: Literal[1, 7843, 7844] = 1
    business_type_ids: list[Literal[1, 7843, 7844]] | None = Field(default=None, min_length=1, max_length=3)
    exclude_awaiting: bool = False
    sample_n: int | None = None
    seed: int | None = None


@router.get("/sources/fsa/authorities")
def fsa_authorities(db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> list[dict]:
    from app.integrations import fsa

    try:
        return fsa.list_authorities()
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"FSA 接口不可用：{e.__class__.__name__}: {e}") from e


@router.post("/batches/{batch_key}/sync/fsa", dependencies=[Depends(idle_batch)])
def sync_fsa(
    batch_key: str, body: FsaSyncIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """从 FSA 名录自动建立候选（OGL v3）。同批次重复同步只补新记录。"""
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    try:
        result = service.sync_fsa(
            db,
            batch,
            body.authority_id,
            body.business_type_id,
            body.exclude_awaiting,
            body.sample_n,
            body.seed,
            op.username,
            business_type_ids=[int(value) for value in body.business_type_ids]
            if body.business_type_ids is not None
            else None,
        )
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"FSA 同步失败：{e.__class__.__name__}: {e}") from e
    audit.record(
        db,
        op,
        "sync_fsa",
        "batch",
        batch.id,
        after={**body.model_dump(), **{k: v for k, v in result.items() if k != "source_version"}},
    )
    db.commit()
    return result


class OvertureIn(BaseModel):
    max_distance_m: float = 200
    min_similarity: float = 0.5
    overwrite: bool = False


@router.post("/batches/{batch_key}/enrich/overture", dependencies=[Depends(idle_batch)])
def enrich_overture(
    batch_key: str, body: OvertureIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> dict:
    """用 Overture Places 补官网/电话（首次按批次范围下载，之后复用缓存）。只填空缺，来源与置信度记入线索。"""
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    try:
        result = service.enrich_overture(db, batch, body.max_distance_m, body.min_similarity, body.overwrite)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Overture 补全失败：{e.__class__.__name__}: {e}") from e
    audit.record(db, op, "enrich_overture", "batch", batch.id, after={k: v for k, v in result.items() if k != "bbox"})
    db.commit()
    return result


@router.post("/batches/{batch_key}/screen", dependencies=[Depends(idle_batch)])
def auto_screen(batch_key: str, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> dict:
    """规则筛选建议：咖啡店/连锁/机构/酒吧标为排除并写明规则版本；其余保持 unchecked 交人工。"""
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    result = service.auto_screen(db, batch)
    audit.record(db, op, "auto_screen", "batch", batch.id, after=result)
    db.commit()
    return result


@router.post("/leads/{lead_id}/website-review", response_model=LeadOut)
def review_lead_website(lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)):
    from app.integrations.google_places import PlacesError
    from app.modules.leads import places_enrichment, policy

    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "门店不存在")
    try:
        status = places_enrichment.review_one(
            db, lead, op, policy.current(db), f"single-review:{uuid.uuid4()}", force=True
        )
    except PlacesError as exc:
        db.rollback()
        places_enrichment._save_status(lead, "retry", str(exc), [])
    else:
        if status == "changed":
            db.rollback()
            raise HTTPException(409, "核验期间门店资料发生变化，已保留最新人工修改，请刷新后重试")
    db.commit()
    db.refresh(lead)
    return lead
