"""Phone execution is separate from provider deliveries and inbound social conversations."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models_base import Base, Timestamped, UUIDPk


class Device(UUIDPk, Timestamped, Base):
    __tablename__ = "mobile_device"
    owner: Mapped[str] = mapped_column(String(64), ForeignKey("operator.username", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(128))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="paired")
    account: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict)


class Pairing(UUIDPk, Base):
    __tablename__ = "mobile_pairing"
    owner: Mapped[str] = mapped_column(String(64), ForeignKey("operator.username", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Execution(UUIDPk, Timestamped, Base):
    __tablename__ = "mobile_execution"
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manual_task.id", ondelete="CASCADE"), unique=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mobile_device.id"))
    confirmed_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    snapshot: Mapped[dict] = mapped_column(JSONB)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_hash: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class ReplyNotification(UUIDPk, Timestamped, Base):
    __tablename__ = "mobile_reply_notification"
    __table_args__ = (
        UniqueConstraint("device_id", "event_key"),
        Index("ix_mobile_reply_inbox", "device_id", "status", "created_at"),
    )
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mobile_device.id", ondelete="CASCADE"))
    event_key: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(24))
    thread_key: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    structured: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mobile_execution.id", ondelete="SET NULL")
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("event.id", ondelete="SET NULL"))


class ReplyThread(UUIDPk, Timestamped, Base):
    __tablename__ = "mobile_reply_thread"
    __table_args__ = (UniqueConstraint("device_id", "channel", "thread_key"),)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mobile_device.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(24))
    thread_key: Mapped[str] = mapped_column(String(64))
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mobile_execution.id", ondelete="CASCADE")
    )
