"""HumanizationConfig - Typed settings loader for humanization behavior."""

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.setting import Setting

logger = logging.getLogger(__name__)


@dataclass
class HumanizationConfig:
    """Typed configuration for humanization behavior."""
    enabled: bool = True
    preset: str = "medium"  # low, medium, high, custom
    # Legacy alias support
    level: str = "medium"  # Backward-compatible alias for preset

    # Pre-stream delays
    pre_stream_min_sec: int = 180
    pre_stream_max_sec: int = 300

    # Between tracks delays
    between_tracks_min_sec: int = 5
    between_tracks_max_sec: int = 15

    # Random actions
    random_actions_enabled: bool = True
    min_actions_per_stream: int = 0
    max_actions_per_stream: int = 3

    # Warmup-specific delays (can be shorter than normal streaming)
    warmup_between_tracks_min_sec: int = 3
    warmup_between_tracks_max_sec: int = 10

    @property
    def effective_preset(self) -> str:
        """Return the effective preset, using preset or falling back to level."""
        return self.preset if self.preset else self.level

    def to_dict(self) -> dict:
        """Convert config to dictionary for serialization."""
        return {
            "humanization_enabled": str(self.enabled).lower(),
            "humanization_preset": self.preset,
            "humanization_level": self.level,
            "pre_stream_min_sec": str(self.pre_stream_min_sec),
            "pre_stream_max_sec": str(self.pre_stream_max_sec),
            "between_tracks_min_sec": str(self.between_tracks_min_sec),
            "between_tracks_max_sec": str(self.between_tracks_max_sec),
            "random_actions_enabled": str(self.random_actions_enabled).lower(),
            "min_actions_per_stream": str(self.min_actions_per_stream),
            "max_actions_per_stream": str(self.max_actions_per_stream),
            "warmup_between_tracks_min_sec": str(self.warmup_between_tracks_min_sec),
            "warmup_between_tracks_max_sec": str(self.warmup_between_tracks_max_sec),
        }


# Preset defaults for convenience
PRESET_DEFAULTS = {
    "low": {
        "pre_stream_min_sec": 60,
        "pre_stream_max_sec": 120,
        "between_tracks_min_sec": 1,
        "between_tracks_max_sec": 3,
        "random_actions_enabled": False,
        "min_actions_per_stream": 0,
        "max_actions_per_stream": 1,
        "warmup_between_tracks_min_sec": 1,
        "warmup_between_tracks_max_sec": 2,
    },
    "medium": {
        "pre_stream_min_sec": 180,
        "pre_stream_max_sec": 300,
        "between_tracks_min_sec": 5,
        "between_tracks_max_sec": 15,
        "random_actions_enabled": True,
        "min_actions_per_stream": 0,
        "max_actions_per_stream": 3,
        "warmup_between_tracks_min_sec": 3,
        "warmup_between_tracks_max_sec": 10,
    },
    "high": {
        "pre_stream_min_sec": 300,
        "pre_stream_max_sec": 480,
        "between_tracks_min_sec": 10,
        "between_tracks_max_sec": 30,
        "random_actions_enabled": True,
        "min_actions_per_stream": 1,
        "max_actions_per_stream": 5,
        "warmup_between_tracks_min_sec": 5,
        "warmup_between_tracks_max_sec": 15,
    },
}

VALID_PRESETS = {"low", "medium", "high", "custom"}
TRUTHY_VALUES = {"true", "1", "yes", "on"}
FALSY_VALUES = {"false", "0", "no", "off"}
HUMANIZATION_SETTING_KEYS = (
    "humanization_enabled",
    "humanization_preset",
    "humanization_level",
    "pre_stream_min_sec",
    "pre_stream_max_sec",
    "between_tracks_min_sec",
    "between_tracks_max_sec",
    "random_actions_enabled",
    "min_actions_per_stream",
    "max_actions_per_stream",
    "warmup_between_tracks_min_sec",
    "warmup_between_tracks_max_sec",
)


def _normalize_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _parse_bool(value: object, default: bool = False) -> bool:
    """Parse string value to boolean."""
    if isinstance(value, bool):
        return value

    normalized = _normalize_string(value)
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSY_VALUES:
        return False
    return default


def _is_bool_like(value: object) -> bool:
    if isinstance(value, bool):
        return True
    normalized = _normalize_string(value)
    return normalized in TRUTHY_VALUES or normalized in FALSY_VALUES


def _parse_int(value: object, default: int) -> int:
    """Parse string value to int with default fallback."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _normalize_range(min_value: int, max_value: int) -> tuple[int, int]:
    min_value = max(0, min_value)
    max_value = max(0, max_value)
    return tuple(sorted((min_value, max_value)))


def apply_preset(preset: str, config: HumanizationConfig) -> HumanizationConfig:
    """Apply preset defaults to config, returning a new config."""
    if preset not in PRESET_DEFAULTS:
        return config

    defaults = PRESET_DEFAULTS[preset]
    return HumanizationConfig(
        enabled=config.enabled,
        preset=preset,
        level=preset,
        pre_stream_min_sec=defaults["pre_stream_min_sec"],
        pre_stream_max_sec=defaults["pre_stream_max_sec"],
        between_tracks_min_sec=defaults["between_tracks_min_sec"],
        between_tracks_max_sec=defaults["between_tracks_max_sec"],
        random_actions_enabled=defaults["random_actions_enabled"],
        min_actions_per_stream=defaults["min_actions_per_stream"],
        max_actions_per_stream=defaults["max_actions_per_stream"],
        warmup_between_tracks_min_sec=defaults["warmup_between_tracks_min_sec"],
        warmup_between_tracks_max_sec=defaults["warmup_between_tracks_max_sec"],
    )


def detect_preset_from_values(config: HumanizationConfig) -> str:
    """Detect if current values match a preset, return 'custom' if not."""
    for preset_name, defaults in PRESET_DEFAULTS.items():
        if (
            config.pre_stream_min_sec == defaults["pre_stream_min_sec"]
            and config.pre_stream_max_sec == defaults["pre_stream_max_sec"]
            and config.between_tracks_min_sec == defaults["between_tracks_min_sec"]
            and config.between_tracks_max_sec == defaults["between_tracks_max_sec"]
            and config.random_actions_enabled == defaults["random_actions_enabled"]
            and config.min_actions_per_stream == defaults["min_actions_per_stream"]
            and config.max_actions_per_stream == defaults["max_actions_per_stream"]
            and config.warmup_between_tracks_min_sec == defaults["warmup_between_tracks_min_sec"]
            and config.warmup_between_tracks_max_sec == defaults["warmup_between_tracks_max_sec"]
        ):
            return preset_name
    return "custom"


class HumanizationConfigService:
    """Service for loading and managing humanization configuration."""

    HUMANIZATION_SETTING_KEYS = HUMANIZATION_SETTING_KEYS

    @staticmethod
    def build_config(settings_dict: dict) -> HumanizationConfig:
        raw_preset = _normalize_string(settings_dict.get("humanization_preset"))
        raw_level = _normalize_string(settings_dict.get("humanization_level"))

        if raw_preset in PRESET_DEFAULTS:
            base_preset = raw_preset
            base_level = raw_preset
        elif raw_preset == "custom":
            base_level = raw_level if raw_level in PRESET_DEFAULTS else "medium"
            base_preset = base_level
        elif raw_level in PRESET_DEFAULTS:
            base_preset = raw_level
            base_level = raw_level
        else:
            base_preset = "medium"
            base_level = "medium"

        preset_defaults = PRESET_DEFAULTS[base_preset]

        pre_stream_min_sec, pre_stream_max_sec = _normalize_range(
            _parse_int(settings_dict.get("pre_stream_min_sec"), preset_defaults["pre_stream_min_sec"]),
            _parse_int(settings_dict.get("pre_stream_max_sec"), preset_defaults["pre_stream_max_sec"]),
        )
        between_tracks_min_sec, between_tracks_max_sec = _normalize_range(
            _parse_int(settings_dict.get("between_tracks_min_sec"), preset_defaults["between_tracks_min_sec"]),
            _parse_int(settings_dict.get("between_tracks_max_sec"), preset_defaults["between_tracks_max_sec"]),
        )
        min_actions_per_stream, max_actions_per_stream = _normalize_range(
            _parse_int(settings_dict.get("min_actions_per_stream"), preset_defaults["min_actions_per_stream"]),
            _parse_int(settings_dict.get("max_actions_per_stream"), preset_defaults["max_actions_per_stream"]),
        )
        warmup_between_tracks_min_sec, warmup_between_tracks_max_sec = _normalize_range(
            _parse_int(settings_dict.get("warmup_between_tracks_min_sec"), preset_defaults["warmup_between_tracks_min_sec"]),
            _parse_int(settings_dict.get("warmup_between_tracks_max_sec"), preset_defaults["warmup_between_tracks_max_sec"]),
        )

        config = HumanizationConfig(
            enabled=_parse_bool(settings_dict.get("humanization_enabled"), True),
            preset=base_preset,
            level=base_level,
            pre_stream_min_sec=pre_stream_min_sec,
            pre_stream_max_sec=pre_stream_max_sec,
            between_tracks_min_sec=between_tracks_min_sec,
            between_tracks_max_sec=between_tracks_max_sec,
            random_actions_enabled=_parse_bool(
                settings_dict.get("random_actions_enabled"),
                preset_defaults["random_actions_enabled"],
            ),
            min_actions_per_stream=min_actions_per_stream,
            max_actions_per_stream=max_actions_per_stream,
            warmup_between_tracks_min_sec=warmup_between_tracks_min_sec,
            warmup_between_tracks_max_sec=warmup_between_tracks_max_sec,
        )

        detected_preset = detect_preset_from_values(config)
        if detected_preset in PRESET_DEFAULTS:
            config.preset = detected_preset
            config.level = detected_preset
        else:
            config.preset = "custom"
            config.level = base_level

        return config

    @staticmethod
    def canonicalize_settings(settings_dict: dict) -> dict:
        return HumanizationConfigService.build_config(settings_dict).to_dict()

    @staticmethod
    async def load_config(db: AsyncSession) -> HumanizationConfig:
        """Load humanization config from database settings."""
        result = await db.execute(select(Setting))
        settings = {s.key: s.value for s in result.scalars().all()}
        return HumanizationConfigService.build_config(settings)

    @staticmethod
    def validate_settings(settings_dict: dict) -> tuple[bool, Optional[str]]:
        """Validate humanization settings. Returns (is_valid, error_message)."""
        # Validate preset if provided
        preset = _normalize_string(settings_dict.get("humanization_preset"))
        if preset and preset not in VALID_PRESETS:
            return False, f"Invalid preset: {preset}. Must be one of: low, medium, high, custom"

        level = _normalize_string(settings_dict.get("humanization_level"))
        if level and level not in PRESET_DEFAULTS:
            return False, f"Invalid humanization_level: {level}. Must be one of: low, medium, high"

        for key in ("humanization_enabled", "random_actions_enabled"):
            if key in settings_dict and settings_dict.get(key) not in ("", None) and not _is_bool_like(settings_dict.get(key)):
                return False, f"Invalid boolean value for {key}"

        # Validate numeric ranges
        numeric_values: dict[str, int] = {}
        for key in [
            "pre_stream_min_sec",
            "pre_stream_max_sec",
            "between_tracks_min_sec",
            "between_tracks_max_sec",
            "min_actions_per_stream",
            "max_actions_per_stream",
            "warmup_between_tracks_min_sec",
            "warmup_between_tracks_max_sec",
        ]:
            val = settings_dict.get(key, "")
            if val in ("", None):
                numeric_values[key] = 0
                continue
            try:
                numeric_values[key] = int(val)
            except (ValueError, TypeError):
                return False, f"Invalid integer value for {key}"

        pre_stream_min = numeric_values["pre_stream_min_sec"]
        pre_stream_max = numeric_values["pre_stream_max_sec"]
        between_min = numeric_values["between_tracks_min_sec"]
        between_max = numeric_values["between_tracks_max_sec"]
        actions_min = numeric_values["min_actions_per_stream"]
        actions_max = numeric_values["max_actions_per_stream"]
        warmup_min = numeric_values["warmup_between_tracks_min_sec"]
        warmup_max = numeric_values["warmup_between_tracks_max_sec"]

        for key, val in numeric_values.items():
            if val < 0:
                return False, f"{key} must be >= 0"

        # Validate min <= max constraints
        if pre_stream_min > pre_stream_max:
            return False, "pre_stream_min_sec must be <= pre_stream_max_sec"

        if between_min > between_max:
            return False, "between_tracks_min_sec must be <= between_tracks_max_sec"

        if actions_min > actions_max:
            return False, "min_actions_per_stream must be <= max_actions_per_stream"

        if warmup_min > warmup_max:
            return False, "warmup_between_tracks_min_sec must be <= warmup_between_tracks_max_sec"

        return True, None

    @staticmethod
    def normalize_settings(settings_dict: dict) -> dict:
        """Normalize settings - apply preset defaults if preset changed."""
        result = dict(settings_dict)

        preset = result.get("humanization_preset", "").lower()
        if preset in PRESET_DEFAULTS:
            result["humanization_level"] = preset
            defaults = PRESET_DEFAULTS[preset]
            for key, val in defaults.items():
                result[key] = str(val)

        # Also handle legacy level key
        level = result.get("humanization_level", "").lower()
        if level in PRESET_DEFAULTS and not preset:
            # If only level is set and no preset, sync preset to level
            result["humanization_level"] = level
            result["humanization_preset"] = level
            defaults = PRESET_DEFAULTS[level]
            for key, val in defaults.items():
                result[key] = str(val)

        return result
