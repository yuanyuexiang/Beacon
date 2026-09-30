import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.integrations.llm import ProviderUnavailable
from app.modules.leads.models import Lead
from app.modules.menus import review, service
from app.modules.menus.models import MenuAnalysis, MenuAsset
from app.modules.menus.schemas import AnalysisOut, AssetOut

router = APIRouter(tags=["menus"])


class AssetUrlIn(BaseModel):
    url: str


def _lead_or_404(db: Session, lead_id: uuid.UUID) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    return lead


@router.post("/leads/{lead_id}/assets", response_model=AssetOut, status_code=201)
def add_asset_by_url(
    lead_id: uuid.UUID, body: AssetUrlIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> MenuAsset:
    """按人工核对过的 URL 抓取菜单。失败也返回 201，fetch_status=failed 并带原因，可重试。"""
    _lead_or_404(db, lead_id)
    asset = service.add_url(db, lead_id, body.url, op.username)
    audit.record(db, op, "add_asset_url", "menu_asset", asset.id, after={"url": body.url, "status": asset.fetch_status})
    db.commit()
    return asset


@router.post("/leads/{lead_id}/assets/upload", response_model=AssetOut, status_code=201)
async def add_asset_upload(
    lead_id: uuid.UUID,
    file: UploadFile = File(...),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> MenuAsset:
    _lead_or_404(db, lead_id)
    body = await file.read()
    try:
        asset = service.add_upload(db, lead_id, file.filename, file.content_type, body, op.username)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    audit.record(db, op, "add_asset_upload", "menu_asset", asset.id, after={"filename": file.filename, "note": note})
    db.commit()
    return asset


@router.post("/assets/{asset_id}/retry", response_model=AssetOut)
def retry_asset(
    asset_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> MenuAsset:
    asset = db.get(MenuAsset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    if not asset.source_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "上传文件不能重试抓取")
    asset = service.fetch_asset(db, asset)
    audit.record(
        db, op, "retry_asset", "menu_asset", asset.id, after={"status": asset.fetch_status, "error": asset.fetch_error}
    )
    db.commit()
    return asset


@router.get("/leads/{lead_id}/assets", response_model=list[AssetOut])
def list_assets(
    lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> list[MenuAsset]:
    _lead_or_404(db, lead_id)
    return list(db.scalars(select(MenuAsset).where(MenuAsset.lead_id == lead_id).order_by(MenuAsset.created_at)).all())


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> MenuAsset:
    asset = db.get(MenuAsset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return asset


@router.post("/assets/{asset_id}/analyses", response_model=AnalysisOut)
def create_analysis(
    asset_id: uuid.UUID,
    engine: str = "rules",
    force: bool = False,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> MenuAnalysis:
    """运行分析并生成版本。同输入同引擎已有有效结果时返回该结果（200），不新建。"""
    asset = db.get(MenuAsset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    try:
        a, created = service.run_analysis(db, asset, engine=engine, force=force)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ProviderUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    if created:
        audit.record(
            db,
            op,
            "analyze",
            "menu_analysis",
            a.id,
            after={"engine": a.engine, "status": a.status, "version": a.version},
        )
        db.commit()
    return a


@router.get("/assets/{asset_id}/analyses", response_model=list[AnalysisOut])
def list_analyses(
    asset_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> list[MenuAnalysis]:
    return list(
        db.scalars(select(MenuAnalysis).where(MenuAnalysis.asset_id == asset_id).order_by(MenuAnalysis.version)).all()
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(
    analysis_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> MenuAnalysis:
    a = db.get(MenuAnalysis, analysis_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分析不存在")
    return a


class CorrectionIn(BaseModel):
    field_path: str
    new_value: Any
    reason: str | None = None


class CorrectionsIn(BaseModel):
    corrections: list[CorrectionIn]


class EvidenceOut(BaseModel):
    analysis_id: uuid.UUID
    asset_id: uuid.UUID
    kind: str
    file_url: str | None
    version: int
    parent_version: int | None
    items: list
    issues: list
    measurements: dict | None
    review_state: str | None


def _analysis_or_404(db: Session, analysis_id: uuid.UUID) -> MenuAnalysis:
    a = db.get(MenuAnalysis, analysis_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分析不存在")
    return a


@router.get("/analyses/{analysis_id}/evidence", response_model=EvidenceOut)
def get_evidence(
    analysis_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> EvidenceOut:
    """证据视图：原文件（受控下载链接）与带位置的条目/问题同屏。"""
    a = _analysis_or_404(db, analysis_id)
    asset = db.get(MenuAsset, a.asset_id)
    assert asset is not None
    return EvidenceOut(
        analysis_id=a.id,
        asset_id=asset.id,
        kind=asset.kind.value,
        file_url=f"/api/files/{asset.storage_path}" if asset.storage_path else None,
        version=a.version,
        parent_version=a.parent_version,
        items=a.items or [],
        issues=a.issues or [],
        measurements=a.measurements,
        review_state=a.review_state,
    )


@router.patch("/analyses/{analysis_id}", response_model=AnalysisOut)
def correct_analysis(
    analysis_id: uuid.UUID, body: CorrectionsIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> MenuAnalysis:
    """人工修正：生成新版本，原版本保留；每处修正可追溯。"""
    a = _analysis_or_404(db, analysis_id)
    latest = service.latest_analysis(db, a.asset_id)
    if latest is None or latest.id != a.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "只能在最新版本上修正")
    try:
        nv = review.apply_corrections(db, a, [c.model_dump() for c in body.corrections], op.username)
    except review.CorrectionError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    audit.record(
        db, op, "correct", "menu_analysis", nv.id, before={"version": a.version}, after={"version": nv.version}
    )
    db.commit()
    return nv


@router.post("/analyses/{analysis_id}/review", response_model=AnalysisOut)
def complete_review(
    analysis_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> MenuAnalysis:
    a = _analysis_or_404(db, analysis_id)
    try:
        a = review.complete_review(db, a, op.username)
    except review.CorrectionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(db, op, "review", "menu_analysis", a.id, after={"review_state": a.review_state})
    db.commit()
    return a
