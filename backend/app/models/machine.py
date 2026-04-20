import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, DateTime, String, Integer, func, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.models.base import Base, TimestampMixin, UUIDMixin


class MachineStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"  # No new instances, existing keep running


class Machine(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "machines"

    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    docker_host: Mapped[str] = mapped_column(String(255), nullable=False)  # tcp://host:2376 or ssh://user@host
    ssh_user: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ssh_key_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    max_instances: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_ram_mb: Mapped[int] = mapped_column(Integer, default=32768, nullable=False)
    status: Mapped[MachineStatus] = mapped_column(
        Enum(MachineStatus, name="machine_status"),
        default=MachineStatus.ONLINE,
        nullable=False
    )
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    cpu_pct: Mapped[Optional[float]] = mapped_column(nullable=True)
    ram_pct: Mapped[Optional[float]] = mapped_column(nullable=True)
