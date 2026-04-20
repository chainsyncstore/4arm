"""RateLimiter — multi-level stream caps to stay below Spotify thresholds."""

import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.account import Account
from app.models.instance import Instance
from app.models.setting import Setting
from app.models.song import Song
from app.models.stream_log import StreamLog
from app.services.antidetect.behavior_profiles import BehaviorProfileManager
from app.ws.dashboard import DashboardWebSocketManager

logger = logging.getLogger(__name__)


class RateLimiter:
    """Enforces streaming rate limits at multiple levels."""

    def __init__(
        self,
        db_session_maker: async_sessionmaker,
        ws_manager: Optional[DashboardWebSocketManager] = None,
    ):
        self.db_session_maker = db_session_maker
        self.ws_manager = ws_manager

        # In-memory tracking
        self._account_last_stream: dict[UUID, datetime] = {}
        self._instance_cooldown_until: dict[UUID, datetime] = {}  # Deterministic cooldown expiry
        self._active_streams: set[UUID] = set()  # Instance IDs currently streaming
        self._daily_listen_budget: dict[tuple[UUID, str], int] = {}  # (instance_id, date_str) -> minutes

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    async def can_stream(
        self,
        instance: Instance,
        account: Account,
        song: Song,
        db: AsyncSession,
    ) -> tuple[bool, str]:
        """Check ALL rate limits.  Returns (allowed, reason)."""

        # 1. Global concurrent limit
        max_concurrent = await self._get_setting(db, "max_concurrent_streams", 14)
        if len(self._active_streams) >= max_concurrent:
            self._increment_rate_limit_counter("global_concurrent_limit")
            return False, f"global_concurrent_limit: {len(self._active_streams)}/{max_concurrent}"

        # 2. Per-account daily limit
        max_daily = await self._get_setting(db, "max_streams_per_account_per_day", 40)
        if account.streams_today >= max_daily:
            self._increment_rate_limit_counter("account_daily_limit")
            return False, f"account_daily_limit: {account.streams_today}/{max_daily}"

        # 3. Per-account hourly limit
        max_hourly = await self._get_setting(db, "max_streams_per_account_per_hour", 8)
        hourly_count = await self.get_account_streams_last_hour(account.id, db)
        if hourly_count >= max_hourly:
            self._increment_rate_limit_counter("account_hourly_limit")
            return False, f"account_hourly_limit: {hourly_count}/{max_hourly}"

        # 4. Per-instance cooldown (deterministic — set when stream ends)
        cooldown_until = self._instance_cooldown_until.get(instance.id)
        if cooldown_until is not None:
            now = datetime.now(timezone.utc)
            if now < cooldown_until:
                remaining = (cooldown_until - now).total_seconds()
                self._increment_rate_limit_counter("instance_cooldown")
                return False, (
                    f"instance_cooldown: {remaining:.0f}s remaining"
                )

        # 5. Per-track-per-account daily limit
        max_track = await self._get_setting(
            db, "max_streams_per_track_per_account_per_day", 2
        )
        track_count = await self.get_track_streams_today(account.id, song.id, db)
        if track_count >= max_track:
            self._increment_rate_limit_counter("track_per_account_daily_limit")
            return False, (
                f"track_per_account_daily_limit: {track_count}/{max_track} "
                f"song={song.id}"
            )

        # 6. Behavior profile — active hour
        bp_manager = BehaviorProfileManager()
        profile_name = getattr(instance, "behavior_profile", None)
        if profile_name:
            profile = bp_manager.get_profile(profile_name)
            now_hour = datetime.now(timezone.utc).hour
            if not bp_manager.is_active_hour(profile, now_hour):
                self._increment_rate_limit_counter("behavior_inactive_hour")
                return False, f"behavior_inactive_hour: profile={profile_name} hour={now_hour}"

        # 7. Daily listen budget (approximate — each stream ≈ 3 min)
        if profile_name:
            profile = bp_manager.get_profile(profile_name)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            budget_key = (instance.id, today_str)
            if budget_key not in self._daily_listen_budget:
                self._daily_listen_budget[budget_key] = bp_manager.get_daily_listen_budget(profile)
            budget = self._daily_listen_budget[budget_key]
            approx_listened = account.streams_today * 3  # rough minutes
            if approx_listened >= budget:
                self._increment_rate_limit_counter("daily_listen_budget")
                return False, (
                    f"daily_listen_budget: ~{approx_listened}min/{budget}min "
                    f"profile={profile_name}"
                )

        return True, "ok"

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------

    async def register_stream_start(self, instance_id: UUID, account_id: UUID) -> None:
        """Mark a stream as started."""
        self._active_streams.add(instance_id)
        now = datetime.now(timezone.utc)
        self._account_last_stream[account_id] = now

        # Update Prometheus metric
        try:
            from app.main import ACTIVE_STREAMS
            ACTIVE_STREAMS.set(len(self._active_streams))
        except Exception:
            pass

        logger.debug(
            f"Stream started: instance={instance_id} account={account_id} "
            f"active={len(self._active_streams)}"
        )

    async def register_stream_end(
        self, instance_id: UUID, account_id: UUID,
        cooldown_min_sec: int = 120, cooldown_max_sec: int = 480
    ) -> None:
        """Mark a stream as finished and set deterministic cooldown."""
        self._active_streams.discard(instance_id)
        cooldown_secs = random.randint(cooldown_min_sec, cooldown_max_sec)
        self._instance_cooldown_until[instance_id] = (
            datetime.now(timezone.utc) + timedelta(seconds=cooldown_secs)
        )

        # Update Prometheus metric
        try:
            from app.main import ACTIVE_STREAMS
            ACTIVE_STREAMS.set(len(self._active_streams))
        except Exception:
            pass

        logger.debug(
            f"Stream ended: instance={instance_id} account={account_id} "
            f"active={len(self._active_streams)} cooldown={cooldown_secs}s"
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_account_streams_last_hour(
        self, account_id: UUID, db: AsyncSession
    ) -> int:
        """Query StreamLog for streams by this account in the last 60 minutes."""
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        result = await db.execute(
            select(func.count(StreamLog.id)).where(
                and_(
                    StreamLog.account_id == account_id,
                    StreamLog.started_at >= one_hour_ago,
                )
            )
        )
        return result.scalar_one() or 0

    async def get_track_streams_today(
        self, account_id: UUID, song_id: UUID, db: AsyncSession
    ) -> int:
        """Query StreamLog for streams of this specific song by this account today."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await db.execute(
            select(func.count(StreamLog.id)).where(
                and_(
                    StreamLog.account_id == account_id,
                    StreamLog.song_id == song_id,
                    StreamLog.started_at >= today_start,
                )
            )
        )
        return result.scalar_one() or 0

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def check_threshold_alerts(
        self, account: Account, db: AsyncSession
    ) -> None:
        """If account is approaching daily limit (>threshold_pct), broadcast warning."""
        max_daily = await self._get_setting(db, "max_streams_per_account_per_day", 40)
        threshold_pct = await self._get_setting(db, "threshold_alert_pct", 80)
        threshold = int(max_daily * threshold_pct / 100)

        if account.streams_today >= threshold and self.ws_manager:
            await self.ws_manager.broadcast_alert(
                "warning",
                f"Account {account.email} approaching daily limit: "
                f"{account.streams_today}/{max_daily} streams "
                f"({int(account.streams_today / max_daily * 100)}%)"
            )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current rate limiter status."""
        return {
            "active_streams": len(self._active_streams),
            "active_stream_instance_ids": [str(i) for i in self._active_streams],
            "tracked_instances": len(self._instance_cooldown_until),
            "tracked_accounts": len(self._account_last_stream),
        }

    # ------------------------------------------------------------------
    # Metrics helper
    # ------------------------------------------------------------------

    def _increment_rate_limit_counter(self, reason: str) -> None:
        """Increment the RATE_LIMIT_BLOCKS Prometheus counter."""
        try:
            from app.main import RATE_LIMIT_BLOCKS
            RATE_LIMIT_BLOCKS.labels(reason=reason).inc()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Setting helper
    # ------------------------------------------------------------------

    async def _get_setting(self, db: AsyncSession, key: str, default: int) -> int:
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            try:
                return int(setting.value)
            except ValueError:
                pass
        return default
