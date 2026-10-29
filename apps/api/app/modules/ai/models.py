"""Immutable, encrypted AI configuration revisions; tasks retain revision references."""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models_base import Base, Timestamped, UUIDPk


class AIConfiguration(UUIDPk, Timestamped, Base):
    __tablename__ = "ai_configuration"
    data: Mapped[dict] = mapped_column(JSONB)
