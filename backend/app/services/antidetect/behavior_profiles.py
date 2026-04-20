"""BehaviorProfileManager — listener persona templates controlling session timing."""

import logging
import math
import random
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instance import Instance

logger = logging.getLogger(__name__)


@dataclass
class BehaviorProfile:
    name: str
    active_hours_start: int          # 0-23 UTC
    active_hours_end: int            # 0-23 UTC
    peak_hour: int                   # Gaussian peak within active window
    session_length_min: int          # Minutes
    session_length_max: int
    session_length_mean: int
    tracks_per_session_min: int
    tracks_per_session_max: int
    skip_probability: float          # 0.0-1.0
    genre_preferences: list[str] = field(default_factory=list)
    pause_between_tracks_min_sec: int = 2
    pause_between_tracks_max_sec: int = 15
    daily_listen_time_min: int = 30   # Minutes
    daily_listen_time_max: int = 90
    sessions_per_day_min: int = 1
    sessions_per_day_max: int = 3


PROFILES: dict[str, BehaviorProfile] = {
    "casual_listener": BehaviorProfile(
        name="casual_listener",
        active_hours_start=8, active_hours_end=23, peak_hour=19,
        session_length_min=15, session_length_max=45, session_length_mean=25,
        tracks_per_session_min=5, tracks_per_session_max=12,
        skip_probability=0.25,
        genre_preferences=["pop", "indie", "chill"],
        pause_between_tracks_min_sec=2, pause_between_tracks_max_sec=15,
        daily_listen_time_min=30, daily_listen_time_max=90,
        sessions_per_day_min=1, sessions_per_day_max=3,
    ),
    "playlist_addict": BehaviorProfile(
        name="playlist_addict",
        active_hours_start=9, active_hours_end=1, peak_hour=21,
        session_length_min=45, session_length_max=120, session_length_mean=75,
        tracks_per_session_min=15, tracks_per_session_max=40,
        skip_probability=0.08,
        genre_preferences=["pop", "r&b", "electronic", "hip-hop"],
        pause_between_tracks_min_sec=1, pause_between_tracks_max_sec=5,
        daily_listen_time_min=90, daily_listen_time_max=240,
        sessions_per_day_min=2, sessions_per_day_max=5,
    ),
    "commuter": BehaviorProfile(
        name="commuter",
        active_hours_start=6, active_hours_end=20, peak_hour=8,
        session_length_min=20, session_length_max=60, session_length_mean=35,
        tracks_per_session_min=7, tracks_per_session_max=18,
        skip_probability=0.15,
        genre_preferences=["pop", "rock", "podcasts"],
        pause_between_tracks_min_sec=1, pause_between_tracks_max_sec=8,
        daily_listen_time_min=40, daily_listen_time_max=120,
        sessions_per_day_min=2, sessions_per_day_max=4,
    ),
    "workout_listener": BehaviorProfile(
        name="workout_listener",
        active_hours_start=5, active_hours_end=21, peak_hour=17,
        session_length_min=30, session_length_max=90, session_length_mean=55,
        tracks_per_session_min=10, tracks_per_session_max=25,
        skip_probability=0.20,
        genre_preferences=["hip-hop", "electronic", "rock", "metal"],
        pause_between_tracks_min_sec=1, pause_between_tracks_max_sec=4,
        daily_listen_time_min=45, daily_listen_time_max=120,
        sessions_per_day_min=1, sessions_per_day_max=2,
    ),
    "night_owl": BehaviorProfile(
        name="night_owl",
        active_hours_start=18, active_hours_end=5, peak_hour=0,
        session_length_min=30, session_length_max=90, session_length_mean=55,
        tracks_per_session_min=10, tracks_per_session_max=30,
        skip_probability=0.18,
        genre_preferences=["lo-fi", "ambient", "jazz", "indie"],
        pause_between_tracks_min_sec=3, pause_between_tracks_max_sec=20,
        daily_listen_time_min=60, daily_listen_time_max=180,
        sessions_per_day_min=1, sessions_per_day_max=3,
    ),
    "background_listener": BehaviorProfile(
        name="background_listener",
        active_hours_start=7, active_hours_end=22, peak_hour=14,
        session_length_min=60, session_length_max=180, session_length_mean=120,
        tracks_per_session_min=20, tracks_per_session_max=60,
        skip_probability=0.35,
        genre_preferences=["ambient", "classical", "lo-fi", "chill"],
        pause_between_tracks_min_sec=0, pause_between_tracks_max_sec=3,
        daily_listen_time_min=120, daily_listen_time_max=360,
        sessions_per_day_min=1, sessions_per_day_max=3,
    ),
}


class BehaviorProfileManager:
    """Assigns and queries listener persona profiles for instances."""

    async def assign_profile(
        self, instance_id: _uuid.UUID, db: AsyncSession
    ) -> str:
        """Randomly assign a profile to an instance and persist the choice."""
        profile_name = random.choice(list(PROFILES.keys()))

        result = await db.get(Instance, instance_id)
        if result:
            result.behavior_profile = profile_name
            await db.flush()

        logger.info(f"Assigned profile '{profile_name}' to instance {instance_id}")
        return profile_name

    def get_profile(self, profile_name: str) -> BehaviorProfile:
        """Look up a profile by name.  Falls back to casual_listener."""
        return PROFILES.get(profile_name, PROFILES["casual_listener"])

    def is_active_hour(self, profile: BehaviorProfile, utc_hour: int) -> bool:
        """Return True if the current hour falls within the profile's active window.

        Uses gaussian probability around peak_hour instead of a hard cutoff.
        """
        # Normalise hour distance accounting for wrap-around
        if profile.active_hours_start <= profile.active_hours_end:
            # Simple range (e.g. 8-23)
            if not (profile.active_hours_start <= utc_hour <= profile.active_hours_end):
                return False
        else:
            # Wrapped range (e.g. 18-05)
            if profile.active_hours_end < utc_hour < profile.active_hours_start:
                return False

        # Gaussian probability centred on peak_hour
        dist = min(abs(utc_hour - profile.peak_hour), 24 - abs(utc_hour - profile.peak_hour))
        sigma = 4.0  # Standard deviation in hours
        probability = math.exp(-0.5 * (dist / sigma) ** 2)

        return random.random() < probability

    def get_session_length(self, profile: BehaviorProfile) -> int:
        """Return a session length in minutes (gaussian around mean, clamped)."""
        std = (profile.session_length_max - profile.session_length_min) / 6.0
        length = random.gauss(profile.session_length_mean, max(std, 1))
        return int(max(profile.session_length_min, min(profile.session_length_max, length)))

    def should_skip_track(self, profile: BehaviorProfile) -> bool:
        """Roll against skip_probability."""
        return random.random() < profile.skip_probability

    def get_daily_listen_budget(self, profile: BehaviorProfile) -> int:
        """Return random daily listen time in minutes within profile bounds."""
        return random.randint(profile.daily_listen_time_min, profile.daily_listen_time_max)
