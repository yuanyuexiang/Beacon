import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.modules.content import service
from app.modules.content.models import ApprovalDecision, ContentKind, ContentPiece, ContentStatus
from app.modules.leads.models import Lead
from app.modules.menus.models import MenuAnalysis

router = APIRouter(tags=["content"])


class ContentCreateIn(BaseModel):
    kind: ContentKind
    analysis_id: uuid.UUID
    section: str | None = None
    item_indexes: list[int] | None = None
    sender_identity: str | None = None
    opt_out_text: str | None = None
    website: str | None = None


class ContentOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    analysis_id: uuid.UUID | None
    kind: ContentKind
    version: int
    template_name: str | None
    template_version: str | None
    engine: str | None
    spec: dict | None
    body_text: str | None
    html_url: str | None
    png_url: str | None
    content_hash: str
    source_hash: str | None
    status: ContentStatus
    approval_valid: bool
    approval_invalid_reason: str | None
    created_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionIn(BaseModel):
    decision: ApprovalDecision
    note: str | None = None


class ReviseIn(BaseModel):
    body_text: str


def _out(db: Session, p: ContentPiece) -> ContentOut:
    ok, why = service.approval_valid(db, p)
    return ContentOut(
        id=p.id,
        lead_id=p.lead_id,
        analysis_id=p.analysis_id,
        kind=p.kind,
        version=p.version,
        template_name=p.template_name,
        template_version=p.template_version,
        engine=p.engine,
        spec=p.spec,
        body_text=p.body_text,
        html_url=f"/api/files/{p.storage_path_html}" if p.storage_path_html else None,
        png_url=f"/api/files/{p.storage_path_png}" if p.storage_path_png else None,
        content_hash=p.content_hash,
        source_hash=p.source_hash,
        status=p.status,
        approval_valid=ok,
        approval_invalid_reason=why,
        created_by=p.created_by,
        created_at=p.created_at,
    )


def _piece_or_404(db: Session, content_id: uuid.UUID) -> ContentPiece:
    p = db.get(ContentPiece, content_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "内容不存在")
    return p


@router.post("/leads/{lead_id}/content", response_model=ContentOut, status_code=201)
def create_content(
    lead_id: uuid.UUID, body: ContentCreateIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> ContentOut:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线索不存在")
    a = db.get(MenuAnalysis, body.analysis_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分析不存在")
    try:
        if body.kind == ContentKind.sample_partial:
            p = service.create_sample(db, lead, a, body.section or "Sample section", body.item_indexes, op.username)
        else:
            p = service.create_message(
                db,
                lead,
                a,
                body.sender_identity or "",
                body.opt_out_text or "",
                body.website or lead.website,
                op.username,
            )
    except service.ContentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(db, op, "create_content", "content_piece", p.id, after={"kind": p.kind, "version": p.version})
    db.commit()
    return _out(db, p)


@router.get("/leads/{lead_id}/content", response_model=list[ContentOut])
def list_content(
    lead_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> list[ContentOut]:
    rows = db.scalars(
        select(ContentPiece).where(ContentPiece.lead_id == lead_id).order_by(ContentPiece.kind, ContentPiece.version)
    ).all()
    return [_out(db, p) for p in rows]


@router.get("/content/{content_id}", response_model=ContentOut)
def get_content(
    content_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> ContentOut:
    return _out(db, _piece_or_404(db, content_id))


@router.post("/content/{content_id}/approve", response_model=ContentOut)
def approve_content(
    content_id: uuid.UUID, body: DecisionIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> ContentOut:
    p = _piece_or_404(db, content_id)
    try:
        p = service.decide(db, p, body.decision, op.username, body.note)
    except service.ContentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(
        db, op, "approve", "content_piece", p.id, after={"decision": body.decision, "content_hash": p.content_hash}
    )
    db.commit()
    return _out(db, p)


@router.post("/content/{content_id}/revise", response_model=ContentOut, status_code=201)
def revise_content(
    content_id: uuid.UUID, body: ReviseIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
) -> ContentOut:
    p = _piece_or_404(db, content_id)
    try:
        nv = service.revise_message(db, p, body.body_text, op.username)
    except service.ContentError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    audit.record(
        db, op, "revise_content", "content_piece", nv.id, before={"version": p.version}, after={"version": nv.version}
    )
    db.commit()
    return _out(db, nv)
