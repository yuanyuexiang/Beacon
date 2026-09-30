"""content：局部样稿与短文案的版本、内容 hash、审批。审批绑定具体 content_hash；源数据或内容改变即失效。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models_base import Base, Timestamped, UUIDPk


class ContentKind(enum.StrEnum):
    sample_partial = "sample_partial"  # 局部样稿（HTML+PNG）
    message_short = "message_short"  # 短文案


class ContentStatus(enum.StrEnum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"


class ApprovalDecision(enum.StrEnum):
    approved = "approved"
    rejected = "rejected"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, native_enum=False, length=40, values_callable=lambda x: [i.value for i in x])


class ContentPiece(UUIDPk, Timestamped, Base):
    __tablename__ = "content_piece"
    __table_args__ = (UniqueConstraint("lead_id", "kind", "version", name="uq_content_version"),)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_analysis.id")
    )  # 数据来源版本
    kind: Mapped[ContentKind] = mapped_column(_enum(ContentKind, "content_kind"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_name: Mapped[str | None] = mapped_column(String(128))
    template_version: Mapped[str | None] = mapped_column(String(64))
    engine: Mapped[str | None] = mapped_column(String(64))  # 文案生成用：template / fake / <provider>
    spec: Mapped[dict | None] = mapped_column(JSONB)  # 填入模板的数据（菜名、价格、引用的 issue 索引）
    body_text: Mapped[str | None] = mapped_column(Text)
    storage_path_html: Mapped[str | None] = mapped_column(String(512))
    storage_path_png: Mapped[str | None] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # spec+body+template 的 sha256
    source_hash: Mapped[str | None] = mapped_column(String(64))  # 所依赖分析版本内容的 hash
    status: Mapped[ContentStatus] = mapped_column(
        _enum(ContentStatus, "content_status"), default=ContentStatus.draft, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(64))

    approvals: Mapped[list["Approval"]] = relationship(back_populates="content", cascade="all, delete-orphan")


class Approval(UUIDPk, Base):
    __tablename__ = "approval"
    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_piece.id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # 审批时的内容 hash
    decision: Mapped[ApprovalDecision] = mapped_column(_enum(ApprovalDecision, "approval_decision"), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    content: Mapped[ContentPiece] = relationship(back_populates="approvals")
