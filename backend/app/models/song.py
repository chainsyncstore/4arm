import uuid
from typing import Optional
from sqlalchemy import Column, Enum, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import Base, TimestampMixin, UUIDMixin


class SongPriority(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SongStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class Song(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "songs"

    spotify_uri: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    artist: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    album_art_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    total_target_streams: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_streams: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streams_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[SongPriority] = mapped_column(
        Enum(SongPriority, name="song_priority"),
        default=SongPriority.MEDIUM,
        nullable=False
    )
    status: Mapped[SongStatus] = mapped_column(
        Enum(SongStatus, name="song_status"),
        default=SongStatus.ACTIVE,
        nullable=False
    )

    # Relationships
    stream_logs: Mapped[list["StreamLog"]] = relationship("StreamLog", back_populates="song", lazy="selectin")
