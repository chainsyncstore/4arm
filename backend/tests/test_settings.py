import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.setting import Setting
from app.routers.settings import seed_default_settings, update_settings
from app.schemas.setting import SettingsUpdate
from app.services.humanization_config import HumanizationConfigService


@pytest.mark.asyncio
async def test_get_settings(client: AsyncClient):
    """Test getting all settings."""
    response = await client.get("/api/settings/")

    assert response.status_code == 200
    data = response.json()
    assert "settings" in data
    # Should have default settings seeded
    assert "max_streams_per_account_per_day" in data["settings"]
    assert "rotation_interval_streams" in data["settings"]


@pytest.mark.asyncio
async def test_get_settings_includes_humanization_defaults(client: AsyncClient):
    """Phase 9: Test that humanization settings are seeded by default."""
    response = await client.get("/api/settings/")

    assert response.status_code == 200
    data = response.json()
    # Phase 9: New humanization settings should be present
    assert "humanization_enabled" in data["settings"]
    assert "humanization_preset" in data["settings"]
    assert "humanization_level" in data["settings"]
    assert "pre_stream_min_sec" in data["settings"]
    assert "pre_stream_max_sec" in data["settings"]
    assert "between_tracks_min_sec" in data["settings"]
    assert "between_tracks_max_sec" in data["settings"]
    assert "random_actions_enabled" in data["settings"]
    assert "min_actions_per_stream" in data["settings"]
    assert "max_actions_per_stream" in data["settings"]
    assert "warmup_between_tracks_min_sec" in data["settings"]
    assert "warmup_between_tracks_max_sec" in data["settings"]


@pytest.mark.asyncio
async def test_update_settings(client: AsyncClient):
    """Test updating settings."""
    response = await client.patch("/api/settings/", json={
        "settings": {
            "max_streams_per_account_per_day": "50",
            "rotation_interval_streams": "20"
        }
    })

    assert response.status_code == 200
    data = response.json()
    assert data["settings"]["max_streams_per_account_per_day"] == "50"
    assert data["settings"]["rotation_interval_streams"] == "20"


@pytest.mark.asyncio
async def test_persist_settings(client: AsyncClient):
    """Test that settings persist across requests."""
    # Set a custom setting
    await client.patch("/api/settings/", json={
        "settings": {
            "custom_key": "custom_value"
        }
    })

    # Get settings and verify
    response = await client.get("/api/settings/")
    data = response.json()
    assert data["settings"]["custom_key"] == "custom_value"


@pytest.mark.asyncio
async def test_humanization_validation_rejects_invalid_preset(client: AsyncClient):
    """Phase 9: Test that invalid preset returns 400."""
    response = await client.patch("/api/settings/", json={
        "settings": {
            "humanization_preset": "invalid_preset"
        }
    })

    assert response.status_code == 400
    assert "Invalid" in response.json()["detail"]


@pytest.mark.asyncio
async def test_humanization_validation_rejects_min_greater_than_max(client: AsyncClient):
    """Phase 9: Test that pre_stream_min > pre_stream_max returns 400."""
    response = await client.patch("/api/settings/", json={
        "settings": {
            "pre_stream_min_sec": "300",
            "pre_stream_max_sec": "100"
        }
    })

    assert response.status_code == 400
    assert "min" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_humanization_preset_applies_defaults(client: AsyncClient):
    """Phase 9: Test that selecting low preset applies low defaults."""
    response = await client.patch("/api/settings/", json={
        "settings": {
            "humanization_preset": "low"
        }
    })

    assert response.status_code == 200
    data = response.json()
    assert data["settings"]["humanization_preset"] == "low"
    assert data["settings"]["humanization_level"] == "low"
    assert data["settings"]["pre_stream_min_sec"] == "60"
    assert data["settings"]["pre_stream_max_sec"] == "120"


@pytest.mark.asyncio
async def test_humanization_legacy_level_still_works(client: AsyncClient):
    """Phase 9: Test that legacy humanization_level still works as compat alias."""
    response = await client.patch("/api/settings/", json={
        "settings": {
            "humanization_level": "high"
        }
    })

    assert response.status_code == 200
    data = response.json()
    # Level should be updated and preset should sync
    assert data["settings"]["humanization_level"] == "high"
    assert data["settings"]["humanization_preset"] == "high"


@pytest.mark.asyncio
async def test_humanization_new_keys_persist(client: AsyncClient):
    """Phase 9: Test that new humanization keys persist correctly."""
    response = await client.patch("/api/settings/", json={
        "settings": {
            "humanization_enabled": "false",
            "random_actions_enabled": "false",
            "min_actions_per_stream": "5",
            "max_actions_per_stream": "10"
        }
    })

    assert response.status_code == 200
    data = response.json()
    assert data["settings"]["humanization_enabled"] == "false"
    assert data["settings"]["random_actions_enabled"] == "false"
    assert data["settings"]["min_actions_per_stream"] == "5"
    assert data["settings"]["max_actions_per_stream"] == "10"

    # Verify persistence
    response = await client.get("/api/settings/")
    data = response.json()
    assert data["settings"]["humanization_enabled"] == "false"


@pytest.mark.asyncio
async def test_humanization_partial_update_rejects_invalid_combined_range(client: AsyncClient):
    response = await client.patch("/api/settings/", json={
        "settings": {
            "pre_stream_max_sec": "100"
        }
    })

    assert response.status_code == 400
    assert "pre_stream_min_sec" in response.json()["detail"]


@pytest.mark.asyncio
async def test_humanization_validation_rejects_negative_action_counts(client: AsyncClient):
    response = await client.patch("/api/settings/", json={
        "settings": {
            "min_actions_per_stream": "-2"
        }
    })

    assert response.status_code == 400
    assert "min_actions_per_stream" in response.json()["detail"]


@pytest.mark.asyncio
async def test_humanization_validation_rejects_invalid_boolean_value(client: AsyncClient):
    response = await client.patch("/api/settings/", json={
        "settings": {
            "humanization_enabled": "maybe"
        }
    })

    assert response.status_code == 400
    assert "boolean" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_load_config_uses_preset_defaults_for_missing_humanization_keys(db_session):
    db_session.add(Setting(key="humanization_level", value="high"))
    await db_session.flush()

    config = await HumanizationConfigService.load_config(db_session)

    assert config.level == "high"
    assert config.pre_stream_min_sec == 300
    assert config.pre_stream_max_sec == 480
    assert config.between_tracks_min_sec == 10
    assert config.max_actions_per_stream == 5
    assert config.warmup_between_tracks_max_sec == 15


@pytest.mark.asyncio
async def test_seed_default_settings_backfills_missing_humanization_keys(db_session):
    db_session.add(Setting(key="max_streams_per_account_per_day", value="40"))
    await db_session.commit()

    inserted = await seed_default_settings(db_session)
    result = await db_session.execute(
        select(Setting).where(Setting.key == "humanization_enabled")
    )

    assert inserted is True
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_seed_default_settings_repairs_invalid_humanization_values(db_session):
    db_session.add_all([
        Setting(key="humanization_enabled", value="maybe"),
        Setting(key="humanization_preset", value="broken"),
        Setting(key="humanization_level", value="broken"),
        Setting(key="pre_stream_min_sec", value="-10"),
        Setting(key="pre_stream_max_sec", value="2"),
        Setting(key="between_tracks_min_sec", value="20"),
        Setting(key="between_tracks_max_sec", value="5"),
        Setting(key="random_actions_enabled", value="sometimes"),
        Setting(key="min_actions_per_stream", value="-3"),
        Setting(key="max_actions_per_stream", value="2"),
        Setting(key="warmup_between_tracks_min_sec", value="9"),
        Setting(key="warmup_between_tracks_max_sec", value="-1"),
    ])
    await db_session.commit()

    changed = await seed_default_settings(db_session)
    result = await db_session.execute(select(Setting))
    settings = {setting.key: setting.value for setting in result.scalars().all()}

    assert changed is True
    assert settings["humanization_enabled"] == "true"
    assert settings["humanization_preset"] == "custom"
    assert settings["humanization_level"] == "medium"
    assert settings["pre_stream_min_sec"] == "0"
    assert settings["pre_stream_max_sec"] == "2"
    assert settings["between_tracks_min_sec"] == "5"
    assert settings["between_tracks_max_sec"] == "20"
    assert settings["random_actions_enabled"] == "true"
    assert settings["min_actions_per_stream"] == "0"
    assert settings["max_actions_per_stream"] == "2"
    assert settings["warmup_between_tracks_min_sec"] == "0"
    assert settings["warmup_between_tracks_max_sec"] == "9"


@pytest.mark.asyncio
async def test_update_settings_repairs_existing_invalid_humanization_values(db_session):
    await seed_default_settings(db_session)

    result = await db_session.execute(select(Setting))
    settings_by_key = {setting.key: setting for setting in result.scalars().all()}
    settings_by_key["humanization_preset"].value = "oops"
    settings_by_key["humanization_level"].value = "oops"
    settings_by_key["pre_stream_min_sec"].value = "50"
    settings_by_key["pre_stream_max_sec"].value = "10"
    settings_by_key["random_actions_enabled"].value = "nope"
    settings_by_key["min_actions_per_stream"].value = "-4"
    settings_by_key["max_actions_per_stream"].value = "1"
    await db_session.commit()

    response = await update_settings(
        SettingsUpdate(settings={"humanization_enabled": "false"}),
        db_session,
    )

    assert response.settings["humanization_enabled"] == "false"
    assert response.settings["humanization_preset"] == "custom"
    assert response.settings["humanization_level"] == "medium"
    assert response.settings["pre_stream_min_sec"] == "10"
    assert response.settings["pre_stream_max_sec"] == "50"
    assert response.settings["random_actions_enabled"] == "true"
    assert response.settings["min_actions_per_stream"] == "0"
    assert response.settings["max_actions_per_stream"] == "1"
