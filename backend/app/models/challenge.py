import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import Enum, ForeignKey, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ChallengeType(str, enum.Enum):
    CAPTCHA = "captcha"
    EMAIL_VERIFY = "email_verify"
    PHONE_VERIFY = "phone_verify"
    TERMS_ACCEPT = "terms_accept"
    UNKNOWN = "unknown"


class ChallengeStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    FAILED = "failed"


class Challenge(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "challenges"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=True
    )
    type: Mapped[ChallengeType] = mapped_column(
        Enum(ChallengeType, name="challenge_type"),
        default=ChallengeType.UNKNOWN, nullable=False
    )
    status: Mapped[ChallengeStatus] = mapped_column(
        Enum(ChallengeStatus, name="challenge_status"),
        default=ChallengeStatus.PENDING, nullable=False
    )
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    account = relationship("Account", lazy="selectin")
    instance = relationship("Instance", lazy="selectin")
