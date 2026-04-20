"""Stream Worker - Executes a single streaming session on one instance."""

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.instance import Instance
from app.models.account import Account, AccountType
from app.models.song import Song
from app.models.stream_log import StreamLog, StreamResult
from app.services.automation.spotify_controller import SpotifyController
from app.services.automation.humanizer import Humanizer
from app.services.adb_service import ADBService
from app.services.challenge_service import handle_detected_challenge
from app.config import settings

if TYPE_CHECKING:
    from app.ws.dashboard import DashboardWebSocketManager

logger = logging.getLogger(__name__)


class StreamWorker:
    """
    Executes a complete streaming session on a single instance.
    
    Handles:
    - Free vs Premium account differences
    - Shuffle miss detection and retry
    - Human-like behavior during playback
    - Stream logging
    """

    def __init__(
        self,
        adb: ADBService,
        spotify: SpotifyController,
        ws_manager: "DashboardWebSocketManager" = None
    ):
        self.adb = adb
        self.spotify = spotify
        self.ws_manager = ws_manager
        self.mock_mode = settings.MOCK_ADB

    async def execute_stream(
        self,
        instance: Instance,
        account: Account,
        song: Song,
        humanizer: Humanizer,
        db: AsyncSession = None
    ) -> StreamLog:
        """
        Execute a full streaming session.

        Flow:
        1. Check account.type (free vs premium)
        2. If premium: play_track_premium(track_uri)
        3. If free: play_track_free(track_uri, artist_name)
           - If track doesn't match (shuffle): mark shuffle_miss, retry up to 3x
           - If retry exhausts: log shuffle_miss, still count as organic listen
        4. verify_playing() — confirm playback started
        5. Apply humanizer.random_action() during playback
        6. wait_for_duration(min_seconds from settings)
        7. stop_playback()
        8. Create and return StreamLog entry

        Args:
            instance: Target instance
            account: Account to use
            song: Song to stream
            humanizer: Humanizer for delays and actions
            db: Optional DB session for logging

        Returns:
            StreamLog entry for the completed stream
        """
        device_id = f"localhost:{instance.adb_port}" if instance.adb_port else "mock-device"
        started_at = datetime.now(timezone.utc)
        result = StreamResult.FAIL
        duration_sec = 0
        failure_reason = None
        verified = False
        shuffle_miss_count = 0
        max_retries = 3

        logger.info(
            f"Starting stream: song={song.spotify_uri}, "
            f"account={account.email}, instance={instance.name}"
        )

        try:
            # Ensure Spotify is running
            if not await self.spotify.launch_spotify(device_id):
                raise RuntimeError("Failed to launch Spotify")

            # Detect challenges (captcha, verification, etc.)
            challenge_info = await self.spotify.detect_challenge(device_id)
            if challenge_info:
                logger.warning(
                    f"Challenge detected on {instance.name} for {account.email}: "
                    f"{challenge_info['type']}"
                )
                if db:
                    await handle_detected_challenge(
                        db=db,
                        adb=self.adb,
                        device_id=device_id,
                        account=account,
                        instance=instance,
                        challenge_type=challenge_info["type"],
                        ws_manager=self.ws_manager,
                    )
                raise RuntimeError(f"Challenge detected: {challenge_info['type']}")

            # Apply pre-stream delay (humanization)
            await humanizer.pre_stream_delay()

            # Play track based on account type
            if account.type == AccountType.PREMIUM:
                # Premium: Direct deep link
                success = await self.spotify.play_track_premium(device_id, song.spotify_uri)
                if not success:
                    raise RuntimeError("Failed to play track (premium)")
                track_matched = True
                actual_track = None

            else:
                # Free: Navigate and play (shuffle mode possible)
                artist_name = song.artist or "Unknown"
                
                for attempt in range(max_retries):
                    play_result = await self.spotify.play_track_free(
                        device_id,
                        song.spotify_uri,
                        artist_name
                    )

                    if not play_result["played"]:
                        raise RuntimeError(f"Failed to play track (free), attempt {attempt + 1}")

                    track_matched = play_result["track_matched"]
                    actual_track = play_result.get("actual_track")

                    if track_matched:
                        break
                    else:
                        # Shuffle miss - track didn't match expected
                        shuffle_miss_count += 1
                        logger.warning(
                            f"Shuffle miss on {instance.name}: "
                            f"expected={song.spotify_uri}, got={actual_track}"
                        )
                        
                        # Small delay before retry
                        await asyncio.sleep(2)
                        
                        # If we've exhausted retries, continue with what we got
                        if attempt == max_retries - 1:
                            logger.info(
                                f"Shuffle miss accepted after {max_retries} attempts, "
                                f"counting as organic listen"
                            )

            # Post-playback challenge checkpoint
            challenge_info = await self.spotify.detect_challenge(device_id)
            if challenge_info:
                logger.warning(
                    f"Post-playback challenge on {instance.name} for {account.email}: "
                    f"{challenge_info['type']}"
                )
                if db:
                    await handle_detected_challenge(
                        db=db,
                        adb=self.adb,
                        device_id=device_id,
                        account=account,
                        instance=instance,
                        challenge_type=challenge_info["type"],
                        ws_manager=self.ws_manager,
                    )
                raise RuntimeError(f"Challenge detected: {challenge_info['type']}")

            # Verify playback started
            verify_result = await self.spotify.verify_playing(
                device_id,
                expected_track_name=song.title
            )

            if not verify_result["is_playing"]:
                raise RuntimeError("Playback verification failed")

            verified = True

            # Apply random actions during playback (humanization)
            action_count = humanizer.get_action_count()
            for _ in range(action_count):
                await humanizer.random_action(self.adb, device_id)
                # Wait a bit between actions
                if not self.mock_mode:
                    await asyncio.sleep(random.randint(10, 30))

            # Wait for minimum stream duration
            # Get min_stream_duration_sec from settings (default 30)
            min_duration = 30
            duration_sec = await self.spotify.wait_for_duration(device_id, min_duration)

            # Stop playback
            await self.spotify.stop_playback(device_id)

            # Determine result
            if shuffle_miss_count > 0 and shuffle_miss_count >= max_retries:
                result = StreamResult.SHUFFLE_MISS
            else:
                result = StreamResult.SUCCESS

            # Auto-downgrade premium account if shuffle behavior detected
            if account.type == AccountType.PREMIUM and shuffle_miss_count > 0:
                logger.warning(
                    f"Premium account {account.email} hit {shuffle_miss_count} shuffle misses "
                    f"— downgrading to FREE"
                )
                account.type = AccountType.FREE
                if db:
                    db.add(account)
                    await db.flush()
                if self.ws_manager:
                    try:
                        await self.ws_manager.broadcast({
                            "type": "account_downgraded",
                            "payload": {
                                "account_id": str(account.id),
                                "email": account.email,
                                "reason": "shuffle_miss_detected"
                            }
                        })
                    except Exception:
                        pass

            logger.info(
                f"Stream completed: song={song.spotify_uri}, "
                f"duration={duration_sec}s, result={result.value}"
            )

        except Exception as e:
            failure_reason = str(e)
            result = StreamResult.FAIL
            logger.error(f"Stream failed: {e}")

        finally:
            # Ensure playback is stopped
            try:
                await self.spotify.stop_playback(device_id)
            except Exception:
                pass

        # Create StreamLog entry
        stream_log = StreamLog(
            instance_id=instance.id,
            account_id=account.id,
            song_id=song.id,
            spotify_uri=song.spotify_uri,
            started_at=started_at,
            duration_sec=duration_sec,
            verified=verified,
            result=result,
            failure_reason=failure_reason
        )

        # Broadcast completion if ws_manager available
        if self.ws_manager:
            try:
                await self.ws_manager.broadcast_stream_completed(
                    song_id=str(song.id),
                    account_id=str(account.id),
                    instance_id=str(instance.id),
                    duration=duration_sec,
                    result=result.value
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast stream completion: {e}")

        return stream_log

    async def execute_session_plan(
        self,
        instance: Instance,
        account: Account,
        session_plan: dict,
        humanizer: Humanizer,
        db: AsyncSession = None
    ) -> list[StreamLog]:
        """
        Execute a full session plan with multiple tracks.

        Args:
            instance: Target instance
            account: Account to use
            session_plan: Output from Humanizer.build_session_plan()
            humanizer: Humanizer for delays and actions
            db: Optional DB session

        Returns:
            List of StreamLog entries
        """
        logs = []
        device_id = f"localhost:{instance.adb_port}" if instance.adb_port else "mock-device"

        # Ensure Spotify is running
        if not await self.spotify.launch_spotify(device_id):
            logger.error(f"Failed to launch Spotify on {instance.name}")
            return logs

        # Pre-stream delay
        await humanizer.pre_stream_delay()

        for track_info in session_plan.get("tracks", []):
            # Create a temporary Song object for the track
            temp_song = Song(
                id=uuid.uuid4(),  # Temporary ID for fillers
                spotify_uri=track_info["uri"],
                title="Session Track",
                artist="Unknown",
                total_target_streams=1,
                daily_rate=100
            )

            # Execute the stream
            log = await self.execute_stream(
                instance=instance,
                account=account,
                song=temp_song,
                humanizer=humanizer,
                db=db
            )
            logs.append(log)

            # Handle skip_after_sec for filler tracks
            skip_after = track_info.get("skip_after_sec")
            if skip_after and skip_after < log.duration_sec:
                # Track was skipped early (simulated in execute_stream via duration)
                log.duration_sec = skip_after

            # Delay between tracks (except last)
            if track_info != session_plan["tracks"][-1]:
                await humanizer.between_tracks_delay()

        return logs
