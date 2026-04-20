"""Humanizer - Random behavioral delays and actions for organic behavior."""

import asyncio
import logging
import random
import math
from typing import TYPE_CHECKING, Optional

from app.services.adb_service import ADBService
from app.models.song import Song, SongPriority
from app.models.account import AccountType

if TYPE_CHECKING:
    from app.models.song import Song
    from app.services.humanization_config import HumanizationConfig

from prometheus_client import Histogram, Counter

logger = logging.getLogger(__name__)

# Phase 9: Humanization observability metrics
HUMANIZATION_PRE_STREAM_DELAY_SECONDS = Histogram(
    "humanization_pre_stream_delay_seconds",
    "Actual pre-stream delay durations",
    buckets=[30, 60, 120, 180, 240, 300, 360, 420, 480, 600]
)
HUMANIZATION_BETWEEN_TRACKS_DELAY_SECONDS = Histogram(
    "humanization_between_tracks_delay_seconds",
    "Actual between-tracks delay durations",
    buckets=[1, 2, 5, 10, 15, 20, 30, 45, 60]
)
HUMANIZATION_RANDOM_ACTIONS_TOTAL = Counter(
    "humanization_random_actions_total",
    "Total random actions executed",
    ["action_type"]
)
HUMANIZATION_STREAM_RUNS_TOTAL = Counter(
    "humanization_stream_runs_total",
    "Total stream executions by preset",
    ["preset"]
)
HUMANIZATION_WARMUP_RUNS_TOTAL = Counter(
    "humanization_warmup_runs_total",
    "Total warmup executions by preset",
    ["preset"]
)


class Humanizer:
    """
    Generates human-like behavior patterns to avoid detection.

    Level behaviors:
    - low: minimal delays (1-3s between tracks, 1-2 min pre-stream)
    - medium: moderate (5-15s between, 3-5 min pre-stream)
    - high: realistic (10-30s between, 5-8 min pre-stream, more random actions)

    Phase 9: Now accepts either a level string OR a typed HumanizationConfig object.
    The config object is the preferred method for runtime use.
    """

    # Filler track URIs for session building (popular tracks)
    FILLER_URIS = [
        "spotify:track:4uLU6hMCjMI75M1A2tKUQC",  # Never Gonna Give You Up
        "spotify:track:11dFghVXANMlKmJXsNCbNl",  # Blinding Lights
        "spotify:track:6UelLqGlWMcVO1BTlK2Vv1",  # Levitating
        "spotify:track:5HCyWlXZQ9b11rr2Yl0CUE",  # Stay
        "spotify:track:2QjOHCTQ1Jl3OuK9SG01Gj",  # Heat Waves
        "spotify:track:1zi7xxj8dga1Aq5zSrMssB",  # As It Was
        "spotify:track:4Dvkj6JhhA12EX05fT7y2e",  # Bad Habits
        "spotify:track:5PjdY0CKGZdEuoNab3yDmX",  # Shape of You
        "spotify:track:7qiZfU4dY9lQabv8lsDsK7",  # Shape of You (alt)
        "spotify:track:3n3Ppam7vgaVa1iaRUc9Lp",  # Mr. Brightside
    ]

    def __init__(self, level_or_config: str | "HumanizationConfig" = "medium", *, level: str | None = None):
        """
        Initialize humanizer with behavior level or typed config.

        Args:
            level_or_config: 'low', 'medium', 'high' string OR HumanizationConfig object
            level: Deprecated keyword arg for backward compatibility
        """
        self._config: Optional["HumanizationConfig"] = None
        self.level = "medium"
        self.mock_mode = False  # Set by external components if needed

        # Handle deprecated 'level' keyword arg for backward compatibility
        if level is not None:
            effective_level = level
        else:
            effective_level = level_or_config

        # Phase 9: Accept either string level or typed config
        if hasattr(effective_level, 'pre_stream_min_sec'):
            # It's a HumanizationConfig object
            self._config = effective_level
            self.level = self._config.effective_preset
        else:
            # It's a string level
            self.level = str(effective_level).lower()

        # Define delay ranges by level (in seconds) - fallback presets
        self._delays = {
            "low": {
                "pre_stream_min": 60,
                "pre_stream_max": 120,
                "between_tracks_min": 1,
                "between_tracks_max": 3,
                "action_chance": 0.1,
            },
            "medium": {
                "pre_stream_min": 180,
                "pre_stream_max": 300,
                "between_tracks_min": 5,
                "between_tracks_max": 15,
                "action_chance": 0.3,
            },
            "high": {
                "pre_stream_min": 300,
                "pre_stream_max": 480,
                "between_tracks_min": 10,
                "between_tracks_max": 30,
                "action_chance": 0.5,
            },
        }

    def _get_delay_config(self) -> dict:
        """Get delay configuration from typed config if available, else from presets."""
        if self._config:
            return {
                "pre_stream_min": self._config.pre_stream_min_sec,
                "pre_stream_max": self._config.pre_stream_max_sec,
                "between_tracks_min": self._config.between_tracks_min_sec,
                "between_tracks_max": self._config.between_tracks_max_sec,
                "action_chance": 0.3 if self._config.random_actions_enabled else 0.0,
            }
        return self._delays.get(self.level, self._delays["medium"])

    def is_enabled(self) -> bool:
        """Return whether humanization behavior should be applied."""
        return self._config.enabled if self._config else True

    def get_action_count(self) -> int:
        """Return how many random actions to attempt during a stream."""
        if self.mock_mode or not self.is_enabled():
            return 0

        if self._config:
            if not self._config.random_actions_enabled:
                return 0
            min_actions = max(0, self._config.min_actions_per_stream)
            max_actions = max(0, self._config.max_actions_per_stream)
            min_actions, max_actions = sorted((min_actions, max_actions))
            return random.randint(
                min_actions,
                max_actions,
            )

        return random.randint(1, 3)

    async def random_delay(self, min_ms: int, max_ms: int) -> None:
        """
        Async sleep with gaussian distribution centered at midpoint.

        Args:
            min_ms: Minimum milliseconds to sleep
            max_ms: Maximum milliseconds to sleep
        """
        if self.mock_mode:
            # 100ms in mock mode
            await asyncio.sleep(0.1)
            return

        # Calculate midpoint and standard deviation
        midpoint = (min_ms + max_ms) / 2
        std_dev = (max_ms - min_ms) / 6  # 99.7% within range

        # Generate gaussian random value
        delay_ms = random.gauss(midpoint, std_dev)

        # Clamp to range
        delay_ms = max(min_ms, min(max_ms, delay_ms))

        await asyncio.sleep(delay_ms / 1000)

    async def random_action(self, adb: ADBService, device_id: str) -> str:
        """
        Occasionally perform human-like actions during playback.

        Probabilities:
        - 70% nothing
        - 15% volume change
        - 10% scroll feed
        - 5% tap safe area

        Returns:
            Action taken (for logging)
        """
        if not self.is_enabled():
            HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type="nothing").inc()
            return "nothing"

        # Phase 9: Respect random_actions_enabled setting from config
        if self._config and not self._config.random_actions_enabled:
            HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type="nothing").inc()
            return "nothing"

        action_probs = [0.70, 0.15, 0.10, 0.05]
        actions = ["nothing", "volume", "scroll", "tap"]

        action = random.choices(actions, weights=action_probs, k=1)[0]

        # Phase 9: Track action metrics
        if action == "nothing":
            HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type="nothing").inc()
            return "nothing"

        if self.mock_mode:
            logger.debug(f"MOCK: Humanizer.random_action({device_id}) -> {action}")
            HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type=action).inc()
            return action

        try:
            if action == "volume":
                # Volume up or down
                keycode = 24 if random.random() < 0.5 else 25  # VOL_UP or VOL_DOWN
                await adb.send_keyevent(device_id, keycode)
                HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type="volume_change").inc()
                return "volume_change"

            elif action == "scroll":
                # Simulate scroll with swipe gesture (tap drag)
                start_x, start_y = 500, 800
                end_x, end_y = 500, 400
                # In real ADB: adb shell input swipe x1 y1 x2 y2 duration
                logger.debug(f"Scroll gesture on {device_id}")
                HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type="scroll").inc()
                return "scroll"

            elif action == "tap":
                # Tap a safe area (center of screen)
                safe_x, safe_y = 540, 960  # Typical 1080p center
                await adb.tap(device_id, safe_x, safe_y)
                HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type="tap").inc()
                return "tap"

        except Exception as e:
            logger.warning(f"Failed to perform action {action} on {device_id}: {e}")
            HUMANIZATION_RANDOM_ACTIONS_TOTAL.labels(action_type="failed").inc()
            return "nothing"

        return action

    def build_session_plan(
        self,
        target_songs: list[Song],
        account_type: str
    ) -> dict:
        """
        Build a session plan: target tracks interleaved with 2-5 filler URIs.

        Args:
            target_songs: List of target songs to play
            account_type: 'free' or 'premium'

        Returns:
            {
                "tracks": [
                    {
                        "uri": str,
                        "is_target": bool,
                        "skip_after_sec": int | None
                    }
                ],
                "total_minutes": float
            }
        """
        tracks = []
        total_minutes = 0

        # For free accounts, we need more filler tracks to appear organic
        filler_count = 3 if account_type == AccountType.FREE else 2

        for song in target_songs:
            # Add filler tracks before target
            for _ in range(random.randint(2, filler_count + 1)):
                filler_uri = random.choice(self.FILLER_URIS)
                tracks.append({
                    "uri": filler_uri,
                    "is_target": False,
                    "skip_after_sec": random.randint(30, 90)  # Skip filler early
                })
                total_minutes += 1.5  # Approximate filler listen time

            # Add target track
            tracks.append({
                "uri": song.spotify_uri,
                "is_target": True,
                "skip_after_sec": None  # Listen to full target
            })
            total_minutes += 3.5  # Approximate target listen time

        return {
            "tracks": tracks,
            "total_minutes": round(total_minutes, 1)
        }

    async def pre_stream_delay(self) -> None:
        """
        Delay before starting a stream.

        - low: 1-2 min
        - medium: 3-5 min
        - high: 5-8 min
        """
        if not self.is_enabled():
            return

        config = self._get_delay_config()
        min_sec = max(0, config["pre_stream_min"])
        max_sec = max(0, config["pre_stream_max"])
        min_sec, max_sec = sorted((min_sec, max_sec))

        if self.mock_mode:
            logger.info(f"MOCK: pre_stream_delay ({min_sec}-{max_sec}s) -> 100ms")
            await asyncio.sleep(0.1)
            return

        # Gaussian delay
        delay_sec = random.gauss((min_sec + max_sec) / 2, (max_sec - min_sec) / 6)
        delay_sec = max(min_sec, min(max_sec, delay_sec))

        logger.info(f"Pre-stream delay: {delay_sec:.0f}s")

        # Phase 9: Record metrics
        HUMANIZATION_PRE_STREAM_DELAY_SECONDS.observe(delay_sec)
        HUMANIZATION_STREAM_RUNS_TOTAL.labels(preset=self.level).inc()

        await asyncio.sleep(delay_sec)

    async def between_tracks_delay(self, for_warmup: bool = False) -> None:
        """
        Delay between tracks within a session.

        - low: 1-3 sec
        - medium: 5-15 sec
        - high: 10-30 sec

        Args:
            for_warmup: If True, use warmup-specific delays from config
        """
        if not self.is_enabled():
            return

        config = self._get_delay_config()

        # Phase 9: Use warmup-specific delays if available and requested
        if for_warmup and self._config:
            min_sec = self._config.warmup_between_tracks_min_sec
            max_sec = self._config.warmup_between_tracks_max_sec
        else:
            min_sec = config["between_tracks_min"]
            max_sec = config["between_tracks_max"]

        min_sec = max(0, min_sec)
        max_sec = max(0, max_sec)
        min_sec, max_sec = sorted((min_sec, max_sec))

        if self.mock_mode:
            logger.debug(f"MOCK: between_tracks_delay ({min_sec}-{max_sec}s) -> 100ms")
            await asyncio.sleep(0.1)
            return

        delay_sec = random.uniform(min_sec, max_sec)

        # Phase 9: Record metrics
        HUMANIZATION_BETWEEN_TRACKS_DELAY_SECONDS.observe(delay_sec)

        await asyncio.sleep(delay_sec)

    def set_mock_mode(self, enabled: bool) -> None:
        """Enable or disable mock mode (shortened delays)."""
        self.mock_mode = enabled
