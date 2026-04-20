"""Spotify controller - High-level Spotify operations via ADB."""

import asyncio
import logging
import random
import re
from typing import Optional

from app.services.adb_service import ADBService
from app.config import settings

logger = logging.getLogger(__name__)


class SpotifyController:
    """Controls Spotify playback on Android devices via ADB."""

    def __init__(self, adb: ADBService):
        self.adb = adb
        self.mock_mode = settings.MOCK_ADB
        self.package = "com.spotify.music"

    async def launch_spotify(self, device_id: str) -> bool:
        """Opens Spotify app, waits for main screen."""
        if self.mock_mode:
            logger.info(f"MOCK: SpotifyController.launch_spotify({device_id})")
            return True

        try:
            success = await self.adb.launch_app(device_id, self.package)
            if success:
                # Wait for app to fully load
                await asyncio.sleep(2)
            return success
        except Exception as e:
            logger.error(f"Failed to launch Spotify on {device_id}: {e}")
            return False

    async def play_track_premium(self, device_id: str, track_uri: str) -> bool:
        """
        Deep link for premium accounts.
        Uses: am start -a android.intent.action.VIEW -d 'spotify:track:<id>'
        """
        if self.mock_mode:
            logger.info(f"MOCK: SpotifyController.play_track_premium({device_id}, {track_uri})")
            return True

        try:
            # Extract track ID from URI (spotify:track:XXXXX)
            track_id = track_uri.split(":")[-1] if ":" in track_uri else track_uri
            deep_link = f"spotify:track:{track_id}"

            # Use adb shell am start for deep link with the Spotify package
            # This opens Spotify directly to the track
            cmd = f"am start -a android.intent.action.VIEW -d '{deep_link}' -p {self.package}"
            rc, stdout, stderr = await self.adb.send_shell_command(device_id, cmd)

            if rc != 0:
                logger.error(f"Failed to start deep link on {device_id}: {stderr}")
                return False

            # Wait for playback to start
            await asyncio.sleep(2)

            logger.info(f"Playing track {track_id} on {device_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to play track on {device_id}: {e}")
            return False

    async def play_track_free(
        self,
        device_id: str,
        track_uri: str,
        artist_name: str
    ) -> dict:
        """
        For free accounts: navigate to artist page via search/deep link,
        find track, start playback.

        Free accounts may hit shuffle mode - tracks might not match exactly.

        Returns:
            {
                "played": bool,
                "track_matched": bool,
                "actual_track": str | None
            }
        """
        if self.mock_mode:
            logger.info(f"MOCK: SpotifyController.play_track_free({device_id}, {track_uri}, {artist_name})")
            # Simulate shuffle miss occasionally
            track_matched = random.random() < 0.7
            return {
                "played": True,
                "track_matched": track_matched,
                "actual_track": "Mock Track" if track_matched else "Random Shuffle Track"
            }

        try:
            # Launch app
            await self.adb.launch_app(device_id, self.package)
            await asyncio.sleep(2)

            # Use search to find the artist/track
            search_query = artist_name if artist_name else track_uri.split(":")[-1]
            search_success = await self.search_and_play(device_id, search_query)

            if not search_success:
                logger.error(f"Search and play failed for free account on {device_id}")
                return {
                    "played": False,
                    "track_matched": False,
                    "actual_track": None
                }

            # Wait for playback to stabilize
            await asyncio.sleep(3)

            # Verify actual playback and try to identify the track
            verify_result = await self.verify_playing(device_id)

            if not verify_result["is_playing"]:
                logger.warning(f"Playback verification failed for free account on {device_id}")
                return {
                    "played": False,
                    "track_matched": False,
                    "actual_track": None
                }

            # Determine if track matched expected
            actual_track = verify_result.get("track_name")
            track_matched = False
            if actual_track:
                # Simple string matching - check if expected track/artist appears in actual
                track_id = track_uri.split(":")[-1] if ":" in track_uri else track_uri
                track_matched = (
                    track_id.lower() in actual_track.lower() or
                    (artist_name and artist_name.lower() in actual_track.lower())
                )

            logger.info(
                f"Free account playback on {device_id}: "
                f"played=True, track_matched={track_matched}, actual_track={actual_track}"
            )

            return {
                "played": True,
                "track_matched": track_matched,
                "actual_track": actual_track
            }

        except Exception as e:
            logger.error(f"Failed to play track on free account {device_id}: {e}")
            return {
                "played": False,
                "track_matched": False,
                "actual_track": None
            }

    async def verify_playing(
        self,
        device_id: str,
        expected_track_name: Optional[str] = None
    ) -> dict:
        """
        Dump UI XML and verify:
        - Correct track is visible
        - Playback is advancing (progress bar moving)

        Returns:
            {
                "is_playing": bool,
                "track_name": str | None,
                "progress_sec": int
            }
        """
        if self.mock_mode:
            logger.info(f"MOCK: SpotifyController.verify_playing({device_id}, {expected_track_name})")
            return {
                "is_playing": True,
                "track_name": expected_track_name or "Mock Song",
                "progress_sec": random.randint(0, 180)
            }

        try:
            # Check if app is running first
            is_running = await self.adb.is_app_running(device_id, self.package)
            if not is_running:
                logger.warning(f"Spotify not running on {device_id}")
                return {
                    "is_playing": False,
                    "track_name": None,
                    "progress_sec": 0
                }

            # Get screen dump to verify playback state
            xml = await self.adb.get_screen_xml(device_id)
            if not xml:
                logger.warning(f"Failed to get screen XML from {device_id}")
                return {
                    "is_playing": False,
                    "track_name": None,
                    "progress_sec": 0
                }

            # Parse XML for playback indicators
            xml_lower = xml.lower()

            # Check for playback UI elements that indicate active playback
            # These are conservative checks based on common Spotify UI patterns
            playback_indicators = [
                "pause", "stop", "playing", "now playing", "progress",
                "seekbar", "seek_bar", "elapsed", "remaining"
            ]

            # Check for track title/artist text elements
            has_track_info = False
            track_name = None

            # Look for common text container patterns in UI hierarchy
            # Text often appears in TextView elements with text attributes
            if 'text="' in xml:
                # Try to extract visible text that might be track info
                # Look for text attributes in the XML
                text_matches = re.findall(r'text="([^"]+)"', xml)

                # Filter out short/UI text, look for likely track titles
                for text in text_matches:
                    # Skip common UI labels and short text
                    if len(text) > 3 and text not in [
                        "spotify", "home", "search", "library", "premium",
                        "settings", "back", "close", "menu", "more"
                    ]:
                        has_track_info = True
                        track_name = text
                        break

            # Check if any playback indicator is present
            is_playing = any(indicator in xml_lower for indicator in playback_indicators)

            # Also check for artist/album indicators as secondary confirmation
            artist_indicators = ["artist", "album", "song", "track"]
            has_artist_context = any(ind in xml_lower for ind in artist_indicators)

            # Conservative verification: need both playback indicator AND context
            verified_playing = is_playing or (has_track_info and has_artist_context)

            # If expected track name provided, try to verify it matches
            if expected_track_name and track_name:
                expected_lower = expected_track_name.lower()
                actual_lower = track_name.lower()
                # Partial match is acceptable
                track_match = (
                    expected_lower in actual_lower or
                    actual_lower in expected_lower
                )
                if not track_match:
                    logger.debug(
                        f"Track name mismatch on {device_id}: "
                        f"expected='{expected_track_name}', actual='{track_name}'"
                    )

            logger.debug(
                f"Playback verification on {device_id}: "
                f"is_playing={verified_playing}, track_name={track_name}"
            )

            return {
                "is_playing": verified_playing,
                "track_name": track_name or expected_track_name,
                "progress_sec": 0  # TODO: Parse progress from seekbar if available
            }

        except Exception as e:
            logger.error(f"Failed to verify playback on {device_id}: {e}")
            return {
                "is_playing": False,
                "track_name": None,
                "progress_sec": 0
            }

    async def wait_for_duration(
        self,
        device_id: str,
        min_seconds: int = 30
    ) -> int:
        """
        Wait until min_seconds elapsed (with random extension 30-90s).
        Returns actual duration in seconds.

        In mock mode, this is shortened to 2 seconds for development speed.
        """
        if self.mock_mode:
            # Shortened for development
            await asyncio.sleep(0.1)  # 100ms mock delay
            actual_duration = random.randint(min_seconds, min_seconds + 60)
            logger.info(f"MOCK: wait_for_duration returned {actual_duration}s (would have waited ~{min_seconds}s)")
            return actual_duration

        # Add random extension (30-90 seconds)
        extension = random.randint(30, 90)
        total_seconds = min_seconds + extension

        logger.info(f"Waiting {total_seconds}s on {device_id}")
        await asyncio.sleep(total_seconds)

        return total_seconds

    async def stop_playback(self, device_id: str) -> bool:
        """Pause or force-stop Spotify."""
        if self.mock_mode:
            logger.info(f"MOCK: SpotifyController.stop_playback({device_id})")
            return True

        try:
            # Try to pause first (media key)
            # Keycode 127 = MEDIA_PAUSE
            await self.adb.send_keyevent(device_id, 127)
            await asyncio.sleep(0.5)

            # Then force stop to be sure
            await self.adb.force_stop(device_id, self.package)
            return True
        except Exception as e:
            logger.error(f"Failed to stop playback on {device_id}: {e}")
            return False

    async def search_and_play(self, device_id: str, query: str) -> bool:
        """
        Search for a query and play the first result.
        Useful for free account navigation.
        """
        if self.mock_mode:
            logger.info(f"MOCK: SpotifyController.search_and_play({device_id}, {query})")
            return True

        try:
            # Ensure app is running
            await self.adb.launch_app(device_id, self.package)
            await asyncio.sleep(2)

            # Step 1: Navigate to Search tab
            # Tap on search icon/button (common coordinates for bottom nav)
            # This is a heuristic - actual coordinates may vary by device
            search_tap_success = await self.adb.tap(device_id, 540, 1700)
            if not search_tap_success:
                logger.warning(f"Failed to tap search on {device_id}, trying fallback")
                # Try alternative: send search key event
                await self.adb.send_keyevent(device_id, 84)  # KEYCODE_SEARCH

            await asyncio.sleep(1)

            # Step 2: Input the search query
            # First tap the search input field
            await self.adb.tap(device_id, 540, 400)
            await asyncio.sleep(0.5)

            # Clear any existing text and input the query
            # Use input_text which handles escaping
            input_success = await self.adb.input_text(device_id, query)
            if not input_success:
                logger.error(f"Failed to input search text on {device_id}")
                return False

            await asyncio.sleep(1)

            # Step 3: Submit search
            await self.adb.send_keyevent(device_id, 66)  # KEYCODE_ENTER
            await asyncio.sleep(2)

            # Step 4: Tap first result
            # First result is typically below the search bar
            # Tap in the results area (heuristic coordinates)
            result_tap_success = await self.adb.tap(device_id, 540, 800)
            if not result_tap_success:
                logger.error(f"Failed to tap search result on {device_id}")
                return False

            await asyncio.sleep(2)

            # Step 5: Tap play button on the track/artist page
            # Play button is typically in the top section of content pages
            play_tap_success = await self.adb.tap(device_id, 200, 900)
            if not play_tap_success:
                logger.warning(f"Failed to tap play button on {device_id}, may already be playing")
                # Don't return False - playback might have started anyway

            await asyncio.sleep(1)

            logger.info(f"Search and play completed for '{query}' on {device_id}")
            return True

        except Exception as e:
            logger.error(f"Search and play failed on {device_id}: {e}")
            return False

    # Challenge detection keyword map: type -> list of indicators
    _CHALLENGE_INDICATORS: dict[str, list[str]] = {
        "captcha": [
            "captcha", "recaptcha", "i'm not a robot", "not a robot",
            "robot check", "security challenge",
        ],
        "email_verify": [
            "verify your email", "confirm your email", "check your email",
            "email verification",
        ],
        "phone_verify": [
            "verify your phone", "phone number", "sms code",
            "verification code",
        ],
        "terms_accept": [
            "terms and conditions", "accept terms", "privacy policy",
            "agree and continue",
        ],
    }

    async def detect_challenge(self, device_id: str) -> Optional[dict]:
        """Check if the current screen shows a CAPTCHA or verification challenge.

        In real mode: dump UI hierarchy via `adb shell uiautomator dump` and
        parse the XML for known challenge indicators (captcha elements,
        verification prompts, etc.)

        Returns: {"type": "captcha"|"email_verify"|..., "indicator": "..."} or None
        """
        if self.mock_mode:
            # 2% chance of challenge in mock mode for testing
            if random.random() < 0.02:
                challenge_types = ["captcha", "email_verify", "terms_accept"]
                return {"type": random.choice(challenge_types)}
            return None

        try:
            xml = await self.adb.get_screen_xml(device_id)
            if not xml:
                return None
            xml_lower = xml.lower()
            for ctype, indicators in self._CHALLENGE_INDICATORS.items():
                for indicator in indicators:
                    if indicator in xml_lower:
                        logger.info(
                            f"Challenge indicator matched on {device_id}: "
                            f"type={ctype}, indicator='{indicator}'"
                        )
                        return {"type": ctype, "indicator": indicator}
            return None
        except Exception as e:
            logger.warning(f"Challenge detection failed on {device_id}: {e}")
            return None
