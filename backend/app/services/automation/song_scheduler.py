"""Song Scheduler - Brain of the system. Assigns songs to available instances."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Set, Dict, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, and_, or_, desc, case, func, exists

from app.models.instance import Instance, InstanceStatus
from app.models.account import Account, AccountStatus
from app.models.song import Song, SongStatus, SongPriority
from app.models.stream_log import StreamLog, StreamResult
from app.models.setting import Setting
from app.services.automation.spotify_controller import SpotifyController
from app.services.automation.humanizer import Humanizer
from app.services.automation.stream_worker import StreamWorker
from app.services.automation.account_rotator import AccountRotator
from app.services.humanization_config import HumanizationConfigService
from app.services.adb_service import ADBService
from app.services.antidetect.rate_limiter import RateLimiter
from app.services.antidetect.warmup import WarmupManager
from app.config import settings
from app.models.challenge import Challenge, ChallengeStatus
from app.ws.dashboard import DashboardWebSocketManager

logger = logging.getLogger(__name__)


class SongScheduler:
    """
    Core scheduling engine that assigns songs to available instances.

    Runs as an APScheduler background job every 30 seconds.
    """

    def __init__(
        self,
        db_session_maker: async_sessionmaker,
        ws_manager: DashboardWebSocketManager = None,
        rate_limiter: RateLimiter = None
    ):
        self.db_session_maker = db_session_maker
        self.ws_manager = ws_manager
        self.scheduler = AsyncIOScheduler()
        self.mock_mode = settings.MOCK_ADB

        # Track active stream tasks
        self.active_tasks: Set[asyncio.Task] = set()
        self.instance_busy: Set[uuid.UUID] = set()  # Instances currently streaming

        # Rate limiter
        self.rate_limiter = rate_limiter

        # Warmup manager
        self.warmup_manager = WarmupManager(ws_manager=self.ws_manager)

        # Statistics
        self.stats = {
            "total_streams_completed": 0,
            "total_streams_failed": 0,
            "last_tick_time": None,
            "scheduler_state": "stopped"
        }

    def start(self):
        """Register the scheduling job (interval: 30 seconds) and start scheduler."""
        self.scheduler.add_job(
            self._scheduling_tick,
            IntervalTrigger(seconds=30),
            id="scheduling_tick",
            replace_existing=True,
            max_instances=1  # Don't overlap ticks
        )

        # Add daily reset job
        self.scheduler.add_job(
            self._daily_reset,
            IntervalTrigger(hours=24),
            id="daily_reset",
            replace_existing=True
        )

        # Add warmup tick job (every 15 minutes)
        self.scheduler.add_job(
            self._warmup_tick,
            IntervalTrigger(minutes=15),
            id="warmup_tick",
            replace_existing=True,
            max_instances=1
        )

        self.scheduler.start()
        self.stats["scheduler_state"] = "running"
        logger.info("SongScheduler started (tick interval: 30s)")

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=True)
        self.stats["scheduler_state"] = "stopped"
        logger.info("SongScheduler stopped")

    def pause(self):
        """Pause scheduling (keep scheduler running but skip ticks)."""
        self.stats["scheduler_state"] = "paused"
        logger.info("SongScheduler paused")

    def resume(self):
        """Resume scheduling."""
        self.stats["scheduler_state"] = "running"
        logger.info("SongScheduler resumed")

    async def _scheduling_tick(self):
        """
        Core scheduling loop executed every 30 seconds.

        1. Query songs WHERE status='active' AND streams_today < daily_rate
        2. Sort by priority (high first), then (daily_rate - streams_today) desc
        3. Find available instances:
           - status='running'
           - has assigned_account (assigned_account_id is not None)
           - assigned_account.status = 'active' or 'warming'
           - NOT currently executing a stream (track via in-memory set)
        4. Check rate limiter before launching streams
        5. Launch stream_worker.execute_stream() as asyncio.Task
        6. On completion callback:
           a. Increment song.completed_streams and song.streams_today
           b. Increment account.streams_today and account.total_streams
           c. Create StreamLog entry
           d. Broadcast stream_completed via WebSocket
           e. If song.completed_streams >= total_target_streams: set status='completed'
           f. Check if account needs rotation
        """
        if self.stats["scheduler_state"] == "paused":
            logger.debug("Scheduler tick skipped (paused)")
            return

        self.stats["last_tick_time"] = datetime.now(timezone.utc).isoformat()
        logger.debug("Scheduler tick started")

        async with self.db_session_maker() as db:
            try:
                # Get settings
                max_streams_per_account = await self._get_setting(
                    db, "max_streams_per_account_per_day", 40
                )
                max_concurrent = await self._get_setting(
                    db, "max_concurrent_streams", 14
                )
                humanization_level = await self._get_setting_str(
                    db, "humanization_level", "medium"
                )

                # 1 & 2. Get eligible songs sorted by priority and need
                songs = await self._get_eligible_songs(db)
                if not songs:
                    logger.debug("No eligible songs")
                    return

                # 3. Get available instances
                instances = await self._get_available_instances(db, max_streams_per_account)
                if not instances:
                    logger.debug("No available instances")
                    return

                # Check concurrent limit
                available_slots = max_concurrent - len(self.active_tasks)
                if available_slots <= 0:
                    logger.debug(f"Max concurrent streams reached ({max_concurrent})")
                    return

                # 4 & 5. Check rate limits and assign songs to instances
                launched = 0
                for instance, account in instances:
                    if launched >= available_slots:
                        break

                    if instance.id in self.instance_busy:
                        continue

                    # Find best song for this instance
                    song = self._select_best_song(songs, account)
                    if not song:
                        continue

                    # Check rate limiter before launching
                    if self.rate_limiter:
                        allowed, reason = await self.rate_limiter.can_stream(
                            instance, account, song, db
                        )
                        if not allowed:
                            logger.debug(f"Rate limited: {reason} (instance={instance.name})")
                            continue

                    # Launch stream
                    self._launch_stream(
                        db, instance, account, song, humanization_level
                    )
                    launched += 1

                if launched > 0:
                    logger.info(f"Launched {launched} streams this tick")

                # Update Prometheus gauges for instance and account counts
                try:
                    from app.main import ACTIVE_INSTANCES, WARMING_ACCOUNTS
                    from app.models.instance import InstanceStatus
                    from app.models.account import AccountStatus

                    # Count running instances
                    running_result = await db.execute(
                        select(Instance).where(Instance.status == InstanceStatus.RUNNING)
                    )
                    running_count = len(running_result.scalars().all())
                    ACTIVE_INSTANCES.set(running_count)

                    # Count warming accounts
                    warming_result = await db.execute(
                        select(Account).where(Account.status == AccountStatus.WARMING)
                    )
                    warming_count = len(warming_result.scalars().all())
                    WARMING_ACCOUNTS.set(warming_count)
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"Error in scheduling tick: {e}")

    async def _get_eligible_songs(self, db: AsyncSession) -> list[Song]:
        """
        Get songs that need streams.

        Criteria:
        - status = 'active'
        - streams_today < daily_rate
        - completed_streams < total_target_streams
        """
        result = await db.execute(
            select(Song)
            .where(
                and_(
                    Song.status == SongStatus.ACTIVE,
                    Song.streams_today < Song.daily_rate,
                    Song.completed_streams < Song.total_target_streams
                )
            )
            .order_by(
                # High priority first (lower number = higher priority)
                case(
                    (Song.priority == SongPriority.HIGH, 0),
                    (Song.priority == SongPriority.MEDIUM, 1),
                    (Song.priority == SongPriority.LOW, 2),
                    else_=3
                ),
                # Then by deficit (daily_rate - streams_today) descending
                (Song.daily_rate - Song.streams_today).desc()
            )
        )
        return result.scalars().all()

    async def _get_available_instances(
        self,
        db: AsyncSession,
        max_streams_per_account: int
    ) -> list[tuple[Instance, Account]]:
        """
        Get instances ready for streaming.

        Criteria:
        - status = 'running'
        - has assigned_account
        - assigned_account.status = 'active'
        - assigned_account.streams_today < max_streams_per_account
        - Not in busy set
        """
        now = datetime.now(timezone.utc)

        # Subqueries: exclude accounts/instances with pending challenges
        pending_for_account = (
            select(Challenge.id)
            .where(
                Challenge.account_id == Account.id,
                Challenge.status == ChallengeStatus.PENDING,
            )
            .correlate(Account)
            .exists()
        )
        pending_for_instance = (
            select(Challenge.id)
            .where(
                Challenge.instance_id == Instance.id,
                Challenge.status == ChallengeStatus.PENDING,
            )
            .correlate(Instance)
            .exists()
        )

        result = await db.execute(
            select(Instance, Account)
            .join(Account, Instance.assigned_account_id == Account.id)
            .where(
                and_(
                    Instance.status == InstanceStatus.RUNNING,
                    Instance.assigned_account_id.isnot(None),
                    Account.status == AccountStatus.ACTIVE,
                    Account.streams_today < max_streams_per_account,
                    or_(
                        Account.cooldown_until.is_(None),
                        Account.cooldown_until < now
                    ),
                    ~pending_for_account,
                    ~pending_for_instance,
                )
            )
        )

        instances_accounts = []
        for instance, account in result.all():
            if instance.id not in self.instance_busy:
                instances_accounts.append((instance, account))

        return instances_accounts

    def _select_best_song(self, songs: list[Song], account: Account) -> Optional[Song]:
        """
        Select the best song for this account.

        For now, just take the first eligible song.
        In future, could implement account-specific targeting.
        """
        if not songs:
            return None

        # Return the first song that still needs streams
        for song in songs:
            if song.streams_today < song.daily_rate:
                return song

        return None

    def _launch_stream(
        self,
        db: AsyncSession,
        instance: Instance,
        account: Account,
        song: Song,
        humanization_level: str
    ):
        """Launch a stream as an async task."""
        # Mark instance as busy
        self.instance_busy.add(instance.id)

        # Register with rate limiter
        if self.rate_limiter:
            asyncio.create_task(
                self.rate_limiter.register_stream_start(instance.id, account.id)
            )

        # Create task
        task = asyncio.create_task(
            self._execute_stream_task(
                instance, account, song, humanization_level
            ),
            name=f"stream-{instance.id}-{song.id}"
        )

        # Track task
        self.active_tasks.add(task)
        task.add_done_callback(
            lambda t: self._on_stream_complete(t, instance.id, account.id, song.id)
        )

        logger.info(
            f"Launched stream task: instance={instance.name}, "
            f"account={account.email}, song={song.spotify_uri}"
        )

    async def _execute_stream_task(
        self,
        instance: Instance,
        account: Account,
        song: Song,
        humanization_level: str
    ):
        """Execute the actual stream with a fresh DB session."""
        async with self.db_session_maker() as db:
            try:
                # Re-fetch objects in this session so changes are tracked
                instance = await db.get(Instance, instance.id)
                account = await db.get(Account, account.id)
                song = await db.get(Song, song.id)

                if not instance or not account or not song:
                    logger.error("Failed to re-fetch instance/account/song in stream task")
                    return None

                # Initialize components
                adb = ADBService()
                spotify = SpotifyController(adb)

                # Phase 9: Load typed config and create Humanizer with it
                humanization_config = await HumanizationConfigService.load_config(db)
                humanizer = Humanizer(humanization_config)
                humanizer.set_mock_mode(self.mock_mode)

                worker = StreamWorker(adb, spotify, self.ws_manager)

                # Execute the stream
                stream_log = await worker.execute_stream(
                    instance, account, song, humanizer, db
                )

                # Persist the stream log
                db.add(stream_log)

                # Update song stats
                if stream_log.result == StreamResult.SUCCESS:
                    song.completed_streams += 1
                    song.streams_today += 1

                    # Check if song completed
                    if song.completed_streams >= song.total_target_streams:
                        song.status = SongStatus.COMPLETED
                        logger.info(f"Song {song.spotify_uri} completed target!")

                        if self.ws_manager:
                            await self.ws_manager.broadcast_alert(
                                "info",
                                f"Song target reached: {song.title or song.spotify_uri}"
                            )

                        # Send alert via AlertingService
                        try:
                            from app.main import alerting_service
                            from app.models.alert import AlertSeverity
                            if alerting_service:
                                await alerting_service.send_alert(
                                    severity=AlertSeverity.INFO,
                                    title="Song Completed",
                                    message=f"Song '{song.title or song.spotify_uri}' has reached its target of {song.total_target_streams} streams!",
                                    db=db
                                )
                        except Exception as e:
                            logger.warning(f"Failed to send song completion alert: {e}")

                elif stream_log.result == StreamResult.SHUFFLE_MISS:
                    # Shuffle miss still counts as a listen for the target
                    song.completed_streams += 1
                    song.streams_today += 1

                # Update account stats
                if stream_log.result in (StreamResult.SUCCESS, StreamResult.SHUFFLE_MISS):
                    account.streams_today += 1
                    account.total_streams += 1
                    account.last_used = datetime.now(timezone.utc)

                await db.commit()

                # Check if account needs rotation
                rotator = AccountRotator(self.ws_manager, adb)
                needs_rotation = await rotator.should_rotate(instance, account, db)
                if needs_rotation:
                    logger.info(f"Account {account.email} needs rotation after stream")
                    # Rotation will happen on next tick

                return stream_log

            except Exception as e:
                logger.error(f"Stream task failed: {e}")
                raise

    def _on_stream_complete(self, task: asyncio.Task, instance_id: uuid.UUID, account_id: uuid.UUID, song_id: uuid.UUID):
        """Handle stream completion."""
        self.active_tasks.discard(task)
        self.instance_busy.discard(instance_id)

        # Unregister from rate limiter
        if self.rate_limiter:
            asyncio.create_task(
                self.rate_limiter.register_stream_end(instance_id, account_id)
            )

        stream_result_label = "fail"
        try:
            result = task.result()
            if result and result.result == StreamResult.SUCCESS:
                self.stats["total_streams_completed"] += 1
                stream_result_label = "success"
            elif result and result.result == StreamResult.SHUFFLE_MISS:
                self.stats["total_streams_completed"] += 1  # Shuffle miss still counts
                stream_result_label = "shuffle_miss"
            else:
                self.stats["total_streams_failed"] += 1
                stream_result_label = result.result.value if result and result.result else "fail"
        except Exception as e:
            logger.error(f"Stream task raised exception: {e}")
            self.stats["total_streams_failed"] += 1
            stream_result_label = "exception"

        # Update Prometheus counter
        try:
            from app.main import STREAMS_TOTAL
            STREAMS_TOTAL.labels(result=stream_result_label).inc()
        except Exception:
            pass

        logger.debug(f"Stream completed for instance {instance_id}, song {song_id}")

    async def _daily_reset(self):
        """
        Reset daily counters.
        Called at daily_reset_hour (default midnight UTC).
        Handles warmup progression for WARMING accounts.
        """
        logger.info("Performing daily reset")

        async with self.db_session_maker() as db:
            from app.services.song_service import SongService

            # Reset all songs' streams_today
            song_service = SongService(db)
            songs_reset = await song_service.reset_daily_streams()

            # Reset all accounts' streams_today
            result = await db.execute(select(Account))
            accounts = result.scalars().all()

            accounts_reset = 0
            for account in accounts:
                if account.streams_today > 0:
                    account.streams_today = 0
                    accounts_reset += 1

            await db.commit()

            logger.info(
                f"Daily reset complete: {songs_reset} songs, {accounts_reset} accounts"
            )

            if self.ws_manager:
                await self.ws_manager.broadcast_alert(
                    "info",
                    f"Daily reset complete: {songs_reset} songs, {accounts_reset} accounts"
                )

    async def _warmup_tick(self):
        """Execute warmup actions for all WARMING accounts that have an assigned instance."""
        if self.stats["scheduler_state"] == "paused":
            return

        async with self.db_session_maker() as db:
            # Query WARMING accounts that have an assigned, running instance
            result = await db.execute(
                select(Instance, Account)
                .join(Account, Instance.assigned_account_id == Account.id)
                .where(
                    and_(
                        Instance.status == InstanceStatus.RUNNING,
                        Account.status == AccountStatus.WARMING,
                        ~(
                            select(Challenge.id)
                            .where(
                                Challenge.account_id == Account.id,
                                Challenge.status == ChallengeStatus.PENDING,
                            )
                            .correlate(Account)
                            .exists()
                        ),
                        ~(
                            select(Challenge.id)
                            .where(
                                Challenge.instance_id == Instance.id,
                                Challenge.status == ChallengeStatus.PENDING,
                            )
                            .correlate(Instance)
                            .exists()
                        ),
                    )
                )
            )

            pairs = result.all()
            if not pairs:
                logger.debug("No WARMING accounts with running instances")
                return

            for instance, account in pairs:
                if instance.id in self.instance_busy:
                    continue

                # Only run warmup once per day per account (check if already done today)
                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                warmup_today = await db.execute(
                    select(func.count(StreamLog.id)).where(
                        and_(
                            StreamLog.account_id == account.id,
                            StreamLog.spotify_uri.like("warmup:%"),
                            StreamLog.started_at >= today_start,
                        )
                    )
                )
                if warmup_today.scalar_one() > 0:
                    continue  # Already did warmup today

                self.instance_busy.add(instance.id)
                try:
                    success = await self.warmup_manager.execute_warmup_day(
                        instance, account, db
                    )
                    await db.commit()
                    if success:
                        logger.info(
                            f"Warmup day {account.warmup_day - 1} completed "
                            f"for {account.email}"
                        )
                except Exception as e:
                    logger.error(f"Warmup tick failed for {account.email}: {e}")
                finally:
                    self.instance_busy.discard(instance.id)

    async def _get_setting(self, db: AsyncSession, key: str, default: int) -> int:
        """Get an integer setting value."""
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            try:
                return int(setting.value)
            except ValueError:
                pass
        return default

    async def _get_setting_str(self, db: AsyncSession, key: str, default: str) -> str:
        """Get a string setting value."""
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        return setting.value if setting else default

    async def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status for API."""
        # Count warmup sessions today
        async with self.db_session_maker() as db:
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            warmup_today = await db.execute(
                select(func.count(StreamLog.id)).where(
                    and_(
                        StreamLog.spotify_uri.like("warmup:%"),
                        StreamLog.started_at >= today_start,
                    )
                )
            )
            warmup_sessions_today = warmup_today.scalar_one()

        return {
            "state": self.stats["scheduler_state"],
            "active_tasks": len(self.active_tasks),
            "busy_instances": len(self.instance_busy),
            "total_streams_completed": self.stats["total_streams_completed"],
            "total_streams_failed": self.stats["total_streams_failed"],
            "last_tick": self.stats["last_tick_time"],
            "warmup_sessions_today": warmup_sessions_today
        }
