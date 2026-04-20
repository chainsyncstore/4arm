"""Song ETA Estimator - Predicts time-to-completion for songs."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.song import Song, SongStatus
from app.models.instance import Instance, InstanceStatus
from app.models.stream_log import StreamLog, StreamResult
from app.models.account import Account, AccountStatus

logger = logging.getLogger(__name__)


class SongEstimator:
    """Estimates completion time for songs based on current throughput."""

    def __init__(self, db_session_maker):
        self.db_session_maker = db_session_maker

    async def estimate_eta(self, song_id: uuid.UUID, db: AsyncSession) -> dict:
        """Calculate ETA for a song.

        1. Get song's remaining_streams = total_target_streams - completed_streams
        2. Calculate current throughput:
           - Count successful streams in last 24h
           - Divide by number of active instances
           - Factor in daily_rate cap for this song
        3. Calculate daily capacity:
           - active_instances * avg_streams_per_instance_per_day
           - Capped by song.daily_rate
        4. estimated_days = remaining_streams / min(daily_capacity, song.daily_rate)
        5. Return ETA data with confidence and bottleneck analysis
        """
        # Get song
        result = await db.execute(select(Song).where(Song.id == song_id))
        song = result.scalar_one_or_none()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        remaining_streams = max(0, song.total_target_streams - song.completed_streams)

        if remaining_streams == 0:
            return {
                "song_id": str(song_id),
                "remaining_streams": 0,
                "daily_capacity": 0,
                "estimated_days": 0.0,
                "estimated_completion": datetime.now(timezone.utc),
                "confidence": "high",
                "bottleneck": "none"
            }

        # Get active instances count
        active_instances_result = await db.execute(
            select(func.count(Instance.id))
            .where(Instance.status == InstanceStatus.RUNNING)
        )
        active_instances = active_instances_result.scalar() or 1

        # Calculate throughput from last 24h
        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        throughput_result = await db.execute(
            select(func.count(StreamLog.id))
            .where(
                and_(
                    StreamLog.started_at >= day_ago,
                    StreamLog.result == StreamResult.SUCCESS
                )
            )
        )
        recent_streams = throughput_result.scalar() or 0

        # Streams per instance per day (avoid div by zero)
        if active_instances > 0 and recent_streams > 0:
            streams_per_instance_per_day = recent_streams / active_instances
            confidence = "high" if recent_streams >= 24 else "medium" if recent_streams >= 10 else "low"
        else:
            # Default assumption: 40 streams per instance per day
            streams_per_instance_per_day = 40
            confidence = "low"

        # Calculate daily capacity
        daily_capacity = int(active_instances * streams_per_instance_per_day)

        # Effective daily rate (capped by song's daily_rate)
        effective_daily_rate = min(daily_capacity, song.daily_rate)

        # Calculate estimated days
        if effective_daily_rate > 0:
            estimated_days = remaining_streams / effective_daily_rate
        else:
            estimated_days = float('inf')

        # Determine bottleneck
        if daily_capacity >= song.daily_rate:
            bottleneck = "daily_rate_cap"
        elif active_instances == 0:
            bottleneck = "instance_capacity"
        else:
            # Check account limits
            active_accounts_result = await db.execute(
                select(func.count(Account.id))
                .where(Account.status == AccountStatus.ACTIVE)
            )
            active_accounts = active_accounts_result.scalar() or 0
            if active_accounts < active_instances:
                bottleneck = "account_limit"
            else:
                bottleneck = "instance_capacity"

        estimated_completion = None
        if estimated_days != float('inf'):
            estimated_completion = datetime.now(timezone.utc) + timedelta(days=estimated_days)

        return {
            "song_id": str(song_id),
            "remaining_streams": remaining_streams,
            "daily_capacity": daily_capacity,
            "estimated_days": round(estimated_days, 2),
            "estimated_completion": estimated_completion,
            "confidence": confidence,
            "bottleneck": bottleneck
        }

    async def estimate_all(self, db: AsyncSession) -> list[dict]:
        """Batch ETA for all active songs."""
        result = await db.execute(
            select(Song).where(Song.status == SongStatus.ACTIVE)
        )
        songs = result.scalars().all()

        eta_list = []
        for song in songs:
            try:
                eta = await self.estimate_eta(song.id, db)
                eta_list.append(eta)
            except Exception as e:
                logger.warning(f"Failed to estimate ETA for song {song.id}: {e}")

        return eta_list
