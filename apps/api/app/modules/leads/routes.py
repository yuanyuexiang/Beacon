import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import Operator
from app.modules.leads import runs, service
from app.modules.leads.models import Batch, Lead, ScreeningClass
from app.modules.leads.schemas import BatchIn, BatchOut, ImportResult, LeadOut, LeadPatch

router = APIRouter(tags=["leads"])


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
def list_batches(db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> list[Batch]:
    return list(db.scalars(select(Batch).order_by(Batch.created_at.desc())).all())


@router.post("/imports", response_model=ImportResult)
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
) -> list[Lead]:
    batch_id = None
    if batch_key:
        b = service.get_batch_by_key(db, batch_key)
        if b is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
        batch_id = b.id
    return list(service.list_leads(db, batch_id, screening_class, min(limit, 500), offset))


@router.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    return lead


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def patch_lead(
    lead_id: uuid.UUID, body: LeadPatch, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(lead, k) for k in changes}
    for k, v in changes.items():
        setattr(lead, k, v)
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
    out.jobs = [
        JobOut.model_validate(j) for j in db.scalars(select(runs.BatchJob).where(runs.BatchJob.run_id == run.id)).all()
    ]
    return out


@router.post("/batches/{batch_key}/runs", response_model=RunOut, status_code=201)
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


@router.post("/runs/{run_id}/resume", response_model=RunOut)
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
    business_type_id: int = 1
    exclude_awaiting: bool = True
    sample_n: int | None = None
    seed: int | None = None


@router.get("/sources/fsa/authorities")
def fsa_authorities(db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> list[dict]:
    from app.integrations import fsa

    try:
        return fsa.list_authorities()
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"FSA 接口不可用：{e.__class__.__name__}: {e}") from e


@router.post("/batches/{batch_key}/sync/fsa")
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


@router.post("/batches/{batch_key}/enrich/overture")
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


@router.post("/batches/{batch_key}/screen")
def auto_screen(batch_key: str, db: Session = Depends(get_db), op: Operator = Depends(current_operator)) -> dict:
    """规则筛选建议：咖啡店/连锁/机构/酒吧标为排除并写明规则版本；其余保持 unchecked 交人工。"""
    batch = service.get_batch_by_key(db, batch_key)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批次不存在")
    result = service.auto_screen(db, batch)
    audit.record(db, op, "auto_screen", "batch", batch.id, after=result)
    db.commit()
    return result
