from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from app.models.stream_log import StreamResult


class StreamLogCreate(BaseModel):
    instance_id: Optional[UUID] = None
    account_id: Optional[UUID] = None
    song_id: Optional[UUID] = None
    spotify_uri: str
    started_at: datetime
    duration_sec: int = 0
    verified: bool = False
    result: StreamResult
    failure_reason: Optional[str] = None


class StreamLogResponse(StreamLogCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    # Enriched display fields (populated from joined relationships)
    instance_name: Optional[str] = None
    account_email: Optional[str] = None
    song_title: Optional[str] = None


class StreamLogSummary(BaseModel):
    total_streams: int
    success_rate: float
    avg_duration: float
    streams_today: int
    failed_streams: int


class PaginatedStreamLogResponse(BaseModel):
    items: List[StreamLogResponse]
    total: int
    skip: int
    limit: int
