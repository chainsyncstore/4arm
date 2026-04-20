from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from app.models.challenge import ChallengeType, ChallengeStatus


class ChallengeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    account_email: Optional[str] = None
    instance_id: Optional[UUID] = None
    instance_name: Optional[str] = None
    type: ChallengeType
    status: ChallengeStatus
    screenshot_path: Optional[str] = None
    resolved_at: Optional[datetime] = None
    expires_at: datetime
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChallengeResolveRequest(BaseModel):
    action: str  # "resolve", "skip", or "fail"
    notes: Optional[str] = None


class PaginatedChallengeResponse(BaseModel):
    items: List[ChallengeResponse]
    total: int
    skip: int
    limit: int
