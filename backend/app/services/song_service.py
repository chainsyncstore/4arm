import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.song import Song, SongStatus, SongPriority
from app.schemas.song import SongCreate, SongUpdate, SongETA

logger = logging.getLogger(__name__)


class SongService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_song(self, data: SongCreate) -> Song:
        """Create a new song."""
        song = Song(
            spotify_uri=data.spotify_uri,
            title=data.title,
            artist=data.artist,
            album_art_url=data.album_art_url,
            total_target_streams=data.total_target_streams,
            daily_rate=data.daily_rate,
            priority=data.priority,
            status=SongStatus.ACTIVE,
            completed_streams=0,
            streams_today=0
        )
        self.db.add(song)
        await self.db.commit()
        await self.db.refresh(song)
        logger.info(f"Created song {song.title or song.spotify_uri}")
        return song

    async def get_song(self, song_id: uuid.UUID) -> Optional[Song]:
        """Get song by ID."""
        result = await self.db.execute(
            select(Song).where(Song.id == song_id)
        )
        return result.scalar_one_or_none()

    async def get_song_by_uri(self, spotify_uri: str) -> Optional[Song]:
        """Get song by Spotify URI."""
        result = await self.db.execute(
            select(Song).where(Song.spotify_uri == spotify_uri)
        )
        return result.scalar_one_or_none()

    async def update_song(self, song_id: uuid.UUID, data: SongUpdate) -> Song:
        """Update song fields."""
        result = await self.db.execute(
            select(Song).where(Song.id == song_id)
        )
        song = result.scalar_one_or_none()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(song, field, value)

        # Auto-update status if target reached
        if song.completed_streams >= song.total_target_streams:
            song.status = SongStatus.COMPLETED

        song.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(song)
        logger.info(f"Updated song {song.title or song.spotify_uri}")
        return song

    async def pause_song(self, song_id: uuid.UUID) -> Song:
        """Pause a song."""
        result = await self.db.execute(
            select(Song).where(Song.id == song_id)
        )
        song = result.scalar_one_or_none()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        song.status = SongStatus.PAUSED
        await self.db.commit()
        await self.db.refresh(song)
        logger.info(f"Paused song {song.title or song.spotify_uri}")
        return song

    async def resume_song(self, song_id: uuid.UUID) -> Song:
        """Resume a paused song."""
        result = await self.db.execute(
            select(Song).where(Song.id == song_id)
        )
        song = result.scalar_one_or_none()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        if song.completed_streams >= song.total_target_streams:
            song.status = SongStatus.COMPLETED
        else:
            song.status = SongStatus.ACTIVE

        await self.db.commit()
        await self.db.refresh(song)
        logger.info(f"Resumed song {song.title or song.spotify_uri}")
        return song

    async def delete_song(self, song_id: uuid.UUID) -> bool:
        """Delete a song."""
        result = await self.db.execute(
            select(Song).where(Song.id == song_id)
        )
        song = result.scalar_one_or_none()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        await self.db.delete(song)
        await self.db.commit()
        logger.info(f"Deleted song {song.title or song.spotify_uri}")
        return True

    async def calculate_eta(self, song_id: uuid.UUID) -> SongETA:
        """Calculate estimated time to completion for a song."""
        result = await self.db.execute(
            select(Song).where(Song.id == song_id)
        )
        song = result.scalar_one_or_none()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        remaining = song.total_target_streams - song.completed_streams
        if remaining <= 0:
            return SongETA(
                song_id=song.id,
                remaining_streams=0,
                estimated_hours=0,
                estimated_completion=datetime.now(timezone.utc),
                based_on_current_rate=0
            )

        # Get current system throughput from recent stream logs
        from app.models.stream_log import StreamLog
        from app.models.stream_log import StreamResult

        # Calculate streams per hour from last 24 hours
        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        throughput_result = await self.db.execute(
            select(func.count(StreamLog.id))
            .where(
                and_(
                    StreamLog.started_at >= day_ago,
                    StreamLog.result == StreamResult.SUCCESS
                )
            )
        )
        recent_streams = throughput_result.scalar() or 0

        # Calculate streams per hour
        if recent_streams > 0:
            streams_per_hour = recent_streams / 24
        else:
            # Default assumption: 10 streams per hour
            streams_per_hour = 10

        # Calculate ETA
        estimated_hours = remaining / streams_per_hour if streams_per_hour > 0 else float('inf')
        estimated_completion = datetime.now(timezone.utc) + timedelta(hours=estimated_hours)

        return SongETA(
            song_id=song.id,
            remaining_streams=remaining,
            estimated_hours=round(estimated_hours, 1),
            estimated_completion=estimated_completion,
            based_on_current_rate=int(streams_per_hour)
        )

    async def reset_daily_streams(self) -> int:
        """Reset streams_today to 0 for all songs. Called at daily_reset_hour."""
        result = await self.db.execute(select(Song))
        songs = result.scalars().all()

        count = 0
        for song in songs:
            if song.streams_today > 0:
                song.streams_today = 0
                count += 1

        await self.db.commit()
        logger.info(f"Reset daily streams for {count} songs")
        return count
