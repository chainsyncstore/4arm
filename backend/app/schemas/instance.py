from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.models.instance import InstanceStatus


class InstanceBase(BaseModel):
    name: str
    ram_limit_mb: int = 2048
    cpu_cores: float = 2.0


class InstanceCreate(InstanceBase):
    pass


class InstanceUpdate(BaseModel):
    name: Optional[str] = None
    ram_limit_mb: Optional[int] = None
    cpu_cores: Optional[float] = None
    status: Optional[InstanceStatus] = None


class InstanceResponse(InstanceBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    docker_id: Optional[str] = None
    # Alias for frontend compatibility (maps docker_id to container_id)
    container_id: Optional[str] = Field(None, alias="docker_id")
    redsocks_container_id: Optional[str] = None
    status: InstanceStatus
    adb_port: Optional[int] = None
    # Alias port to adb_port for frontend compatibility
    port: Optional[int] = Field(None, alias="adb_port")
    assigned_account_id: Optional[UUID] = None
    assigned_account_email: Optional[str] = None
    assigned_proxy_host: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PaginatedInstanceResponse(BaseModel):
    items: List[InstanceResponse]
    total: int
    skip: int
    limit: int
