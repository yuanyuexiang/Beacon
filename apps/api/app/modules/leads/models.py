"""leads：批次、门店（线索）、批次成员、导入记录。门店与法律主体分开记录，主体未知不推断。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models_base import Base, Timestamped, UUIDPk


class ScreeningClass(enum.StrEnum):
    unchecked = "unchecked"
    candidate = "candidate"
    unknown = "unknown"
    excluded_cafe = "excluded_cafe"
    excluded_chain = "excluded_chain"
    excluded_canteen = "excluded_canteen"
    excluded_community = "excluded_community"
    excluded_institution = "excluded_institution"
    excluded_pub = "excluded_pub"
    excluded_closed = "excluded_closed"
    excluded_other = "excluded_other"


class EntityStatus(enum.StrEnum):
    unknown = "unknown"
    company = "company"
    sole_trader = "sole_trader"
    other = "other"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, native_enum=False, length=40, values_callable=lambda x: [i.value for i in x])


class Batch(UUIDPk, Timestamped, Base):
    __tablename__ = "batch"
    batch_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    region: Mapped[str | None] = mapped_column(String(128))
    business_type: Mapped[str | None] = mapped_column(String(128))
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)  # 例如 fsa
    source_version: Mapped[str | None] = mapped_column(String(64))  # 例如 extractDate
    source_licence: Mapped[str | None] = mapped_column(String(128))  # 例如 OGL-3.0
    sampling_method: Mapped[str | None] = mapped_column(Text)
    sampling_seed: Mapped[int | None] = mapped_column(Integer)
    candidate_count: Mapped[int | None] = mapped_column(Integer)  # 冻结的 N
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    members: Mapped[list["BatchLead"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class Lead(UUIDPk, Timestamped, Base):
    """门店。source_key 为稳定来源键（如 fsa:416314），跨批次唯一。"""

    __tablename__ = "lead"
    source_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    postcode: Mapped[str | None] = mapped_column(String(16))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    website: Mapped[str | None] = mapped_column(String(512))
    website_source: Mapped[str | None] = mapped_column(String(128))  # 官网来源说明（人工检索/来源字段）
    screening_class: Mapped[ScreeningClass] = mapped_column(
        _enum(ScreeningClass, "screening_class"), default=ScreeningClass.unchecked, nullable=False
    )
    screening_reason: Mapped[str | None] = mapped_column(Text)
    entity_status: Mapped[EntityStatus] = mapped_column(
        _enum(EntityStatus, "entity_status"), default=EntityStatus.unknown, nullable=False
    )
    entity_evidence: Mapped[str | None] = mapped_column(Text)
    entity_reviewed_by: Mapped[str | None] = mapped_column(String(64))
    raw: Mapped[dict | None] = mapped_column(JSONB)  # 来源原始记录（仅许可允许存储的字段）

    memberships: Mapped[list["BatchLead"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class BatchLead(UUIDPk, Base):
    __tablename__ = "batch_lead"
    __table_args__ = (UniqueConstraint("batch_id", "lead_id", name="uq_batch_lead"),)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    sample_order: Mapped[int | None] = mapped_column(Integer)

    batch: Mapped[Batch] = relationship(back_populates="members")
    lead: Mapped[Lead] = relationship(back_populates="memberships")


class ImportRun(UUIDPk, Timestamped, Base):
    __tablename__ = "import_run"
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("batch.id"), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(256))
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    linked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 已存在门店关联到本批次
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 同批次重复行
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[list | None] = mapped_column(JSONB)  # [{row, reason}]
    operator: Mapped[str | None] = mapped_column(String(64))
