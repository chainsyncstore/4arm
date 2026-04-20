from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from app.models.proxy import ProxyProtocol, ProxyStatus


class ProxyBase(BaseModel):
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: ProxyProtocol = ProxyProtocol.SOCKS5
    country: Optional[str] = None


class ProxyCreate(ProxyBase):
    pass


class ProxyUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: Optional[ProxyProtocol] = None
    country: Optional[str] = None
    status: Optional[ProxyStatus] = None


class ProxyResponse(ProxyBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: ProxyStatus
    ip: Optional[str] = None
    latency_ms: Optional[float] = None
    last_health_check: Optional[datetime] = None
    uptime_pct: float
    linked_account_id: Optional[UUID] = None
    linked_account_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ProxyTestResult(BaseModel):
    healthy: bool
    ip: Optional[str] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None
