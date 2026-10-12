"""Channel-scoped identities, inbound conversations and approved social deliveries."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models_base import Base, Timestamped, UUIDPk


class ChannelAccount(UUIDPk, Timestamped, Base):
    __tablename__ = "channel_account"
    __table_args__ = (UniqueConstraint("platform", "sender_id", name="uq_channel_account_sender"),)
    platform: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(128))
    auth_mode: Mapped[str] = mapped_column(String(32))
    sender_id: Mapped[str] = mapped_column(String(128))
    page_id: Mapped[str | None] = mapped_column(String(128))
    auth_version: Mapped[str | None] = mapped_column(String(64))
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    sending_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    queue_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=20)
    capabilities: Mapped[list] = mapped_column(JSONB, default=list)


class Conversation(UUIDPk, Timestamped, Base):
    __tablename__ = "social_conversation"
    __table_args__ = (UniqueConstraint("account_id", "recipient_id", name="uq_social_recipient"),)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channel_account.id"))
    recipient_id: Mapped[str] = mapped_column(String(128))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"))
    eligibility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_eligibility.id", ondelete="SET NULL")
    )
    mapping_version: Mapped[str] = mapped_column(String(64))
    last_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_message: Mapped[str | None] = mapped_column(Text)


class ConversationEvent(UUIDPk, Base):
    __tablename__ = "social_conversation_event"
    __table_args__ = (UniqueConstraint("account_id", "message_id", name="uq_social_event"),)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channel_account.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_conversation.id", ondelete="CASCADE")
    )
    message_id: Mapped[str] = mapped_column(String(256))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed: Mapped[bool] = mapped_column(Boolean, default=False)


class OutreachDelivery(UUIDPk, Timestamped, Base):
    __tablename__ = "outreach_delivery"
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manual_task.id", ondelete="CASCADE"), unique=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("channel_account.id"))
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("social_conversation.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(32), index=True, default="preview")
    payload: Mapped[dict] = mapped_column(JSONB)
    approval_token: Mapped[str | None] = mapped_column(Text)
    request_key: Mapped[str] = mapped_column(String(128), unique=True)
    auth_version: Mapped[str] = mapped_column(String(64))
    mapping_version: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_message_id: Mapped[str | None] = mapped_column(String(256))
    last_error: Mapped[str | None] = mapped_column(Text)
