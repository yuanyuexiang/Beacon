import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.menus.models import AnalysisStatus, AssetKind, FetchStatus


class AssetOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    kind: AssetKind
    source_url: str | None
    final_url: str | None
    original_filename: str | None
    http_status: int | None
    content_type: str | None
    sha256: str | None
    bytes: int | None
    storage_path: str | None
    fetch_status: FetchStatus
    fetch_error: str | None
    fetch_attempts: int
    fetched_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    version: int
    parent_version: int | None
    status: AnalysisStatus
    engine: str
    engine_version: str | None
    items: list | None
    measurements: dict | None
    issues: list | None
    error: str | None
    review_state: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    input_sha256: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
