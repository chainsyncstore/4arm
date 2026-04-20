import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import Base, TimestampMixin, UUIDMixin


class InstanceStatus(str, enum.Enum):
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    DESTROYING = "destroying"


class Instance(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "instances"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    docker_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    redsocks_container_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[InstanceStatus] = mapped_column(
        Enum(InstanceStatus, name="instance_status"),
        default=InstanceStatus.CREATING,
        nullable=False
    )
    adb_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assigned_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id"),
        nullable=True,
        unique=True
    )
    ram_limit_mb: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    cpu_cores: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    behavior_profile: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    assigned_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        back_populates="assigned_instance",
        foreign_keys=[assigned_account_id],
        lazy="selectin"
    )
