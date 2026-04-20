"""Health Monitor - Instance/app crash detection and recovery."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Set
from collections import defaultdict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, and_

from app.models.instance import Instance, InstanceStatus
from app.models.account import Account, AccountStatus
from app.models.stream_log import StreamLog, StreamResult
from app.models.alert import AlertSeverity
from app.services.adb_service import ADBService
from app.services.automation.spotify_controller import SpotifyController
from app.services.automation.account_rotator import AccountRotator
from app.config import settings
from app.ws.dashboard import DashboardWebSocketManager

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitors instance health and recovers from crashes.

    Runs health checks every 60 seconds:
    - Check if Spotify is running
    - Check if UI is responsive
    - Restart/recover on failures
    - Alert on repeated failures
    """

    def __init__(
        self,
        db_session_maker: async_sessionmaker,
        ws_manager: DashboardWebSocketManager = None
    ):
        self.db_session_maker = db_session_maker
        self.ws_manager = ws_manager
        self.scheduler = AsyncIOScheduler()
        self.mock_mode = settings.MOCK_ADB

        # Track failures per instance (instance_id -> list of timestamps)
        self.failure_history: Dict[str, List[datetime]] = defaultdict(list)
        self.max_failures = 3  # Max failures in 10 minutes before marking error
        self.failure_window = timedelta(minutes=10)

    def start(self):
        """Register health check job (interval: 60 seconds)."""
        self.scheduler.add_job(
            self._health_check_tick,
            IntervalTrigger(seconds=60),
            id="health_check",
            replace_existing=True,
            max_instances=1
        )
        self.scheduler.start()
        logger.info("HealthMonitor started (check interval: 60s)")

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=True)
        logger.info("HealthMonitor stopped")

    async def _health_check_tick(self):
        """
        Core health check loop.

        For each instance WHERE status='running':
        1. Check if Spotify is running (adb.is_app_running)
        2. Check if UI is responsive (adb.get_screen_xml)
        3. On app crash: restart Spotify, re-inject session, resume
        4. On container unresponsive: restart instance pod
        5. On repeated failures (>3 in 10 min): mark instance as 'error', alert
        6. Log all health events to stream_logs with result='health_check'
        """
        if self.mock_mode:
            # In mock mode, always report healthy
            logger.debug("MOCK: Health check tick (all instances healthy)")
            return

        async with self.db_session_maker() as db:
            try:
                # Get all running instances with their accounts
                result = await db.execute(
                    select(Instance, Account)
                    .join(Account, Instance.assigned_account_id == Account.id, isouter=True)
                    .where(Instance.status == InstanceStatus.RUNNING)
                )

                for instance, account in result.all():
                    await self._check_instance(db, instance, account)

            except Exception as e:
                logger.error(f"Error in health check tick: {e}")

    async def _check_instance(
        self,
        db: AsyncSession,
        instance: Instance,
        account: Account
    ):
        """Check health of a single instance."""
        device_id = f"localhost:{instance.adb_port}" if instance.adb_port else "mock-device"
        adb = ADBService()

        health_event = None
        recovery_needed = False

        try:
            # 1. Check if Spotify is running
            is_running = await adb.is_app_running(device_id, "com.spotify.music")

            if not is_running:
                logger.warning(f"Spotify not running on {instance.name}")
                health_event = "spotify_not_running"
                recovery_needed = True

                # Try to recover: restart Spotify
                if await self._recover_spotify(db, instance, account, adb):
                    health_event = "spotify_recovered"
                else:
                    health_event = "spotify_recovery_failed"

            # 2. Check UI responsiveness (if Spotify was running)
            if not recovery_needed and is_running:
                try:
                    xml = await adb.get_screen_xml(device_id)
                    if not xml or len(xml) < 100:
                        logger.warning(f"UI unresponsive on {instance.name}")
                        health_event = "ui_unresponsive"
                        recovery_needed = True
                except Exception as e:
                    logger.warning(f"Failed to get UI dump from {instance.name}: {e}")
                    health_event = "ui_check_failed"
                    recovery_needed = True

            # Log health check
            await self._log_health_check(db, instance, account, health_event or "healthy")

            # Track failures
            if recovery_needed:
                await self._track_failure(db, instance, health_event)

        except Exception as e:
            logger.error(f"Health check failed for {instance.name}: {e}")
            await self._track_failure(db, instance, f"check_exception: {str(e)[:50]}")

    async def _recover_spotify(
        self,
        db: AsyncSession,
        instance: Instance,
        account: Account,
        adb: ADBService
    ) -> bool:
        """
        Attempt to recover Spotify on an instance.

        Steps:
        1. Force stop Spotify
        2. Re-inject session if account exists
        3. Relaunch Spotify
        4. Verify it's running
        """
        device_id = f"localhost:{instance.adb_port}" if instance.adb_port else "mock-device"

        try:
            logger.info(f"Attempting Spotify recovery on {instance.name}")

            # Force stop
            await adb.force_stop(device_id, "com.spotify.music")
            await asyncio.sleep(1)

            # Re-inject session if we have an account with session
            if account and account.session_blob_path:
                try:
                    await adb.inject_session(device_id, session_dir=account.session_blob_path)
                    logger.info(f"Re-injected session for {account.email}")
                except Exception as e:
                    logger.warning(f"Failed to re-inject session: {e}")

            # Relaunch
            spotify = SpotifyController(adb)
            if await spotify.launch_spotify(device_id):
                # Verify it's running
                await asyncio.sleep(2)
                is_running = await adb.is_app_running(device_id, "com.spotify.music")

                if is_running:
                    logger.info(f"Spotify recovery successful on {instance.name}")
                    return True

            logger.warning(f"Spotify recovery failed on {instance.name}")
            return False

        except Exception as e:
            logger.error(f"Error during Spotify recovery on {instance.name}: {e}")
            return False

    async def _recover_instance(self, db: AsyncSession, instance: Instance):
        """
        Recover an unresponsive instance by restarting the pod.

        This would restart the Docker container in production.
        """
        from app.services.instance_manager import InstanceManager

        logger.warning(f"Attempting instance recovery for {instance.name}")

        try:
            manager = InstanceManager(db)
            await manager.restart_instance(instance.id)
            logger.info(f"Instance {instance.name} restarted successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to restart instance {instance.name}: {e}")
            return False

    async def _track_failure(
        self,
        db: AsyncSession,
        instance: Instance,
        failure_type: str
    ):
        """Track failure and alert if threshold reached."""
        now = datetime.now(timezone.utc)
        instance_id_str = str(instance.id)

        # Add failure to history
        self.failure_history[instance_id_str].append(now)

        # Clean old failures outside window
        cutoff = now - self.failure_window
        self.failure_history[instance_id_str] = [
            t for t in self.failure_history[instance_id_str] if t > cutoff
        ]

        failure_count = len(self.failure_history[instance_id_str])

        # If repeated failures, mark instance as error
        if failure_count >= self.max_failures:
            logger.error(
                f"Instance {instance.name} has {failure_count} failures in 10min, "
                f"marking as error"
            )

            instance.status = InstanceStatus.ERROR
            await db.commit()

            # Alert dashboard
            if self.ws_manager:
                await self.ws_manager.broadcast_alert(
                    "error",
                    f"Instance {instance.name} marked as error after {failure_count} failures"
                )

                # Broadcast status update
                await self.ws_manager.broadcast_instance_status(
                    instance_id=instance_id_str,
                    status=InstanceStatus.ERROR.value,
                    account_email=instance.assigned_account.email if instance.assigned_account else None,
                    current_track=None
                )

            # Send critical alert via AlertingService if available
            try:
                from app.main import alerting_service
                if alerting_service:
                    await alerting_service.send_alert(
                        severity=AlertSeverity.CRITICAL,
                        title=f"Instance {instance.name} Error",
                        message=f"Instance has been marked as ERROR after {failure_count} health check failures in 10 minutes. Failure type: {failure_type}",
                        db=db
                    )
            except Exception as e:
                logger.warning(f"Failed to send critical alert: {e}")

    async def _log_health_check(
        self,
        db: AsyncSession,
        instance: Instance,
        account: Account,
        event: str
    ):
        """Log health check event to stream_logs."""
        try:
            log = StreamLog(
                instance_id=instance.id,
                account_id=account.id if account else None,
                song_id=None,
                spotify_uri="health_check",
                started_at=datetime.now(timezone.utc),
                duration_sec=0,
                verified=True,
                result=StreamResult.HEALTH_CHECK,
                failure_reason=event if event != "healthy" else None
            )
            db.add(log)
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to log health check: {e}")

    def get_status(self) -> dict:
        """Get current health monitor status."""
        return {
            "running": self.scheduler.running,
            "mock_mode": self.mock_mode,
            "instances_with_failures": len(self.failure_history),
            "failure_threshold": self.max_failures,
            "failure_window_minutes": self.failure_window.total_seconds() / 60
        }
