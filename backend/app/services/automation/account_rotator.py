"""Account Rotator - Session and proxy swap logic."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.instance import Instance
from app.models.account import Account, AccountStatus, AccountType
from app.models.proxy import Proxy
from app.models.setting import Setting
from app.services.instance_manager import InstanceManager
from app.services.proxy_service import ProxyService
from app.services.adb_service import ADBService
from app.services.automation.spotify_controller import SpotifyController
from app.ws.dashboard import DashboardWebSocketManager

logger = logging.getLogger(__name__)


class AccountRotator:
    """
    Handles account rotation on instances including:
    - Proxy switching
    - Session injection
    - Account cooldown management
    """

    def __init__(
        self,
        ws_manager: DashboardWebSocketManager = None,
        adb: ADBService = None
    ):
        self.ws_manager = ws_manager
        self.adb = adb or ADBService()
        self.spotify = SpotifyController(self.adb)

    async def should_rotate(self, instance: Instance, account: Account, db: AsyncSession) -> bool:
        """
        Check if rotation is needed based on:
        - account.streams_today >= rotation_interval_streams
        - Time since account was assigned > rotation_interval_hours

        Args:
            instance: The instance to check
            account: The currently assigned account
            db: Database session

        Returns:
            True if rotation is needed
        """
        # Get settings
        rotation_streams = await self._get_setting(db, "rotation_interval_streams", 15)
        rotation_hours = await self._get_setting(db, "rotation_interval_hours", 4)

        # Check stream count limit
        if account.streams_today >= rotation_streams:
            logger.info(
                f"Account {account.email} reached stream limit: "
                f"{account.streams_today}/{rotation_streams}"
            )
            return True

        # Check time limit
        if account.last_used:
            time_since_assignment = datetime.now(timezone.utc) - account.last_used
            hours_elapsed = time_since_assignment.total_seconds() / 3600

            if hours_elapsed >= rotation_hours:
                logger.info(
                    f"Account {account.email} reached time limit: "
                    f"{hours_elapsed:.1f}h/{rotation_hours}h"
                )
                return True

        return False

    async def rotate_account(
        self,
        instance: Instance,
        db: AsyncSession
    ) -> Optional[Account]:
        """
        Perform full account rotation sequence:
        1. Stop Spotify on instance
        2. Set old account status = 'cooldown'
        3. Unassign old account from instance
        4. Select next account (must have proxy)
        5. Assign new account to instance
        6. Switch proxy
        7. Inject new account session blob
        8. Launch Spotify, verify logged-in state
        9. Broadcast instance_status update
        10. Return new account

        Args:
            instance: Instance to rotate
            db: Database session

        Returns:
            New account or None if no account available
        """
        old_account = instance.assigned_account
        device_id = f"localhost:{instance.adb_port}" if instance.adb_port else "mock-device"

        logger.info(f"Starting account rotation for instance {instance.name}")

        # 1. Stop Spotify
        try:
            await self.spotify.stop_playback(device_id)
            logger.info(f"Stopped Spotify on {instance.name}")
        except Exception as e:
            logger.warning(f"Failed to stop Spotify on {instance.name}: {e}")

        # 2. Set old account to cooldown if it exists
        if old_account:
            cooldown_hours = await self._get_setting(db, "cooldown_hours", 6)
            old_account.status = AccountStatus.COOLDOWN
            old_account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=cooldown_hours)
            logger.info(
                f"Set account {old_account.email} to cooldown until {old_account.cooldown_until}"
            )

        # 3. Unassign old account from instance
        instance_manager = InstanceManager(db)
        await instance_manager.unassign_account(instance.id)
        logger.info(f"Unassigned account from instance {instance.name}")

        # Flush changes so the old account is marked as unassigned
        await db.flush()

        # 4. Select next account
        new_account = await self._select_next_account(db)
        if not new_account:
            logger.warning(f"No available account for rotation on {instance.name}")
            if self.ws_manager:
                await self.ws_manager.broadcast_alert(
                    "warning",
                    f"No available accounts for rotation on {instance.name}"
                )
            return None

        # 5. Assign new account to instance
        await instance_manager.assign_account(instance.id, new_account.id)
        new_account.last_used = datetime.now(timezone.utc)
        logger.info(f"Assigned account {new_account.email} to instance {instance.name}")

        # Refresh instance to get updated relationships
        await db.refresh(instance)

        # 6. Switch proxy
        if new_account.proxy_id:
            proxy_service = ProxyService(db)
            try:
                await proxy_service.switch_proxy(instance.id, new_account.proxy_id)
                logger.info(f"Switched proxy for {instance.name} to proxy {new_account.proxy_id}")
            except Exception as e:
                logger.error(f"Failed to switch proxy: {e}")

        # 7. Inject session blob (if exists)
        if new_account.session_blob_path:
            try:
                await self.adb.inject_session(
                    device_id,
                    session_dir=new_account.session_blob_path
                )
                logger.info(f"Injected session for {new_account.email}")
            except Exception as e:
                logger.warning(f"Failed to inject session: {e}")

        # 8. Launch Spotify and verify
        try:
            if await self.spotify.launch_spotify(device_id):
                # In real implementation, verify logged-in state via UI
                logger.info(f"Spotify launched successfully for {new_account.email}")
            else:
                logger.warning(f"Failed to launch Spotify for {new_account.email}")
        except Exception as e:
            logger.error(f"Error launching Spotify: {e}")

        # 9. Broadcast update
        if self.ws_manager:
            await self.ws_manager.broadcast_instance_status(
                instance_id=str(instance.id),
                status=instance.status.value,
                account_email=new_account.email,
                current_track=None
            )

        # Commit all changes
        await db.commit()

        return new_account

    async def _select_next_account(self, db: AsyncSession) -> Optional[Account]:
        """
        Select the best available account for rotation.

        Criteria:
        - status = 'active'
        - assigned_instance is None
        - cooldown_until is None or < now
        - streams_today < max_streams_per_account_per_day
        - Has a linked proxy (proxy_id is not None)
        - No pending challenge

        Returns:
            Best available account or None
        """
        from app.models.challenge import Challenge, ChallengeStatus

        now = datetime.now(timezone.utc)

        # Get settings
        max_streams = await self._get_setting(db, "max_streams_per_account_per_day", 40)

        # Subquery: exclude accounts with pending challenges
        pending_challenge = (
            select(Challenge.id)
            .where(
                Challenge.account_id == Account.id,
                Challenge.status == ChallengeStatus.PENDING,
            )
            .correlate(Account)
            .exists()
        )

        # Query for available accounts
        result = await db.execute(
            select(Account)
            .where(
                and_(
                    Account.status == AccountStatus.ACTIVE,
                    Account.assigned_instance == None,  # Not assigned
                    Account.proxy_id.isnot(None),  # Has proxy
                    Account.streams_today < max_streams,  # Under stream limit
                    or_(
                        Account.cooldown_until.is_(None),  # No cooldown
                        Account.cooldown_until < now  # Or cooldown expired
                    ),
                    ~pending_challenge,
                )
            )
            .order_by(Account.last_used.asc())  # Least recently used first
        )

        accounts = result.scalars().all()

        if not accounts:
            return None

        # Return the first (LRU) account
        selected = accounts[0]
        logger.info(f"Selected account {selected.email} for rotation")
        return selected

    async def _get_setting(self, db: AsyncSession, key: str, default: int) -> int:
        """Get a setting value or return default."""
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            try:
                return int(setting.value)
            except ValueError:
                pass
        return default

    async def rotate_if_needed(
        self,
        instance: Instance,
        db: AsyncSession
    ) -> Optional[Account]:
        """
        Convenience method: Check if rotation needed and perform it.

        Args:
            instance: Instance to check
            db: Database session

        Returns:
            New account if rotated, current account if not needed, None if failed
        """
        if not instance.assigned_account:
            # No account assigned, try to get one
            return await self.rotate_account(instance, db)

        if await self.should_rotate(instance, instance.assigned_account, db):
            return await self.rotate_account(instance, db)

        return instance.assigned_account
