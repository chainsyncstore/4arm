import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.song import Song, SongStatus, SongPriority
from app.schemas.song import SongCreate, SongResponse, SongUpdate, SongETA, PaginatedSongResponse
from app.services.song_service import SongService

router = APIRouter(prefix="/api/songs", tags=["songs"])


def get_song_service(db: AsyncSession = Depends(get_db)) -> SongService:
    return SongService(db)


@router.get("/", response_model=PaginatedSongResponse)
async def list_songs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[SongStatus] = None,
    priority: Optional[SongPriority] = None,
    db: AsyncSession = Depends(get_db)
) -> PaginatedSongResponse:
    """List all songs with optional filters."""
    # Count query
    count_query = select(func.count(Song.id))
    if status:
        count_query = count_query.where(Song.status == status)
    if priority:
        count_query = count_query.where(Song.priority == priority)

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Data query
    query = select(Song)
    if status:
        query = query.where(Song.status == status)
    if priority:
        query = query.where(Song.priority == priority)
    query = query.order_by(Song.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    songs = result.scalars().all()

    # Build response with computed progress
    responses = []
    for song in songs:
        resp = SongResponse.model_validate(song)
        if song.total_target_streams > 0:
            resp.progress_pct = (song.completed_streams / song.total_target_streams) * 100
        else:
            resp.progress_pct = 0.0
        responses.append(resp)

    return PaginatedSongResponse(
        items=responses,
        total=total,
        skip=skip,
        limit=limit
    )


@router.post("/", response_model=SongResponse)
async def create_song(
    data: SongCreate,
    service: SongService = Depends(get_song_service)
) -> SongResponse:
    """Create a new song."""
    # Check for duplicate URI
    existing = await service.get_song_by_uri(data.spotify_uri)
    if existing:
        raise HTTPException(status_code=409, detail="Song with this Spotify URI already exists")

    song = await service.create_song(data)
    resp = SongResponse.model_validate(song)
    if song.total_target_streams > 0:
        resp.progress_pct = (song.completed_streams / song.total_target_streams) * 100
    else:
        resp.progress_pct = 0.0
    return resp


@router.get("/{song_id}", response_model=SongResponse)
async def get_song(
    song_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> SongResponse:
    """Get song details."""
    result = await db.execute(select(Song).where(Song.id == song_id))
    song = result.scalar_one_or_none()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    resp = SongResponse.model_validate(song)
    if song.total_target_streams > 0:
        resp.progress_pct = (song.completed_streams / song.total_target_streams) * 100
    else:
        resp.progress_pct = 0.0

    return resp


@router.patch("/{song_id}", response_model=SongResponse)
async def update_song(
    song_id: uuid.UUID,
    data: SongUpdate,
    service: SongService = Depends(get_song_service)
) -> SongResponse:
    """Update song fields."""
    try:
        song = await service.update_song(song_id, data)
        resp = SongResponse.model_validate(song)
        if song.total_target_streams > 0:
            resp.progress_pct = (song.completed_streams / song.total_target_streams) * 100
        else:
            resp.progress_pct = 0.0
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{song_id}")
async def delete_song(
    song_id: uuid.UUID,
    service: SongService = Depends(get_song_service)
) -> dict:
    """Delete a song."""
    try:
        await service.delete_song(song_id)
        return {"message": "Song deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{song_id}/pause")
async def pause_song(
    song_id: uuid.UUID,
    service: SongService = Depends(get_song_service)
) -> SongResponse:
    """Pause a song."""
    try:
        song = await service.pause_song(song_id)
        resp = SongResponse.model_validate(song)
        if song.total_target_streams > 0:
            resp.progress_pct = (song.completed_streams / song.total_target_streams) * 100
        else:
            resp.progress_pct = 0.0
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{song_id}/resume")
async def resume_song(
    song_id: uuid.UUID,
    service: SongService = Depends(get_song_service)
) -> SongResponse:
    """Resume a paused song."""
    try:
        song = await service.resume_song(song_id)
        resp = SongResponse.model_validate(song)
        if song.total_target_streams > 0:
            resp.progress_pct = (song.completed_streams / song.total_target_streams) * 100
        else:
            resp.progress_pct = 0.0
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{song_id}/eta", response_model=SongETA)
async def get_song_eta(
    song_id: uuid.UUID,
    service: SongService = Depends(get_song_service)
) -> SongETA:
    """Get estimated time to completion for a song."""
    try:
        return await service.calculate_eta(song_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/eta/summary")
async def get_eta_summary(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get batch ETA for all active songs."""
    from app.services.song_estimator import SongEstimator

    estimator = SongEstimator(db_session_maker=None)
    eta_list = await estimator.estimate_all(db)

    return {
        "songs": eta_list,
        "total_active": len(eta_list),
        "generated_at": datetime.now().isoformat()
    }
