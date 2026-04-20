from typing import Optional
from typing import List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.account import AccountType, AccountStatus


class AccountBase(BaseModel):
    email: EmailStr
    display_name: Optional[str] = None
    type: AccountType = AccountType.FREE


class AccountCreate(AccountBase):
    password: Optional[str] = None
    proxy_id: Optional[UUID] = None


class AccountUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    type: Optional[AccountType] = None
    status: Optional[AccountStatus] = None
    proxy_id: Optional[UUID] = None


class AccountImport(BaseModel):
    csv_content: str  # Base64 encoded CSV


class AccountResponse(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_blob_path: Optional[str] = None
    proxy_id: Optional[UUID] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    fingerprint_id: Optional[str] = None
    status: AccountStatus
    warmup_day: int
    cooldown_until: Optional[datetime] = None
    last_used: Optional[datetime] = None
    total_streams: int
    streams_today: int
    assigned_instance_id: Optional[UUID] = None
    assigned_instance_name: Optional[str] = None
    password: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PaginatedAccountResponse(BaseModel):
    items: List[AccountResponse]
    total: int
    skip: int
    limit: int
