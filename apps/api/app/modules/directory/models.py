import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models_base import Base, Timestamped, UUIDPk


class Authority(Timestamped, Base):
    __tablename__ = "directory_authority"
    authority_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str | None] = mapped_column(String(128))
    establishment_count: Mapped[int | None] = mapped_column(Integer)


class Region(Timestamped, Base):
    __tablename__ = "directory_region"
    authority_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    business_type_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    interval_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    type_versions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SyncRun(UUIDPk, Timestamped, Base):
    __tablename__ = "directory_sync"
    __table_args__ = (
        Index(
            "uq_directory_active_sync",
            "authority_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
    authority_id: Mapped[int] = mapped_column(Integer, ForeignKey("directory_region.authority_id"), nullable=False)
    business_type_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    source_versions: Mapped[dict | None] = mapped_column(JSONB)


class Entry(Timestamped, Base):
    __tablename__ = "directory_entry"
    fhrsid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    authority_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("directory_region.authority_id"), index=True, nullable=False
    )
    business_type_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    postcode: Mapped[str | None] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    present: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    discovery_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    last_change_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("directory_sync.id"), nullable=False
    )


class Change(UUIDPk, Base):
    __tablename__ = "directory_change"
    sync_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("directory_sync.id"), index=True, nullable=False
    )
    fhrsid: Mapped[int] = mapped_column(BigInteger, ForeignKey("directory_entry.fhrsid"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False)


class WorkerStatus(Base):
    __tablename__ = "directory_worker_status"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
