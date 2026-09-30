"""menus：菜单文件（受控存储引用）、分析版本、人工修正。分析失败不伪装成功；修正生成新版本，原值保留。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models_base import Base, Timestamped, UUIDPk


class AssetKind(enum.StrEnum):
    html = "html"
    pdf = "pdf"
    image = "image"
    unknown = "unknown"


class FetchStatus(enum.StrEnum):
    pending = "pending"
    fetched = "fetched"
    failed = "failed"


class AnalysisStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    needs_review = "needs_review"
    failed = "failed"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, native_enum=False, length=40, values_callable=lambda x: [i.value for i in x])


class MenuAsset(UUIDPk, Timestamped, Base):
    __tablename__ = "menu_asset"
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[AssetKind] = mapped_column(_enum(AssetKind, "asset_kind"), default=AssetKind.unknown, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))  # 上传文件时为空
    final_url: Mapped[str | None] = mapped_column(String(1024))
    original_filename: Mapped[str | None] = mapped_column(String(256))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(128))
    sha256: Mapped[str | None] = mapped_column(String(64))
    bytes: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(String(512))  # 相对 BEACON_DATA_DIR
    fetch_status: Mapped[FetchStatus] = mapped_column(
        _enum(FetchStatus, "fetch_status"), default=FetchStatus.pending, nullable=False
    )
    fetch_error: Mapped[str | None] = mapped_column(Text)
    fetch_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    added_by: Mapped[str | None] = mapped_column(String(64))

    analyses: Mapped[list["MenuAnalysis"]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class MenuAnalysis(UUIDPk, Timestamped, Base):
    """一次分析尝试/版本。items、measurements、issues 为结构化 JSON；issues 每项含证据位置与人工确认字段。"""

    __tablename__ = "menu_analysis"
    __table_args__ = (UniqueConstraint("asset_id", "version", name="uq_analysis_version"),)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_asset.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer)  # 由哪个版本修正而来
    status: Mapped[AnalysisStatus] = mapped_column(
        _enum(AnalysisStatus, "analysis_status"), default=AnalysisStatus.pending, nullable=False
    )
    engine: Mapped[str] = mapped_column(String(64), nullable=False)  # rules / fake / <provider>
    engine_version: Mapped[str | None] = mapped_column(String(64))
    items: Mapped[list | None] = mapped_column(
        JSONB
    )  # [{name, price_text, price, currency_symbol, decimals, evidence:{page,line,raw}}]
    measurements: Mapped[dict | None] = mapped_column(JSONB)  # menu_probe 输出
    issues: Mapped[list | None] = mapped_column(
        JSONB
    )  # [{issue_code, fact, evidence, severity, confirmed, confirmed_by, confirmed_at, note}]
    error: Mapped[str | None] = mapped_column(Text)
    review_state: Mapped[str | None] = mapped_column(String(32))  # None / reviewed
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_sha256: Mapped[str | None] = mapped_column(String(64))  # 分析所用文件 hash，防止文件更换后结果错配

    asset: Mapped[MenuAsset] = relationship(back_populates="analyses")
    corrections: Mapped[list["AnalysisCorrection"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class AnalysisCorrection(UUIDPk, Base):
    """人工修正记录：记录在新版本上，指向 JSON 路径，保留旧值与新值。"""

    __tablename__ = "analysis_correction"
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_analysis.id", ondelete="CASCADE"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(
        String(256), nullable=False
    )  # 例如 items[3].price_text / issues[0].confirmed
    old_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    new_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    corrected_by: Mapped[str] = mapped_column(String(64), nullable=False)
    corrected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    analysis: Mapped[MenuAnalysis] = relationship(back_populates="corrections")
