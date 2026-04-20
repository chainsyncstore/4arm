import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Float, UniqueConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import Base, TimestampMixin, UUIDMixin


class ProxyProtocol(str, enum.Enum):
    SOCKS5 = "socks5"
    HTTP = "http"
    HTTPS = "https"


class ProxyStatus(str, enum.Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNCHECKED = "unchecked"


class Proxy(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "proxies"
    __table_args__ = (UniqueConstraint("host", "port", name="unique_host_port"),)

    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    protocol: Mapped[ProxyProtocol] = mapped_column(
        Enum(ProxyProtocol, name="proxy_protocol"),
        default=ProxyProtocol.SOCKS5,
        nullable=False
    )
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    status: Mapped[ProxyStatus] = mapped_column(
        Enum(ProxyStatus, name="proxy_status"),
        default=ProxyStatus.UNCHECKED,
        nullable=False
    )
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    uptime_pct: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)

    # Relationships - 1:1 with account
    account: Mapped[Optional["Account"]] = relationship("Account", back_populates="proxy", uselist=False, lazy="selectin")
