from datetime import datetime
from typing import Optional
from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    @staticmethod
    def default_settings():
        return [
            {"key": "max_streams_per_account_per_day", "value": "40", "description": "Max streams one account can do per day"},
            {"key": "rotation_interval_streams", "value": "15", "description": "Rotate account after N streams"},
            {"key": "rotation_interval_hours", "value": "4", "description": "Rotate account after N hours"},
            {"key": "cooldown_hours", "value": "6", "description": "Hours an account rests after rotation"},
            {"key": "min_stream_duration_sec", "value": "30", "description": "Minimum seconds to count as a valid stream"},
            {"key": "max_concurrent_streams", "value": "14", "description": "Max instances streaming simultaneously"},
            {"key": "warmup_duration_days", "value": "5", "description": "Days of warmup before account goes active"},
            {"key": "daily_reset_hour", "value": "0", "description": "Hour (UTC) when streams_today resets"},
            {"key": "default_account_type", "value": "free", "description": "Default type for new accounts"},
            {"key": "creation_delay_min_sec", "value": "180", "description": "Min seconds between account creations"},
            {"key": "creation_delay_max_sec", "value": "300", "description": "Max seconds between account creations"},
            {"key": "daily_account_creation_cap", "value": "8", "description": "Max accounts to create per day"},
            {"key": "max_streams_per_account_per_hour", "value": "8", "description": "Max streams one account can do per rolling hour"},
            {"key": "max_streams_per_track_per_account_per_day", "value": "2", "description": "Max times one account streams the same track per day"},
            {"key": "instance_cooldown_min_sec", "value": "120", "description": "Min seconds between streams on same instance"},
            {"key": "instance_cooldown_max_sec", "value": "480", "description": "Max seconds between streams on same instance"},
            {"key": "threshold_alert_pct", "value": "80", "description": "Alert when account reaches this % of daily limit"},
            # Phase 7: Scaling & Monitoring settings
            {"key": "telegram_bot_token", "value": "", "description": "Telegram Bot API token for alerts"},
            {"key": "telegram_chat_id", "value": "", "description": "Telegram chat ID for alerts"},
            {"key": "alert_cooldown_minutes", "value": "5", "description": "Dedup window for same alert title"},
            {"key": "daily_digest_enabled", "value": "true", "description": "Send daily digest at midnight UTC"},
            {"key": "cluster_enabled", "value": "false", "description": "Enable multi-machine cluster mode"},
            # Phase 9: Humanization Settings (typed config)
            {"key": "humanization_enabled", "value": "true", "description": "Enable humanization delays and actions"},
            {"key": "humanization_preset", "value": "medium", "description": "Preset: low, medium, high, or custom"},
            # Primary humanization level (backward compatible with legacy)
            {"key": "humanization_level", "value": "medium", "description": "Humanization level: low, medium, or high"},
            {"key": "pre_stream_min_sec", "value": "180", "description": "Min seconds delay before starting a stream"},
            {"key": "pre_stream_max_sec", "value": "300", "description": "Max seconds delay before starting a stream"},
            {"key": "between_tracks_min_sec", "value": "5", "description": "Min seconds delay between tracks"},
            {"key": "between_tracks_max_sec", "value": "15", "description": "Max seconds delay between tracks"},
            {"key": "random_actions_enabled", "value": "true", "description": "Enable random actions during playback"},
            {"key": "min_actions_per_stream", "value": "0", "description": "Minimum random actions per stream"},
            {"key": "max_actions_per_stream", "value": "3", "description": "Maximum random actions per stream"},
            {"key": "warmup_between_tracks_min_sec", "value": "3", "description": "Min seconds between tracks during warmup"},
            {"key": "warmup_between_tracks_max_sec", "value": "10", "description": "Max seconds between tracks during warmup"},
        ]
