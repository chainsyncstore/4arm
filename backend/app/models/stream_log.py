import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import Base, TimestampMixin, UUIDMixin


class StreamResult(str, enum.Enum):
    SUCCESS = "success"
    FAIL = "fail"
    SHUFFLE_MISS = "shuffle_miss"
    HEALTH_CHECK = "health_check"


class StreamLog(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "stream_logs"

    instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("instances.id"),
        nullable=True
    )
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id"),
        nullable=True
    )
    song_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("songs.id"),
        nullable=True
    )
    spotify_uri: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    result: Mapped[StreamResult] = mapped_column(
        Enum(StreamResult, name="stream_result"),
        nullable=False
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    instance: Mapped[Optional["Instance"]] = relationship("Instance")
    account: Mapped[Optional["Account"]] = relationship("Account")
    song: Mapped[Optional["Song"]] = relationship("Song", back_populates="stream_logs")
