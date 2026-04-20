from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from app.models.song import SongPriority, SongStatus


class SongBase(BaseModel):
    spotify_uri: str
    title: Optional[str] = None
    artist: Optional[str] = None
    album_art_url: Optional[str] = None
    total_target_streams: int
    daily_rate: int
    priority: SongPriority = SongPriority.MEDIUM


class SongCreate(SongBase):
    pass


class SongUpdate(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album_art_url: Optional[str] = None
    total_target_streams: Optional[int] = None
    daily_rate: Optional[int] = None
    priority: Optional[SongPriority] = None
    status: Optional[SongStatus] = None
    completed_streams: Optional[int] = None
    streams_today: Optional[int] = None


class SongResponse(SongBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    completed_streams: int
    streams_today: int
    status: SongStatus
    created_at: datetime
    updated_at: datetime
    progress_pct: float = 0.0  # Computed: completed_streams / total_target_streams * 100

    @staticmethod
    def from_orm_with_progress(song) -> "SongResponse":
        response = SongResponse.model_validate(song)
        if song.total_target_streams > 0:
            response.progress_pct = (song.completed_streams / song.total_target_streams) * 100
        else:
            response.progress_pct = 0.0
        return response


class SongETA(BaseModel):
    song_id: UUID
    remaining_streams: int
    estimated_hours: float
    estimated_completion: Optional[datetime] = None
    based_on_current_rate: int  # streams per hour


class PaginatedSongResponse(BaseModel):
    items: List[SongResponse]
    total: int
    skip: int
    limit: int
