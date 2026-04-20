"""Tests for Phase 6: Anti-Detection & Hardening layer."""

import random
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus, AccountType
from app.models.instance import Instance, InstanceStatus
from app.models.proxy import Proxy, ProxyProtocol, ProxyStatus
from app.models.song import Song, SongStatus, SongPriority
from app.models.fingerprint import DeviceFingerprint
from app.models.stream_log import StreamLog, StreamResult
from app.services.adb_service import ADBService
from app.services.antidetect.fingerprint import FingerprintManager
from app.services.antidetect.behavior_profiles import BehaviorProfileManager, PROFILES, BehaviorProfile
from app.services.antidetect.warmup import WarmupManager
from app.services.antidetect.rate_limiter import RateLimiter
from app.services.automation.humanizer import Humanizer


# ============================================================================
# FingerprintManager Tests
# ============================================================================

class TestFingerprintManager:
    """Tests for device fingerprint generation and application."""

    @pytest_asyncio.fixture
    async def fp_manager(self):
        adb = ADBService()
        return FingerprintManager(adb)

    @pytest.mark.asyncio
    async def test_generate_fingerprint_returns_all_required_fields(self, fp_manager):
        """generate_fingerprint() returns all required fields."""
        fp = await fp_manager.generate_fingerprint()

        required_fields = [
            "android_id", "device_model", "device_brand", "device_manufacturer",
            "build_fingerprint", "gsfid", "screen_density", "locale",
            "timezone", "advertising_id"
        ]
        for field in required_fields:
            assert field in fp, f"Missing required field: {field}"
            assert fp[field] is not None, f"Field {field} is None"

    @pytest.mark.asyncio
    async def test_generate_fingerprint_unique_android_id(self, fp_manager):
        """No two generated fingerprints share the same android_id."""
        fps = []
        for _ in range(20):
            fp = await fp_manager.generate_fingerprint()
            fps.append(fp)

        android_ids = [fp["android_id"] for fp in fps]
        assert len(android_ids) == len(set(android_ids)), "Duplicate android_id found"

    @pytest.mark.asyncio
    async def test_generate_fingerprint_valid_android_id_format(self, fp_manager):
        """android_id is 16 hex characters."""
        fp = await fp_manager.generate_fingerprint()
        assert len(fp["android_id"]) == 16, "android_id must be 16 chars"
        assert all(c in "0123456789abcdef" for c in fp["android_id"]), "android_id must be hex"

    @pytest.mark.asyncio
    async def test_generate_fingerprint_valid_gsfid_format(self, fp_manager):
        """gsfid is a 19-digit integer string."""
        fp = await fp_manager.generate_fingerprint()
        assert len(fp["gsfid"]) == 19, "gsfid must be 19 digits"
        assert fp["gsfid"].isdigit(), "gsfid must be numeric"

    @pytest.mark.asyncio
    async def test_generate_fingerprint_valid_uuid_format(self, fp_manager):
        """advertising_id is a valid UUID v4."""
        fp = await fp_manager.generate_fingerprint()
        try:
            uuid.UUID(fp["advertising_id"])
        except ValueError:
            pytest.fail("advertising_id is not a valid UUID")

    @pytest.mark.asyncio
    async def test_apply_fingerprint_mock_mode_returns_true(self, fp_manager, monkeypatch):
        """apply_fingerprint() in mock mode returns True."""
        monkeypatch.setattr(fp_manager, "mock_mode", True)
        fp = await fp_manager.generate_fingerprint()
        result = await fp_manager.apply_fingerprint("localhost:5555", fp)
        assert result is True

    @pytest.mark.asyncio
    async def test_store_and_get_fingerprint(self, db_session: AsyncSession, fp_manager):
        """store_fingerprint() persists to DB, get_fingerprint() retrieves it."""
        # Create test instance
        instance = Instance(
            name="test-fp-instance",
            status=InstanceStatus.RUNNING,
            adb_port=5555
        )
        db_session.add(instance)
        await db_session.flush()

        # Generate and store fingerprint
        fp = await fp_manager.generate_fingerprint()
        await fp_manager.store_fingerprint(instance.id, fp, db_session)
        await db_session.commit()

        # Retrieve fingerprint
        retrieved = await fp_manager.get_fingerprint(instance.id, db_session)
        assert retrieved is not None
        assert retrieved.android_id == fp["android_id"]
        assert retrieved.device_model == fp["device_model"]
        assert retrieved.device_brand == fp["device_brand"]


# ============================================================================
# BehaviorProfileManager Tests
# ============================================================================

class TestBehaviorProfileManager:
    """Tests for behavior profile assignment and queries."""

    @pytest_asyncio.fixture
    async def bp_manager(self):
        return BehaviorProfileManager()

    @pytest.mark.asyncio
    async def test_all_profiles_are_valid(self, bp_manager):
        """All 6+ profiles are valid with fields within expected ranges."""
        required_profiles = [
            "casual_listener", "playlist_addict", "commuter",
            "workout_listener", "night_owl", "background_listener"
        ]

        for profile_name in required_profiles:
            profile = bp_manager.get_profile(profile_name)
            assert profile is not None, f"Profile {profile_name} not found"
            assert profile.name == profile_name
            assert 0 <= profile.active_hours_start <= 23
            assert 0 <= profile.active_hours_end <= 23
            assert 0 <= profile.skip_probability <= 1.0
            assert profile.session_length_min <= profile.session_length_max
            assert profile.session_length_mean >= profile.session_length_min
            assert profile.session_length_mean <= profile.session_length_max

    @pytest.mark.asyncio
    async def test_is_active_hour_returns_true_during_active_window(self, bp_manager):
        """is_active_hour() returns True during active window."""
        profile = bp_manager.get_profile("casual_listener")
        # casual_listener active 8-23, peak 19
        # At peak hour should be True
        result = bp_manager.is_active_hour(profile, 19)
        # Due to gaussian probability, we test multiple times
        results = [bp_manager.is_active_hour(profile, 19) for _ in range(100)]
        assert any(results), "Should sometimes return True at peak hour"

    @pytest.mark.asyncio
    async def test_is_active_hour_returns_false_outside_window(self, bp_manager):
        """is_active_hour() returns False outside active window."""
        profile = bp_manager.get_profile("casual_listener")
        # casual_listener active 8-23, hour 3 is outside
        result = bp_manager.is_active_hour(profile, 3)
        assert result is False, "Should return False outside active hours"

    @pytest.mark.asyncio
    async def test_should_skip_track_respects_probability(self, bp_manager):
        """should_skip_track() respects probability distribution."""
        profile = BehaviorProfile(
            name="test_profile",
            active_hours_start=0, active_hours_end=23, peak_hour=12,
            session_length_min=10, session_length_max=30, session_length_mean=20,
            tracks_per_session_min=5, tracks_per_session_max=10,
            skip_probability=0.5
        )

        # Run 1000 trials
        skips = sum(bp_manager.should_skip_track(profile) for _ in range(1000))
        # With p=0.5, we expect ~500 skips (allow wide margin for randomness)
        assert 400 < skips < 600, f"Skip rate should be around 50%, got {skips/10:.1f}%"

    @pytest.mark.asyncio
    async def test_get_session_length_within_bounds(self, bp_manager):
        """get_session_length() returns values within min/max bounds."""
        profile = bp_manager.get_profile("casual_listener")
        lengths = [bp_manager.get_session_length(profile) for _ in range(100)]
        assert all(profile.session_length_min <= l <= profile.session_length_max for l in lengths)

    @pytest.mark.asyncio
    async def test_assign_profile_persists_to_instance(self, db_session: AsyncSession, bp_manager):
        """assign_profile() stores profile name in Instance."""
        instance = Instance(
            name="test-bp-instance",
            status=InstanceStatus.RUNNING,
            adb_port=5556
        )
        db_session.add(instance)
        await db_session.flush()

        profile_name = await bp_manager.assign_profile(instance.id, db_session)
        await db_session.commit()

        assert profile_name in PROFILES.keys()
        assert instance.behavior_profile == profile_name


# ============================================================================
# WarmupManager Tests
# ============================================================================

class TestWarmupManager:
    """Tests for warmup sequence management."""

    @pytest_asyncio.fixture
    async def warmup_manager(self):
        return WarmupManager()

    @pytest_asyncio.fixture
    async def test_account(self, db_session: AsyncSession):
        """Create a test account in WARMING status."""
        proxy = Proxy(
            host=f"10.0.1.{random.randint(1, 254)}",
            port=random.randint(10000, 60000),
            protocol=ProxyProtocol.SOCKS5,
            status=ProxyStatus.HEALTHY
        )
        db_session.add(proxy)
        await db_session.flush()

        account = Account(
            email=f"warmup_test_{uuid.uuid4().hex[:6]}@example.com",
            type=AccountType.FREE,
            status=AccountStatus.WARMING,
            warmup_day=1,
            proxy_id=proxy.id
        )
        db_session.add(account)
        await db_session.flush()
        return account

    @pytest_asyncio.fixture
    async def test_instance(self, db_session: AsyncSession):
        """Create a test instance."""
        instance = Instance(
            name=f"warmup-test-{uuid.uuid4().hex[:6]}",
            status=InstanceStatus.RUNNING,
            adb_port=random.randint(5560, 5999)
        )
        db_session.add(instance)
        await db_session.flush()
        return instance

    @pytest.mark.asyncio
    async def test_get_warmup_plan_returns_correct_plan_for_each_day(self, warmup_manager, test_account, db_session):
        """Correct plan returned for each warmup day (1-5)."""
        for day in range(1, 6):
            test_account.warmup_day = day
            plan = await warmup_manager.get_warmup_plan(test_account, db_session)
            assert plan is not None, f"Plan should exist for day {day}"
            assert "actions" in plan
            assert "description" in plan

    @pytest.mark.asyncio
    async def test_get_warmup_plan_returns_none_when_complete(self, warmup_manager, test_account, db_session):
        """get_warmup_plan() returns None when warmup is complete."""
        test_account.warmup_day = 6  # Beyond 5-day warmup
        plan = await warmup_manager.get_warmup_plan(test_account, db_session)
        assert plan is None

    @pytest.mark.asyncio
    async def test_execute_warmup_day_increments_warmup_day(self, warmup_manager, test_account, test_instance, db_session, monkeypatch):
        """execute_warmup_day() increments warmup_day."""
        # Mock all ADB operations
        monkeypatch.setattr(warmup_manager, "mock_mode", True)

        initial_day = test_account.warmup_day
        result = await warmup_manager.execute_warmup_day(test_instance, test_account, db_session)

        assert result is True
        assert test_account.warmup_day == initial_day + 1

    @pytest.mark.asyncio
    async def test_account_transitions_to_active_after_final_warmup_day(self, warmup_manager, test_instance, db_session, monkeypatch):
        """Account transitions from WARMING -> ACTIVE after final warmup day."""
        # Create account at final warmup day
        proxy = Proxy(
            host=f"10.0.3.{random.randint(1, 254)}",
            port=random.randint(10000, 60000),
            protocol=ProxyProtocol.SOCKS5,
            status=ProxyStatus.HEALTHY
        )
        db_session.add(proxy)
        await db_session.flush()

        account = Account(
            email=f"final_warmup_{uuid.uuid4().hex[:6]}@example.com",
            type=AccountType.FREE,
            status=AccountStatus.WARMING,
            warmup_day=5,  # Final day
            proxy_id=proxy.id
        )
        db_session.add(account)
        await db_session.flush()

        monkeypatch.setattr(warmup_manager, "mock_mode", True)

        await warmup_manager.execute_warmup_day(test_instance, account, db_session)

        assert account.status == AccountStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_warmup_tick_executes_for_warming_accounts(self, db_session: AsyncSession, monkeypatch):
        """Warmup tick executes execute_warmup_day for WARMING accounts with running instances."""
        from app.services.automation.song_scheduler import SongScheduler
        from tests.conftest import TestingSessionLocal

        # Create WARMING account
        proxy = Proxy(
            host=f"10.0.4.{random.randint(1, 254)}",
            port=random.randint(10000, 60000),
            protocol=ProxyProtocol.SOCKS5,
            status=ProxyStatus.HEALTHY
        )
        db_session.add(proxy)
        await db_session.flush()

        account = Account(
            email=f"warmup_tick_{uuid.uuid4().hex[:6]}@example.com",
            type=AccountType.FREE,
            status=AccountStatus.WARMING,
            warmup_day=1,
            proxy_id=proxy.id
        )
        db_session.add(account)
        await db_session.flush()

        # Create running instance assigned to account
        instance = Instance(
            name=f"warmup-tick-instance-{uuid.uuid4().hex[:6]}",
            status=InstanceStatus.RUNNING,
            adb_port=random.randint(5560, 5999),
            assigned_account_id=account.id,
            behavior_profile="casual_listener"
        )
        db_session.add(instance)
        await db_session.commit()

        # Create scheduler using test session maker so it sees test data
        scheduler = SongScheduler(TestingSessionLocal)
        monkeypatch.setattr(scheduler.warmup_manager, "mock_mode", True)
        monkeypatch.setattr(scheduler, "stats", {"scheduler_state": "running"})

        initial_day = account.warmup_day

        # Execute warmup tick
        await scheduler._warmup_tick()

        # Refresh account from DB to see changes made by the scheduler's session
        await db_session.refresh(account)

        # Verify warmup_day was incremented
        assert account.warmup_day == initial_day + 1

    @pytest.mark.asyncio
    async def test_warmup_tick_skips_if_already_done_today(self, db_session: AsyncSession, monkeypatch):
        """Warmup tick skips accounts that already have a warmup stream log today."""
        from app.services.automation.song_scheduler import SongScheduler
        from tests.conftest import TestingSessionLocal

        # Create WARMING account
        proxy = Proxy(
            host=f"10.0.5.{random.randint(1, 254)}",
            port=random.randint(10000, 60000),
            protocol=ProxyProtocol.SOCKS5,
            status=ProxyStatus.HEALTHY
        )
        db_session.add(proxy)
        await db_session.flush()

        account = Account(
            email=f"warmup_skip_{uuid.uuid4().hex[:6]}@example.com",
            type=AccountType.FREE,
            status=AccountStatus.WARMING,
            warmup_day=1,
            proxy_id=proxy.id
        )
        db_session.add(account)
        await db_session.flush()

        # Create running instance assigned to account
        instance = Instance(
            name=f"warmup-skip-instance-{uuid.uuid4().hex[:6]}",
            status=InstanceStatus.RUNNING,
            adb_port=random.randint(5560, 5999),
            assigned_account_id=account.id,
            behavior_profile="casual_listener"
        )
        db_session.add(instance)
        await db_session.flush()

        # Create a warmup stream log for today
        warmup_log = StreamLog(
            instance_id=instance.id,
            account_id=account.id,
            song_id=None,
            spotify_uri="warmup:day_1",
            started_at=datetime.now(timezone.utc),
            duration_sec=1200,
            verified=True,
            result=StreamResult.HEALTH_CHECK
        )
        db_session.add(warmup_log)
        await db_session.commit()

        # Create scheduler using test session maker
        scheduler = SongScheduler(TestingSessionLocal)
        monkeypatch.setattr(scheduler.warmup_manager, "mock_mode", True)
        monkeypatch.setattr(scheduler, "stats", {"scheduler_state": "running"})

        initial_day = account.warmup_day

        # Execute warmup tick - should skip since already done today
        await scheduler._warmup_tick()

        # Refresh account from DB
        await db_session.refresh(account)

        # Verify warmup_day was NOT incremented (still 1)
        assert account.warmup_day == initial_day

    @pytest.mark.asyncio
    async def test_no_double_increment_warmup_day(self, db_session: AsyncSession, monkeypatch):
        """Verify warmup_day increments exactly once per day via warmup_tick only."""
        from app.services.automation.song_scheduler import SongScheduler
        from tests.conftest import TestingSessionLocal

        # Create WARMING account
        proxy = Proxy(
            host=f"10.0.6.{random.randint(1, 254)}",
            port=random.randint(10000, 60000),
            protocol=ProxyProtocol.SOCKS5,
            status=ProxyStatus.HEALTHY
        )
        db_session.add(proxy)
        await db_session.flush()

        account = Account(
            email=f"no_double_{uuid.uuid4().hex[:6]}@example.com",
            type=AccountType.FREE,
            status=AccountStatus.WARMING,
            warmup_day=1,
            proxy_id=proxy.id
        )
        db_session.add(account)
        await db_session.flush()

        # Create running instance assigned to account
        instance = Instance(
            name=f"no-double-instance-{uuid.uuid4().hex[:6]}",
            status=InstanceStatus.RUNNING,
            adb_port=random.randint(5560, 5999),
            assigned_account_id=account.id,
            behavior_profile="casual_listener"
        )
        db_session.add(instance)
        await db_session.commit()

        # Create scheduler using test session maker
        scheduler = SongScheduler(TestingSessionLocal)
        monkeypatch.setattr(scheduler.warmup_manager, "mock_mode", True)
        monkeypatch.setattr(scheduler, "stats", {"scheduler_state": "running"})

        initial_day = account.warmup_day

        # Execute warmup tick once
        await scheduler._warmup_tick()

        # Refresh account from DB to see changes
        await db_session.refresh(account)

        # Verify warmup_day incremented by exactly 1
        assert account.warmup_day == initial_day + 1

        # Execute _daily_reset (should NOT increment warmup_day anymore)
        await scheduler._daily_reset()

        # Refresh again
        await db_session.refresh(account)

        # Verify warmup_day still at +1 (no double increment)
        assert account.warmup_day == initial_day + 1


# ============================================================================
# RateLimiter Tests
# ============================================================================

class TestRateLimiter:
    """Tests for multi-level rate limiting."""

    @pytest_asyncio.fixture
    async def rate_limiter(self):
        from app.database import async_session_maker
        return RateLimiter(async_session_maker)

    @pytest_asyncio.fixture
    async def test_account(self, db_session: AsyncSession):
        """Create a test account."""
        proxy = Proxy(
            host=f"10.0.2.{random.randint(1, 254)}",
            port=random.randint(10000, 60000),
            protocol=ProxyProtocol.SOCKS5,
            status=ProxyStatus.HEALTHY
        )
        db_session.add(proxy)
        await db_session.flush()

        account = Account(
            email=f"rate_test_{uuid.uuid4().hex[:6]}@example.com",
            type=AccountType.FREE,
            status=AccountStatus.ACTIVE,
            proxy_id=proxy.id
        )
        db_session.add(account)
        await db_session.flush()
        return account

    @pytest_asyncio.fixture
    async def test_instance(self, db_session: AsyncSession):
        """Create a test instance without behavior profile (avoids non-deterministic active hour check)."""
        instance = Instance(
            name=f"rate-test-{uuid.uuid4().hex[:6]}",
            status=InstanceStatus.RUNNING,
            adb_port=random.randint(5560, 5999),
            behavior_profile=None
        )
        db_session.add(instance)
        await db_session.flush()
        return instance

    @pytest_asyncio.fixture
    async def test_song(self, db_session: AsyncSession):
        """Create a test song."""
        song = Song(
            spotify_uri=f"spotify:track:test_{uuid.uuid4().hex[:8]}",
            title="Test Song",
            artist="Test Artist",
            total_target_streams=100,
            daily_rate=10,
            status=SongStatus.ACTIVE,
            priority=SongPriority.MEDIUM
        )
        db_session.add(song)
        await db_session.flush()
        return song

    @pytest.mark.asyncio
    async def test_can_stream_allows_when_all_checks_pass(self, rate_limiter, test_account, test_instance, test_song, db_session, monkeypatch):
        """can_stream() allows when all checks pass."""
        # Clear any existing active streams
        rate_limiter._active_streams.clear()

        allowed, reason = await rate_limiter.can_stream(test_instance, test_account, test_song, db_session)
        assert allowed is True
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_register_stream_start_end_manages_active_set(self, rate_limiter, test_account, test_instance):
        """register_stream_start/end correctly manage active set."""
        # Clear active streams
        rate_limiter._active_streams.clear()

        await rate_limiter.register_stream_start(test_instance.id, test_account.id)
        assert test_instance.id in rate_limiter._active_streams
        assert rate_limiter.get_status()["active_streams"] == 1

        await rate_limiter.register_stream_end(test_instance.id, test_account.id)
        assert test_instance.id not in rate_limiter._active_streams
        assert rate_limiter.get_status()["active_streams"] == 0

    @pytest.mark.asyncio
    async def test_get_status_returns_correct_data(self, rate_limiter):
        """get_status() returns current rate limiter status."""
        status = rate_limiter.get_status()
        assert "active_streams" in status
        assert "active_stream_instance_ids" in status
        assert "tracked_instances" in status
        assert "tracked_accounts" in status


# ============================================================================
# Integration Tests
# ============================================================================

class TestAntiDetectionIntegration:
    """Integration tests for the anti-detection layer."""

    @pytest.mark.asyncio
    async def test_end_to_end_fingerprint_creation(self, db_session: AsyncSession):
        """Full flow: create instance, generate fingerprint, verify persistence."""
        from app.services.instance_manager import InstanceManager

        manager = InstanceManager(db_session)

        # Create instance (triggers fingerprint generation)
        instance = await manager.create_instance(
            name="integration-test-instance",
            ram_limit_mb=2048,
            cpu_cores=2.0
        )

        # Verify instance has behavior profile
        assert instance.behavior_profile is not None
        assert instance.behavior_profile in PROFILES.keys()

        # Verify fingerprint exists in DB
        from app.services.antidetect.fingerprint import FingerprintManager
        fp_manager = FingerprintManager()
        fp = await fp_manager.get_fingerprint(instance.id, db_session)
        assert fp is not None
        assert len(fp.android_id) == 16
