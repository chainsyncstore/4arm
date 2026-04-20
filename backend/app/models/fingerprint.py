"""DeviceFingerprint model — stores per-instance device identity data."""

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DeviceFingerprint(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "device_fingerprints"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), unique=True, nullable=False
    )
    android_id: Mapped[str] = mapped_column(String(16), nullable=False)
    device_model: Mapped[str] = mapped_column(String(100), nullable=False)
    device_brand: Mapped[str] = mapped_column(String(50), nullable=False)
    device_manufacturer: Mapped[str] = mapped_column(String(50), nullable=False)
    build_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    gsfid: Mapped[str] = mapped_column(String(20), nullable=False)
    screen_density: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False)
    advertising_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Relationship
    instance: Mapped["Instance"] = relationship(
        "Instance",
        backref=backref("fingerprint", uselist=False, cascade="all, delete-orphan"),
    )
