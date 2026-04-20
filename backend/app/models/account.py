import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Enum, ForeignKey, Integer, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import Base, TimestampMixin, UUIDMixin


class AccountType(str, enum.Enum):
    FREE = "free"
    PREMIUM = "premium"


class AccountStatus(str, enum.Enum):
    NEW = "new"
    WARMING = "warming"
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    BANNED = "banned"


class Account(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "accounts"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_plain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type"),
        default=AccountType.FREE,
        nullable=False
    )
    session_blob_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    proxy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("proxies.id"),
        nullable=True,
        unique=True
    )
    fingerprint_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, name="account_status"),
        default=AccountStatus.NEW,
        nullable=False
    )
    warmup_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_streams: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streams_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    proxy: Mapped[Optional["Proxy"]] = relationship("Proxy", back_populates="account", lazy="selectin")
    assigned_instance: Mapped[Optional["Instance"]] = relationship(
        "Instance",
        back_populates="assigned_account",
        uselist=False,
        foreign_keys="Instance.assigned_account_id",
        lazy="selectin"
    )
