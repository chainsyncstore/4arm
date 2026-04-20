"""WarmupManager — graduated onboarding sequence for new accounts (3-5 days)."""

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.account import Account, AccountStatus
from app.models.instance import Instance
from app.models.setting import Setting
from app.models.stream_log import StreamLog, StreamResult
from app.services.adb_service import ADBService
from app.services.automation.humanizer import Humanizer
from app.services.automation.spotify_controller import SpotifyController
from app.services.humanization_config import HumanizationConfigService

if TYPE_CHECKING:
    from app.ws.dashboard import DashboardWebSocketManager

logger = logging.getLogger(__name__)


class WarmupManager:
    """Manages the warmup sequence for new accounts."""

    WARMUP_PLANS = {
        1: {
            "actions": ["browse_discover", "follow_playlists", "play_random_tracks"],
            "follow_playlists": 3,
            "play_tracks": 6,
            "max_listen_minutes": 20,
            "description": "Light browsing — follow playlists, play a few tracks",
        },
        2: {
            "actions": ["play_playlist", "save_songs", "explore_artist"],
            "play_tracks": 12,
            "save_songs": 3,
            "explore_artists": 1,
            "max_listen_minutes": 40,
            "description": "Active listening — full playlist, save songs, explore artists",
        },
        3: {
            "actions": ["mixed_session", "follow_artists"],
            "play_tracks": 18,
            "follow_artists": 2,
            "max_listen_minutes": 60,
            "description": "Increasing volume — mixed sessions, follow artists",
        },
        4: {
            "actions": ["full_session"],
            "play_tracks": 25,
            "max_listen_minutes": 80,
            "description": "Near-normal volume — full listening sessions",
        },
        5: {
            "actions": ["full_session"],
            "play_tracks": 30,
            "max_listen_minutes": 100,
            "description": "Full volume — transition to normal streaming",
        },
    }

    def __init__(self, ws_manager: "DashboardWebSocketManager | None" = None):
        self.mock_mode = settings.MOCK_ADB
        self.ws_manager = ws_manager

    async def get_warmup_plan(self, account: Account, db: AsyncSession) -> Optional[dict]:
        """Return today's warmup plan based on account.warmup_day.

        Returns None if warmup is complete.
        """
        warmup_duration = await self._get_warmup_duration(db)

        if account.warmup_day > warmup_duration or account.warmup_day < 1:
            return None

        plan = self.WARMUP_PLANS.get(account.warmup_day)
        if plan is None:
            # Beyond defined plans — use the last defined plan
            plan = self.WARMUP_PLANS[max(self.WARMUP_PLANS.keys())]

        return plan

    async def execute_warmup_day(
        self, instance: Instance, account: Account, db: AsyncSession
    ) -> bool:
        """Execute the warmup plan for today.

        1. Get plan for account.warmup_day
        2. Execute each action via SpotifyController / ADBService
        3. On completion: increment account.warmup_day
        4. If warmup complete: set account.status = ACTIVE
        5. Log warmup activities as StreamLog entries
        """
        plan = await self.get_warmup_plan(account, db)
        if plan is None:
            logger.info(f"Warmup already complete for account {account.email}")
            return False

        device_id = f"localhost:{instance.adb_port}" if instance.adb_port else "localhost:5555"
        adb = ADBService()
        spotify = SpotifyController(adb)

        # Phase 9: Load typed config instead of hardcoding "medium"
        humanization_config = await HumanizationConfigService.load_config(db)
        humanizer = Humanizer(humanization_config)
        humanizer.set_mock_mode(self.mock_mode)

        # Phase 9: Record warmup runs metric
        from app.services.automation.humanizer import HUMANIZATION_WARMUP_RUNS_TOTAL
        HUMANIZATION_WARMUP_RUNS_TOTAL.labels(preset=humanization_config.effective_preset).inc()

        logger.info(
            f"Executing warmup day {account.warmup_day} for account {account.email}: "
            f"{plan['description']}"
        )

        try:
            # Launch Spotify first
            await spotify.launch_spotify(device_id)

            # Pre-plan challenge checkpoint
            challenge_info = await spotify.detect_challenge(device_id)
            if challenge_info:
                logger.warning(
                    f"Challenge detected before warmup plan for {account.email}: "
                    f"{challenge_info['type']}"
                )
                from app.services.challenge_service import handle_detected_challenge
                await handle_detected_challenge(
                    db=db,
                    adb=adb,
                    device_id=device_id,
                    account=account,
                    instance=instance,
                    challenge_type=challenge_info["type"],
                    ws_manager=self.ws_manager,
                )
                return False

            for action in plan["actions"]:
                if action == "browse_discover":
                    await self._browse_discover(device_id, adb, spotify)
                elif action == "follow_playlists":
                    count = plan.get("follow_playlists", 3)
                    await self._follow_playlists(device_id, count, adb, spotify)
                elif action in ("play_random_tracks", "play_playlist", "mixed_session", "full_session"):
                    count = plan.get("play_tracks", 6)
                    await self._play_random_tracks(device_id, count, adb, spotify, humanizer)
                elif action == "save_songs":
                    count = plan.get("save_songs", 2)
                    await self._save_songs(device_id, count, adb)
                elif action == "explore_artist":
                    await self._explore_artist(device_id, adb, spotify)
                elif action == "follow_artists":
                    count = plan.get("follow_artists", 2)
                    await self._follow_artists(device_id, count, adb, spotify)

                # Between-action challenge checkpoint
                challenge_info = await spotify.detect_challenge(device_id)
                if challenge_info:
                    logger.warning(
                        f"Challenge detected during warmup for {account.email}: "
                        f"{challenge_info['type']}"
                    )
                    from app.services.challenge_service import handle_detected_challenge
                    await handle_detected_challenge(
                        db=db,
                        adb=adb,
                        device_id=device_id,
                        account=account,
                        instance=instance,
                        challenge_type=challenge_info["type"],
                        ws_manager=self.ws_manager,
                    )
                    return False

            # Log warmup activity
            log = StreamLog(
                instance_id=instance.id,
                account_id=account.id,
                song_id=None,
                spotify_uri="warmup:day_" + str(account.warmup_day),
                started_at=datetime.now(timezone.utc),
                duration_sec=plan.get("max_listen_minutes", 20) * 60,
                verified=True,
                result=StreamResult.HEALTH_CHECK,
                failure_reason=None,
            )
            db.add(log)

            # Advance warmup day
            account.warmup_day += 1
            warmup_duration = await self._get_warmup_duration(db)

            if account.warmup_day > warmup_duration:
                account.status = AccountStatus.ACTIVE
                logger.info(
                    f"Account {account.email} completed warmup — status set to ACTIVE"
                )
            else:
                logger.info(
                    f"Account {account.email} completed warmup day {account.warmup_day - 1}, "
                    f"next day: {account.warmup_day}"
                )

            await db.flush()
            return True

        except Exception as e:
            logger.error(f"Warmup failed for account {account.email}: {e}")
            return False

    # ------------------------------------------------------------------
    # Private warmup action helpers
    # ------------------------------------------------------------------

    async def _browse_discover(
        self, device_id: str, adb: ADBService, spotify: SpotifyController
    ) -> None:
        """Simulate browsing the Discover/Home page."""
        if self.mock_mode:
            logger.info(f"MOCK: browse_discover on {device_id}")
            return

        await spotify.launch_spotify(device_id)
        await asyncio.sleep(random.uniform(3, 8))
        # Scroll down a few times
        for _ in range(random.randint(2, 5)):
            await adb.tap(device_id, 540, 1200)
            await asyncio.sleep(random.uniform(1, 3))

    async def _follow_playlists(
        self, device_id: str, count: int, adb: ADBService, spotify: SpotifyController
    ) -> None:
        """Follow N random popular playlists via search."""
        if self.mock_mode:
            logger.info(f"MOCK: follow_playlists count={count} on {device_id}")
            return

        queries = ["Top Hits", "Chill Vibes", "Workout Mix", "Road Trip", "Mood Booster"]
        for i in range(min(count, len(queries))):
            await spotify.search_and_play(device_id, queries[i])
            await asyncio.sleep(random.uniform(2, 5))
            # Tap follow button area
            await adb.tap(device_id, 540, 400)
            await asyncio.sleep(random.uniform(1, 3))

    async def _play_random_tracks(
        self,
        device_id: str,
        count: int,
        adb: ADBService,
        spotify: SpotifyController,
        humanizer: Humanizer,
    ) -> None:
        """Play N random tracks from filler URIs."""
        if self.mock_mode:
            logger.info(f"MOCK: play_random_tracks count={count} on {device_id}")
            return

        for _ in range(count):
            uri = random.choice(Humanizer.FILLER_URIS)
            await spotify.play_track_premium(device_id, uri)
            listen_time = random.randint(30, 120)
            await spotify.wait_for_duration(device_id, listen_time)
            # Phase 9: Use warmup-specific delays
            await humanizer.between_tracks_delay(for_warmup=True)

    async def _save_songs(self, device_id: str, count: int, adb: ADBService) -> None:
        """Save N songs to library."""
        if self.mock_mode:
            logger.info(f"MOCK: save_songs count={count} on {device_id}")
            return

        for _ in range(count):
            # Tap heart/save button area
            await adb.tap(device_id, 900, 700)
            await asyncio.sleep(random.uniform(1, 3))

    async def _explore_artist(
        self, device_id: str, adb: ADBService, spotify: SpotifyController
    ) -> None:
        """Navigate to an artist page, scroll through discography."""
        if self.mock_mode:
            logger.info(f"MOCK: explore_artist on {device_id}")
            return

        await spotify.search_and_play(device_id, "popular artist")
        await asyncio.sleep(random.uniform(2, 5))
        for _ in range(random.randint(3, 7)):
            await adb.tap(device_id, 540, 1200)
            await asyncio.sleep(random.uniform(1, 3))

    async def _follow_artists(
        self, device_id: str, count: int, adb: ADBService, spotify: SpotifyController
    ) -> None:
        """Follow N artists."""
        if self.mock_mode:
            logger.info(f"MOCK: follow_artists count={count} on {device_id}")
            return

        artists = ["Drake", "Taylor Swift", "The Weeknd", "Dua Lipa", "Bad Bunny"]
        for i in range(min(count, len(artists))):
            await spotify.search_and_play(device_id, artists[i])
            await asyncio.sleep(random.uniform(2, 4))
            await adb.tap(device_id, 540, 400)
            await asyncio.sleep(random.uniform(1, 3))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_warmup_duration(self, db: AsyncSession) -> int:
        """Read warmup_duration_days from settings, default 5."""
        result = await db.execute(
            select(Setting).where(Setting.key == "warmup_duration_days")
        )
        setting = result.scalar_one_or_none()
        if setting:
            try:
                return int(setting.value)
            except ValueError:
                pass
        return 5
