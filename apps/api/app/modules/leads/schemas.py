import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

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
    assigned_to: str | None = None
    id: uuid.UUID
    source_key: str
    source_name: str
    name: str
    address: str | None
    postcode: str | None
    lat: float | None
    lng: float | None
    website: str | None
    website_source: str | None
    screening_class: ScreeningClass
    screening_reason: str | None
    entity_status: EntityStatus
    entity_evidence: str | None
    business_type_id: int | None = None
    business_type_name: str | None = None
    inspection_pending: bool = False
    manual_entry: dict | None = None
    operating_type: dict | None = None
    website_research: dict | None = None
    google_enrichment: dict | None = None
    source_sync: dict | None = None
    verified_websites: list[dict] = Field(default_factory=list)
    website_history: list[dict] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def source_metadata(cls, value):
        from app.modules.leads.models import Lead

        if isinstance(value, Lead):
            raw = value.raw or {}
            row = {k: getattr(value, k) for k in cls.model_fields if hasattr(value, k)}
            row.update(
                manual_entry={k: v for k, v in raw.get("manual_entry", {}).items() if k != "request_hash"} or None,
                operating_type=raw.get("operating_type"),
                website_research=raw.get("website_research"),
                google_enrichment=raw.get("places_enrichment"),
                source_sync=raw.get("source_sync"),
                verified_websites=raw.get("verified_websites", []),
                website_history=raw.get("website_history", []),
            )
            return row
        return value

    list_summary: dict | None = None
    communication_progress: dict | None = None
    contact_count: int = 0  # 已记录的联系方式数（仅列表接口填充）
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadPatch(BaseModel):
    expected_website: str | None = None
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
