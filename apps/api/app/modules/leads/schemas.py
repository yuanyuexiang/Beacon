import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.leads.models import EntityStatus, ScreeningClass


class BatchIn(BaseModel):
    batch_key: str = Field(min_length=1, max_length=64)
    country: str = Field(min_length=2, max_length=2)
    region: str | None = None
    business_type: str | None = None
    source_name: str = Field(min_length=1, max_length=64)
    source_version: str | None = None
    source_licence: str | None = None
    sampling_method: str | None = None
    sampling_seed: int | None = None
    notes: str | None = None


class BatchOut(BatchIn):
    id: uuid.UUID
    candidate_count: int | None
    frozen_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadOut(BaseModel):
    id: uuid.UUID
    source_key: str
    source_name: str
    name: str
    address: str | None
    postcode: str | None
    lat: float | None
    lng: float | None
    website: str | None
    screening_class: ScreeningClass
    screening_reason: str | None
    entity_status: EntityStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadPatch(BaseModel):
    website: str | None = None
    website_source: str | None = None
    screening_class: ScreeningClass | None = None
    screening_reason: str | None = None
    entity_status: EntityStatus | None = None
    entity_evidence: str | None = None


class ImportRowError(BaseModel):
    row: int
    reason: str


class ImportResult(BaseModel):
    import_run_id: uuid.UUID
    batch_key: str
    file_sha256: str
    row_count: int
    created_count: int
    linked_count: int
    skipped_count: int
    error_count: int
    errors: list[ImportRowError]
