"""sales：渠道准入、人工任务、事件（幂等键）、抑制、成本。unknown 不放行；模型不得修改准入。"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models_base import Base, Timestamped, UUIDPk


class Channel(enum.StrEnum):
    email = "email"
    whatsapp = "whatsapp"
    phone = "phone"
    instagram = "instagram"
    facebook = "facebook"
    tiktok = "tiktok"
    other_social = "other_social"  # X、LinkedIn、YouTube 等；contact_ref 为账号 URL
    contact_form = "contact_form"
    post = "post"


class ContactUsable(enum.StrEnum):
    unknown = "unknown"
    valid = "valid"
    invalid = "invalid"


class Eligibility(enum.StrEnum):
    unknown = "unknown"
    allowed = "allowed"
    blocked = "blocked"


class TaskStatus(enum.StrEnum):
    pending = "pending"
    opened = "opened"
    sent_manual = "sent_manual"
    paused = "paused"
    cancelled = "cancelled"


class EventKind(enum.StrEnum):
    reply = "reply"
    reject = "reject"
    unsubscribe = "unsubscribe"
    bounce = "bounce"
    note = "note"


class SuppressionScope(enum.StrEnum):
    lead = "lead"
    contact = "contact"


class CostCategory(enum.StrEnum):
    setup = "setup"
    processing = "processing"
    outreach = "outreach"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, native_enum=False, length=40, values_callable=lambda x: [i.value for i in x])


class ChannelEligibility(UUIDPk, Timestamped, Base):
    __tablename__ = "channel_eligibility"
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel"), nullable=False)
    contact_ref: Mapped[str | None] = mapped_column(String(256))  # 规范化联系值；可为空（如联系表单 URL）
    contact_source: Mapped[str | None] = mapped_column(String(256))
    contact_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_usable: Mapped[ContactUsable] = mapped_column(
        _enum(ContactUsable, "contact_usable"), default=ContactUsable.unknown, nullable=False
    )
    eligibility: Mapped[Eligibility] = mapped_column(
        _enum(Eligibility, "eligibility"), default=Eligibility.unknown, nullable=False
    )
    rule_version: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[str | None] = mapped_column(Text)  # 授权/筛查证据说明
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManualTask(UUIDPk, Timestamped, Base):
    __tablename__ = "manual_task"
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel"), nullable=False)
    eligibility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel_eligibility.id"), nullable=False
    )
    content_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("content_piece.id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # 创建任务时审批通过的内容 hash
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "task_status"), default=TaskStatus.pending, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(64))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_by: Mapped[str | None] = mapped_column(String(64))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 销售填写的实际发生时间
    sent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 系统录入时间
    sent_by: Mapped[str | None] = mapped_column(String(64))
    status_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class Event(UUIDPk, Base):
    __tablename__ = "event"
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[Channel | None] = mapped_column(_enum(Channel, "channel"))
    event_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)  # 幂等键
    kind: Mapped[EventKind] = mapped_column(_enum(EventKind, "event_kind"), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 对方回复时间（可空）
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 系统收到/录入时间
    recorded_by: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict | None] = mapped_column(JSONB)  # 摘要/分类等；不长期保留原文
    actions: Mapped[list | None] = mapped_column(JSONB)  # 系统执行的动作 [{action, target_id}]


class Suppression(UUIDPk, Base):
    __tablename__ = "suppression"
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id", ondelete="SET NULL"))
    scope: Mapped[SuppressionScope] = mapped_column(_enum(SuppressionScope, "suppression_scope"), nullable=False)
    contact_ref: Mapped[str | None] = mapped_column(String(256))  # scope=contact 时的规范化联系值
    reason: Mapped[str] = mapped_column(String(64), nullable=False)  # reject / unsubscribe / bounce / manual
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("event.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64))


class CostEntry(UUIDPk, Base):
    __tablename__ = "cost_entry"
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("batch.id"))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lead.id", ondelete="SET NULL"))
    category: Mapped[CostCategory] = mapped_column(_enum(CostCategory, "cost_category"), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    minutes: Mapped[int | None] = mapped_column(Integer)
    basis: Mapped[str | None] = mapped_column(Text)  # 计价依据
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[str | None] = mapped_column(String(64))
