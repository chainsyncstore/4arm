from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.setting import Setting
from app.schemas.setting import SettingsResponse, SettingsUpdate
from app.services.humanization_config import HumanizationConfigService
from prometheus_client import Counter

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Phase 9: Humanization metrics
HUMANIZATION_SETTINGS_UPDATES_TOTAL = Counter(
    "humanization_settings_updates_total",
    "Total successful humanization settings updates"
)
HUMANIZATION_VALIDATION_FAILURES_TOTAL = Counter(
    "humanization_validation_failures_total",
    "Total rejected invalid settings updates"
)
HUMANIZATION_PRESET_APPLIED_TOTAL = Counter(
    "humanization_preset_applied_total",
    "Total preset applications",
    ["preset"]
)
HUMANIZATION_SETTING_KEYS = set(HumanizationConfigService.HUMANIZATION_SETTING_KEYS)
DEFAULT_SETTINGS = {default["key"]: default for default in Setting.default_settings()}


def repair_humanization_settings(db: AsyncSession, settings_by_key: dict[str, Setting]) -> bool:
    canonical_settings = HumanizationConfigService.canonicalize_settings(
        {key: setting.value for key, setting in settings_by_key.items()}
    )
    repaired = False

    for key in HumanizationConfigService.HUMANIZATION_SETTING_KEYS:
        canonical_value = canonical_settings[key]
        setting = settings_by_key.get(key)

        if setting is None:
            default = DEFAULT_SETTINGS[key]
            setting = Setting(
                key=key,
                value=canonical_value,
                description=default["description"],
            )
            db.add(setting)
            settings_by_key[key] = setting
            repaired = True
            continue

        if setting.value != canonical_value:
            setting.value = canonical_value
            repaired = True

    return repaired


async def seed_default_settings(db: AsyncSession):
    """Seed default settings if none exist."""
    result = await db.execute(select(Setting))
    existing = result.scalars().all()
    settings_by_key = {setting.key: setting for setting in existing}

    changed = False
    for default in DEFAULT_SETTINGS.values():
        if default["key"] in settings_by_key:
            continue
        setting = Setting(
            key=default["key"],
            value=default["value"],
            description=default["description"]
        )
        db.add(setting)
        settings_by_key[setting.key] = setting
        changed = True

    if repair_humanization_settings(db, settings_by_key):
        changed = True

    if changed:
        await db.commit()

    return changed


@router.get("/", response_model=SettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db)
) -> SettingsResponse:
    """Get all settings as key-value object."""
    result = await db.execute(select(Setting))
    settings = result.scalars().all()

    return SettingsResponse(
        settings={s.key: s.value for s in settings}
    )


@router.patch("/")
async def update_settings(
    data: SettingsUpdate,
    db: AsyncSession = Depends(get_db)
) -> SettingsResponse:
    """Update settings (key: value pairs)."""
    # Phase 9: Validate humanization settings if present
    existing_result = await db.execute(select(Setting))
    existing_settings = {setting.key: setting.value for setting in existing_result.scalars().all()}

    # Phase 9: Normalize settings (apply preset defaults)
    normalized_settings = HumanizationConfigService.normalize_settings(data.settings)

    if any(k in normalized_settings for k in HUMANIZATION_SETTING_KEYS):
        canonical_existing_humanization = HumanizationConfigService.canonicalize_settings(existing_settings)
        merged_settings = {
            **existing_settings,
            **canonical_existing_humanization,
            **normalized_settings,
        }
        is_valid, error_msg = HumanizationConfigService.validate_settings(merged_settings)
        if not is_valid:
            HUMANIZATION_VALIDATION_FAILURES_TOTAL.inc()
            raise HTTPException(status_code=400, detail=f"Invalid settings: {error_msg}")

        canonical_humanization_settings = HumanizationConfigService.canonicalize_settings(merged_settings)
        for key in HumanizationConfigService.HUMANIZATION_SETTING_KEYS:
            normalized_settings[key] = canonical_humanization_settings[key]

    for key, value in normalized_settings.items():
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
        else:
            # Create new setting
            setting = Setting(key=key, value=value)
            db.add(setting)

    await db.commit()

    # Phase 9: Record metrics for successful updates
    if any(k in data.settings for k in HUMANIZATION_SETTING_KEYS):
        HUMANIZATION_SETTINGS_UPDATES_TOTAL.inc()
        preset = normalized_settings.get("humanization_preset", "")
        if preset:
            HUMANIZATION_PRESET_APPLIED_TOTAL.labels(preset=preset).inc()

    # Return updated settings
    result = await db.execute(select(Setting))
    settings = result.scalars().all()

    return SettingsResponse(
        settings={s.key: s.value for s in settings}
    )
