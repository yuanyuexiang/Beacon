"""触达准备独立于可执行任务；缺项可保存，激活时仍须满足全部业务约束。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models_base import Base, Timestamped, UUIDPk


class Preparation(UUIDPk, Timestamped, Base):
    __tablename__ = "communication_draft"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'converted', 'cancelled')", name="ck_communication_draft_status"),
        Index("uq_communication_active", "lead_id", "channel", unique=True, postgresql_where=text("status = 'draft'")),
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), index=True
    )
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(32))
    execution_mode: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    eligibility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_eligibility.id", ondelete="SET NULL")
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_piece.id", ondelete="SET NULL")
    )
    assigned_to: Mapped[str | None] = mapped_column(String(64), ForeignKey("operator.username", ondelete="SET NULL"))
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(String(16), default="initial", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manual_task.id", ondelete="SET NULL")
    )
    queued: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64))
