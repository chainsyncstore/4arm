"""Tests for Phase 3 Automation Engine."""

import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.automation.spotify_controller import SpotifyController
from app.services.automation.humanizer import Humanizer
from app.services.automation.stream_worker import StreamWorker
from app.services.automation.account_rotator import AccountRotator
from app.services.automation.song_scheduler import SongScheduler
from app.services.automation.health_monitor import HealthMonitor
from app.services.humanization_config import HumanizationConfig
from app.services.adb_service import ADBService
from app.models.instance import Instance, InstanceStatus
from app.models.account import Account, AccountStatus, AccountType
from app.models.song import Song, SongStatus, SongPriority
from app.models.stream_log import StreamLog, StreamResult
from app.models.proxy import Proxy, ProxyStatus


@pytest.fixture
def mock_adb():
    """Create a mock ADB service."""
    adb = MagicMock(spec=ADBService)
    adb.mock_mode = True
    adb.connect = AsyncMock(return_value=True)
    adb.launch_app = AsyncMock(return_value=True)
    adb.force_stop = AsyncMock(return_value=True)
    adb.is_app_running = AsyncMock(return_value=True)
    adb.get_screen_xml = AsyncMock(return_value="<mock>ui</mock>")
    adb.inject_session = AsyncMock(return_value=True)
    adb.tap = AsyncMock(return_value=True)
    adb.send_keyevent = AsyncMock(return_value=True)
    return adb


@pytest.fixture
def sample_instance():
    """Create a sample instance for testing."""
    return Instance(
        id=uuid.uuid4(),
        name="test-instance-1",
        docker_id="mock-docker-123",
        status=InstanceStatus.RUNNING,
        adb_port=5555,
        ram_limit_mb=2048,
        cpu_cores=2.0
    )


@pytest.fixture
def sample_account():
    """Create a sample account for testing."""
    account = Account(
        id=uuid.uuid4(),
        email="test@example.com",
        type=AccountType.PREMIUM,
        status=AccountStatus.ACTIVE,
        streams_today=5,
        total_streams=100
    )
    return account


@pytest.fixture
def sample_song():
    """Create a sample song for testing."""
    return Song(
        id=uuid.uuid4(),
        spotify_uri="spotify:track:1234567890",
        title="Test Song",
        artist="Test Artist",
        total_target_streams=1000,
        daily_rate=100,
        completed_streams=500,
        streams_today=50,
        priority=SongPriority.MEDIUM,
        status=SongStatus.ACTIVE
    )


class TestSpotifyController:
    """Tests for SpotifyController."""

    @pytest.mark.asyncio
    async def test_launch_spotify_mock(self, mock_adb):
        """Test launching Spotify in mock mode."""
        controller = SpotifyController(mock_adb)
        result = await controller.launch_spotify("localhost:5555")
        assert result is True
        # In mock mode, ADB calls are skipped — no adb.launch_app call expected

    @pytest.mark.asyncio
    async def test_play_track_premium_mock(self, mock_adb):
        """Test playing track for premium account in mock mode."""
        controller = SpotifyController(mock_adb)
        result = await controller.play_track_premium(
            "localhost:5555",
            "spotify:track:12345"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_play_track_free_mock(self, mock_adb):
        """Test playing track for free account in mock mode."""
        controller = SpotifyController(mock_adb)
        result = await controller.play_track_free(
            "localhost:5555",
            "spotify:track:12345",
            "Test Artist"
        )
        assert result["played"] is True
        assert "track_matched" in result
        assert "actual_track" in result

    @pytest.mark.asyncio
    async def test_verify_playing_mock(self, mock_adb):
        """Test verifying playback in mock mode."""
        controller = SpotifyController(mock_adb)
        result = await controller.verify_playing("localhost:5555", "Test Song")
        assert result["is_playing"] is True
        assert result["track_name"] == "Test Song"
        assert "progress_sec" in result

    @pytest.mark.asyncio
    async def test_wait_for_duration_mock(self, mock_adb):
        """Test wait duration is short in mock mode."""
        controller = SpotifyController(mock_adb)
        start = datetime.now()
        duration = await controller.wait_for_duration("localhost:5555", 30)
        elapsed = (datetime.now() - start).total_seconds()
        # Should complete very quickly in mock mode
        assert elapsed < 1.0
        assert duration >= 30

    @pytest.mark.asyncio
    async def test_stop_playback_mock(self, mock_adb):
        """Test stopping playback in mock mode."""
        controller = SpotifyController(mock_adb)
        result = await controller.stop_playback("localhost:5555")
        assert result is True

    @pytest.mark.asyncio
    async def test_play_track_premium_real_mode_failure(self):
        """Test play_track_premium returns False when ADB command fails in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            # Create a mock ADB that simulates real mode but fails
            adb = MagicMock(spec=ADBService)
            adb.send_shell_command = AsyncMock(return_value=(1, "", "Error: Activity not found"))

            controller = SpotifyController(adb)
            result = await controller.play_track_premium("localhost:5555", "spotify:track:12345")

            # Should return False on failure, not True
            assert result is False
            adb.send_shell_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_play_track_premium_real_mode_success(self):
        """Test play_track_premium succeeds when ADB command works in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.send_shell_command = AsyncMock(return_value=(0, "Starting: Intent...", ""))

            controller = SpotifyController(adb)
            result = await controller.play_track_premium("localhost:5555", "spotify:track:12345")

            assert result is True
            # Verify the correct deep-link command was sent
            call_args = adb.send_shell_command.call_args
            assert "spotify:track:12345" in call_args[0][1]
            assert "am start" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_verify_playing_real_mode_no_app_running(self):
        """Test verify_playing returns failure when app is not running in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.is_app_running = AsyncMock(return_value=False)

            controller = SpotifyController(adb)
            result = await controller.verify_playing("localhost:5555", "Test Song")

            assert result["is_playing"] is False
            assert result["track_name"] is None
            assert result["progress_sec"] == 0

    @pytest.mark.asyncio
    async def test_verify_playing_real_mode_empty_xml(self):
        """Test verify_playing returns failure when XML dump is empty in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.is_app_running = AsyncMock(return_value=True)
            adb.get_screen_xml = AsyncMock(return_value="")

            controller = SpotifyController(adb)
            result = await controller.verify_playing("localhost:5555", "Test Song")

            assert result["is_playing"] is False
            assert result["track_name"] is None

    @pytest.mark.asyncio
    async def test_verify_playing_real_mode_playback_detected(self):
        """Test verify_playing detects playback from XML in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.is_app_running = AsyncMock(return_value=True)
            # XML with playback indicators
            adb.get_screen_xml = AsyncMock(return_value='''
            <hierarchy rotation="0">
                <node text="Now Playing" class="android.widget.TextView" />
                <node text="Test Song Title" class="android.widget.TextView" />
                <node text="pause" content-desc="Pause" class="android.widget.ImageView" />
            </hierarchy>
            ''')

            controller = SpotifyController(adb)
            result = await controller.verify_playing("localhost:5555", "Test Song Title")

            assert result["is_playing"] is True
            assert result["track_name"] is not None

    @pytest.mark.asyncio
    async def test_search_and_play_real_mode_failure(self):
        """Test search_and_play returns False when input fails in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.launch_app = AsyncMock(return_value=True)
            adb.tap = AsyncMock(return_value=True)
            adb.input_text = AsyncMock(return_value=False)  # Input fails
            adb.send_keyevent = AsyncMock(return_value=True)

            controller = SpotifyController(adb)
            result = await controller.search_and_play("localhost:5555", "Test Artist")

            assert result is False

    @pytest.mark.asyncio
    async def test_search_and_play_real_mode_result_tap_fails(self):
        """Test search_and_play returns False when result tap fails in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.launch_app = AsyncMock(return_value=True)
            adb.tap = AsyncMock(side_effect=[True, True, False])  # search tap, input tap, result tap fails
            adb.input_text = AsyncMock(return_value=True)
            adb.send_keyevent = AsyncMock(return_value=True)

            controller = SpotifyController(adb)
            result = await controller.search_and_play("localhost:5555", "Test Artist")

            assert result is False

    @pytest.mark.asyncio
    async def test_play_track_free_real_mode_search_fails(self):
        """Test play_track_free returns failure when search_and_play fails in real mode."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.launch_app = AsyncMock(return_value=True)
            adb.tap = AsyncMock(return_value=False)  # Search tap fails immediately
            adb.input_text = AsyncMock(return_value=False)
            adb.send_keyevent = AsyncMock(return_value=True)
            adb.get_screen_xml = AsyncMock(return_value="")
            adb.is_app_running = AsyncMock(return_value=True)

            controller = SpotifyController(adb)
            result = await controller.play_track_free(
                "localhost:5555",
                "spotify:track:12345",
                "Test Artist"
            )

            # Should fail because search_and_play couldn't complete
            assert result["played"] is False
            assert result["track_matched"] is False

    @pytest.mark.asyncio
    async def test_play_track_free_real_mode_verification_fails(self):
        """Test play_track_free returns failure when playback verification fails."""
        with patch("app.services.automation.spotify_controller.settings") as mock_settings:
            mock_settings.MOCK_ADB = False
            adb = MagicMock(spec=ADBService)
            adb.launch_app = AsyncMock(return_value=True)
            adb.tap = AsyncMock(return_value=True)
            adb.input_text = AsyncMock(return_value=True)
            adb.send_keyevent = AsyncMock(return_value=True)
            # XML shows no playback indicators
            adb.get_screen_xml = AsyncMock(return_value='<hierarchy><node text="Spotify" /></hierarchy>')
            adb.is_app_running = AsyncMock(return_value=True)

            controller = SpotifyController(adb)
            result = await controller.play_track_free(
                "localhost:5555",
                "spotify:track:12345",
                "Test Artist"
            )

            # Search succeeds but playback verification should fail
            # (no pause/playing indicator in XML)
            assert result["played"] is False  # Because verify_playing returns is_playing=False


class TestHumanizer:
    """Tests for Humanizer."""

    @pytest.mark.asyncio
    async def test_random_delay_gaussian(self):
        """Test random delay uses gaussian distribution."""
        humanizer = Humanizer(level="low")
        humanizer.set_mock_mode(False)  # Test real timing

        delays = []
        for _ in range(10):
            start = datetime.now()
            await humanizer.random_delay(100, 200)  # 100-200ms
            elapsed = (datetime.now() - start).total_seconds() * 1000
            delays.append(elapsed)

        # All delays should be within range (with some tolerance)
        for d in delays:
            assert 80 <= d <= 250  # Allow 20% tolerance

    @pytest.mark.asyncio
    async def test_random_action_probabilities(self, mock_adb):
        """Test random action respects probability distribution."""
        humanizer = Humanizer(level="medium")
        humanizer.set_mock_mode(False)

        actions = []
        for _ in range(100):
            action = await humanizer.random_action(mock_adb, "localhost:5555")
            actions.append(action)

        # Most should be "nothing" (~70%)
        nothing_count = actions.count("nothing")
        assert nothing_count > 50  # At least 50%

    def test_build_session_plan(self):
        """Test session plan building."""
        humanizer = Humanizer(level="medium")
        songs = [
            Song(
                id=uuid.uuid4(),
                spotify_uri="spotify:track:target1",
                title="Target 1",
                artist="Artist",
                total_target_streams=100,
                daily_rate=10,
                priority=SongPriority.HIGH,
                status=SongStatus.ACTIVE
            )
        ]

        plan = humanizer.build_session_plan(songs, AccountType.PREMIUM)

        assert "tracks" in plan
        assert "total_minutes" in plan
        assert len(plan["tracks"]) > 0

        # Should have filler tracks + target
        target_tracks = [t for t in plan["tracks"] if t["is_target"]]
        filler_tracks = [t for t in plan["tracks"] if not t["is_target"]]
        assert len(target_tracks) == 1
        assert len(filler_tracks) >= 2

    @pytest.mark.asyncio
    async def test_pre_stream_delay_levels(self):
        """Test pre-stream delays by level."""
        for level, expected_range in [
            ("low", (0.05, 0.15)),  # 1-2 min in mock mode
            ("medium", (0.1, 0.2)),
            ("high", (0.1, 0.3))
        ]:
            humanizer = Humanizer(level=level)
            humanizer.set_mock_mode(True)

            start = datetime.now()
            await humanizer.pre_stream_delay()
            elapsed = (datetime.now() - start).total_seconds()

            # In mock mode, should be very short
            assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_typed_config_disabled_skips_runtime_behavior(self, mock_adb):
        """Disabled typed humanization config should skip delays and actions."""
        humanizer = Humanizer(HumanizationConfig(enabled=False, preset="medium", level="medium"))
        humanizer.set_mock_mode(False)

        assert humanizer.get_action_count() == 0

        start = datetime.now()
        await humanizer.pre_stream_delay()
        elapsed = (datetime.now() - start).total_seconds()

        assert elapsed < 0.05
        assert await humanizer.random_action(mock_adb, "localhost:5555") == "nothing"


class TestStreamWorker:
    """Tests for StreamWorker."""

    @pytest.mark.asyncio
    async def test_execute_stream_premium(
        self, mock_adb, sample_instance, sample_account, sample_song
    ):
        """Test executing a stream for premium account."""
        sample_instance.assigned_account = sample_account
        sample_account.type = AccountType.PREMIUM

        humanizer = Humanizer(level="low")
        humanizer.set_mock_mode(True)

        spotify = SpotifyController(mock_adb)
        spotify.detect_challenge = AsyncMock(return_value=None)
        worker = StreamWorker(mock_adb, spotify)

        # Create a mock DB session
        mock_db = AsyncMock()

        stream_log = await worker.execute_stream(
            sample_instance, sample_account, sample_song, humanizer, mock_db
        )

        assert stream_log is not None
        assert stream_log.result == StreamResult.SUCCESS
        assert stream_log.account_id == sample_account.id
        assert stream_log.song_id == sample_song.id
        assert stream_log.instance_id == sample_instance.id

    @pytest.mark.asyncio
    async def test_execute_stream_free_shuffle_miss(
        self, mock_adb, sample_instance, sample_account, sample_song
    ):
        """Test handling shuffle miss for free account."""
        sample_instance.assigned_account = sample_account
        sample_account.type = AccountType.FREE

        # Mock spotify controller to simulate shuffle miss
        spotify = MagicMock(spec=SpotifyController)
        spotify.mock_mode = True
        spotify.launch_spotify = AsyncMock(return_value=True)
        spotify.detect_challenge = AsyncMock(return_value=None)
        spotify.stop_playback = AsyncMock(return_value=True)
        # First two attempts fail (shuffle miss), third succeeds
        spotify.play_track_free = AsyncMock(side_effect=[
            {"played": True, "track_matched": False, "actual_track": "Wrong Track"},
            {"played": True, "track_matched": False, "actual_track": "Wrong Track 2"},
            {"played": True, "track_matched": True, "actual_track": None}
        ])
        spotify.verify_playing = AsyncMock(return_value={
            "is_playing": True,
            "track_name": sample_song.title,
            "progress_sec": 60
        })
        spotify.wait_for_duration = AsyncMock(return_value=45)

        humanizer = Humanizer(level="low")
        humanizer.set_mock_mode(True)

        worker = StreamWorker(mock_adb, spotify)
        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        stream_log = await worker.execute_stream(
            sample_instance, sample_account, sample_song, humanizer, mock_db
        )

        # With max_retries=3, after 2 shuffle misses and 1 success
        assert stream_log is not None
        assert stream_log.verified is True

    @pytest.mark.asyncio
    async def test_execute_stream_uses_humanizer_action_count(
        self, mock_adb, sample_instance, sample_account, sample_song
    ):
        """StreamWorker should use the humanizer-provided action count."""
        sample_instance.assigned_account = sample_account
        sample_account.type = AccountType.PREMIUM

        spotify = MagicMock(spec=SpotifyController)
        spotify.mock_mode = True
        spotify.launch_spotify = AsyncMock(return_value=True)
        spotify.detect_challenge = AsyncMock(return_value=None)
        spotify.play_track_premium = AsyncMock(return_value=True)
        spotify.verify_playing = AsyncMock(return_value={
            "is_playing": True,
            "track_name": sample_song.title,
            "progress_sec": 60,
        })
        spotify.wait_for_duration = AsyncMock(return_value=45)
        spotify.stop_playback = AsyncMock(return_value=True)

        humanizer = MagicMock()
        humanizer.pre_stream_delay = AsyncMock(return_value=None)
        humanizer.get_action_count = MagicMock(return_value=2)
        humanizer.random_action = AsyncMock(return_value="nothing")

        worker = StreamWorker(mock_adb, spotify)
        worker.mock_mode = True
        mock_db = AsyncMock()

        stream_log = await worker.execute_stream(
            sample_instance, sample_account, sample_song, humanizer, mock_db
        )

        assert stream_log.result == StreamResult.SUCCESS
        assert humanizer.random_action.await_count == 2


class TestAccountRotator:
    """Tests for AccountRotator."""

    @pytest.mark.asyncio
    async def test_should_rotate_stream_limit(self, sample_instance, sample_account):
        """Test rotation detection when stream limit reached."""
        rotator = AccountRotator()

        mock_db = AsyncMock()

        # Mock settings
        with patch.object(rotator, '_get_setting', new=AsyncMock()) as mock_setting:
            mock_setting.side_effect = lambda db, key, default: {
                "rotation_interval_streams": 10,
                "rotation_interval_hours": 4
            }.get(key, default)

            # Account has reached stream limit
            sample_account.streams_today = 10

            result = await rotator.should_rotate(sample_instance, sample_account, mock_db)
            assert result is True

    @pytest.mark.asyncio
    async def test_should_rotate_time_limit(self, sample_instance, sample_account):
        """Test rotation detection when time limit reached."""
        rotator = AccountRotator()
        mock_db = AsyncMock()

        with patch.object(rotator, '_get_setting', new=AsyncMock()) as mock_setting:
            mock_setting.side_effect = lambda db, key, default: {
                "rotation_interval_streams": 40,
                "rotation_interval_hours": 4
            }.get(key, default)

            # Account was used 5 hours ago
            sample_account.streams_today = 5
            sample_account.last_used = datetime.now(timezone.utc) - timedelta(hours=5)

            result = await rotator.should_rotate(sample_instance, sample_account, mock_db)
            assert result is True

    @pytest.mark.asyncio
    async def test_should_not_rotate(self, sample_instance, sample_account):
        """Test rotation not needed."""
        rotator = AccountRotator()
        mock_db = AsyncMock()

        with patch.object(rotator, '_get_setting', new=AsyncMock()) as mock_setting:
            mock_setting.side_effect = lambda db, key, default: {
                "rotation_interval_streams": 40,
                "rotation_interval_hours": 4
            }.get(key, default)

            sample_account.streams_today = 5
            sample_account.last_used = datetime.now(timezone.utc) - timedelta(hours=2)

            result = await rotator.should_rotate(sample_instance, sample_account, mock_db)
            assert result is False


class TestSongScheduler:
    """Tests for SongScheduler."""

    def test_scheduler_initialization(self):
        """Test scheduler initialization."""
        mock_session_maker = MagicMock()
        mock_ws = MagicMock()

        scheduler = SongScheduler(mock_session_maker, mock_ws)

        assert scheduler.stats["scheduler_state"] == "stopped"
        assert len(scheduler.active_tasks) == 0

    @pytest.mark.asyncio
    async def test_get_status(self, db_session):
        """Test status retrieval."""
        from tests.conftest import TestingSessionLocal

        scheduler = SongScheduler(TestingSessionLocal, MagicMock())
        scheduler.stats["scheduler_state"] = "running"
        scheduler.stats["total_streams_completed"] = 10

        status = await scheduler.get_status()

        assert status["state"] == "running"
        assert status["total_streams_completed"] == 10
        assert status["active_tasks"] == 0
        assert "warmup_sessions_today" in status

    def test_pause_resume(self):
        """Test pause and resume functionality."""
        mock_session_maker = MagicMock()
        mock_ws = MagicMock()

        scheduler = SongScheduler(mock_session_maker, mock_ws)
        # Don't call scheduler.start() — it requires a running event loop.
        # Manually set state to simulate start.
        scheduler.stats["scheduler_state"] = "running"

        assert scheduler.stats["scheduler_state"] == "running"

        scheduler.pause()
        assert scheduler.stats["scheduler_state"] == "paused"

        scheduler.resume()
        assert scheduler.stats["scheduler_state"] == "running"


class TestHealthMonitor:
    """Tests for HealthMonitor."""

    def test_health_monitor_initialization(self):
        """Test health monitor initialization."""
        mock_session_maker = MagicMock()
        mock_ws = MagicMock()

        monitor = HealthMonitor(mock_session_maker, mock_ws)

        assert monitor.mock_mode is True  # From settings

    def test_get_status(self):
        """Test health monitor status."""
        mock_session_maker = MagicMock()
        mock_ws = MagicMock()

        monitor = HealthMonitor(mock_session_maker, mock_ws)
        status = monitor.get_status()

        assert "running" in status
        assert "mock_mode" in status
        assert status["failure_threshold"] == 3

    @pytest.mark.asyncio
    async def test_mock_mode_health_check(self):
        """Test that mock mode health check completes quickly."""
        mock_session_maker = MagicMock()
        mock_ws = MagicMock()

        monitor = HealthMonitor(mock_session_maker, mock_ws)
        monitor.mock_mode = True

        # Should complete without error in mock mode
        start = datetime.now()
        await monitor._health_check_tick()
        elapsed = (datetime.now() - start).total_seconds()

        # Should be very fast in mock mode
        assert elapsed < 0.1


@pytest.mark.asyncio
async def test_integration_stream_flow(mock_adb, sample_instance, sample_account, sample_song):
    """Integration test for full stream flow."""
    sample_instance.assigned_account = sample_account
    sample_instance.adb_port = 5555
    sample_account.type = AccountType.PREMIUM

    # Create all components
    spotify = SpotifyController(mock_adb)
    spotify.detect_challenge = AsyncMock(return_value=None)
    humanizer = Humanizer(level="low")
    humanizer.set_mock_mode(True)
    worker = StreamWorker(mock_adb, spotify)

    # Execute stream
    mock_db = AsyncMock()
    stream_log = await worker.execute_stream(
        sample_instance, sample_account, sample_song, humanizer, mock_db
    )

    # Verify the stream completed successfully
    assert stream_log is not None
    assert stream_log.result == StreamResult.SUCCESS
    assert stream_log.verified is True
    assert stream_log.duration_sec > 0
    assert stream_log.failure_reason is None

    # In mock mode, ADB calls are skipped — no direct adb calls expected


class TestStreamWorkerChallengeHandling:
    """Tests for StreamWorker challenge detection and handling."""

    @pytest.mark.asyncio
    async def test_challenge_detection_fails_stream(
        self, mock_adb, sample_instance, sample_account, sample_song
    ):
        """When a challenge is detected, the stream should fail with challenge reason."""
        sample_instance.assigned_account = sample_account
        sample_account.type = AccountType.PREMIUM

        spotify = MagicMock(spec=SpotifyController)
        spotify.mock_mode = True
        spotify.launch_spotify = AsyncMock(return_value=True)
        # Return a challenge on the first detect call
        spotify.detect_challenge = AsyncMock(return_value={"type": "captcha"})
        spotify.stop_playback = AsyncMock(return_value=True)

        humanizer = Humanizer(level="low")
        humanizer.set_mock_mode(True)

        worker = StreamWorker(mock_adb, spotify)

        # Use a mock DB that supports add/flush
        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        stream_log = await worker.execute_stream(
            sample_instance, sample_account, sample_song, humanizer, mock_db
        )

        assert stream_log is not None
        assert stream_log.result == StreamResult.FAIL
        assert "Challenge detected" in stream_log.failure_reason
        assert "captcha" in stream_log.failure_reason

    @pytest.mark.asyncio
    async def test_post_playback_challenge_checkpoint(
        self, mock_adb, sample_instance, sample_account, sample_song
    ):
        """Challenge detected after playback starts should also fail the stream."""
        sample_instance.assigned_account = sample_account
        sample_account.type = AccountType.PREMIUM

        spotify = MagicMock(spec=SpotifyController)
        spotify.mock_mode = True
        spotify.launch_spotify = AsyncMock(return_value=True)
        # First detect returns None (pre-playback), second returns challenge (post-playback)
        spotify.detect_challenge = AsyncMock(
            side_effect=[None, {"type": "email_verify"}]
        )
        spotify.play_track_premium = AsyncMock(return_value=True)
        spotify.stop_playback = AsyncMock(return_value=True)

        humanizer = Humanizer(level="low")
        humanizer.set_mock_mode(True)

        worker = StreamWorker(mock_adb, spotify)
        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        stream_log = await worker.execute_stream(
            sample_instance, sample_account, sample_song, humanizer, mock_db
        )

        assert stream_log.result == StreamResult.FAIL
        assert "Challenge detected" in stream_log.failure_reason
        assert "email_verify" in stream_log.failure_reason


class TestSchedulerChallengeExclusion:
    """Tests for scheduler excluding accounts/instances with pending challenges."""

    @pytest.mark.asyncio
    async def test_get_available_instances_excludes_pending(self, db_session):
        """_get_available_instances should exclude instance/account with pending challenge."""
        from tests.conftest import TestingSessionLocal
        from app.models.challenge import Challenge, ChallengeType, ChallengeStatus

        async with TestingSessionLocal() as session:
            # Create proxy for account
            from app.models.proxy import Proxy, ProxyStatus
            proxy = Proxy(
                id=uuid.uuid4(),
                host="10.0.0.1",
                port=1080,
                protocol="socks5",
                status=ProxyStatus.HEALTHY,
            )
            session.add(proxy)

            account = Account(
                id=uuid.uuid4(),
                email="scheduler-test@example.com",
                type=AccountType.PREMIUM,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
                proxy_id=proxy.id,
            )
            session.add(account)
            await session.flush()

            instance = Instance(
                id=uuid.uuid4(),
                name="sched-instance-01",
                status=InstanceStatus.RUNNING,
                adb_port=5555,
                ram_limit_mb=2048,
                cpu_cores=2.0,
                assigned_account_id=account.id,
            )
            session.add(instance)
            await session.flush()

            # Add a pending challenge
            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=account.id,
                instance_id=instance.id,
                type=ChallengeType.CAPTCHA,
                status=ChallengeStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add(challenge)
            await session.commit()

            # Test scheduler excludes it
            scheduler = SongScheduler(TestingSessionLocal, MagicMock())
            result = await scheduler._get_available_instances(session, 40)
            instance_ids = [inst.id for inst, _ in result]
            assert instance.id not in instance_ids

    @pytest.mark.asyncio
    async def test_get_available_instances_includes_non_pending(self, db_session):
        """_get_available_instances should include instance/account when challenge is resolved."""
        from tests.conftest import TestingSessionLocal
        from app.models.challenge import Challenge, ChallengeType, ChallengeStatus

        async with TestingSessionLocal() as session:
            from app.models.proxy import Proxy, ProxyStatus
            proxy = Proxy(
                id=uuid.uuid4(),
                host="10.0.0.2",
                port=1081,
                protocol="socks5",
                status=ProxyStatus.HEALTHY,
            )
            session.add(proxy)

            account = Account(
                id=uuid.uuid4(),
                email="scheduler-ok@example.com",
                type=AccountType.PREMIUM,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
                proxy_id=proxy.id,
            )
            session.add(account)
            await session.flush()

            instance = Instance(
                id=uuid.uuid4(),
                name="sched-instance-02",
                status=InstanceStatus.RUNNING,
                adb_port=5556,
                ram_limit_mb=2048,
                cpu_cores=2.0,
                assigned_account_id=account.id,
            )
            session.add(instance)
            await session.flush()

            # Add a RESOLVED challenge (should NOT block)
            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=account.id,
                instance_id=instance.id,
                type=ChallengeType.CAPTCHA,
                status=ChallengeStatus.RESOLVED,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                resolved_at=datetime.now(timezone.utc),
            )
            session.add(challenge)
            await session.commit()

            scheduler = SongScheduler(TestingSessionLocal, MagicMock())
            result = await scheduler._get_available_instances(session, 40)
            instance_ids = [inst.id for inst, _ in result]
            assert instance.id in instance_ids


class TestAccountRotatorChallengeExclusion:
    """Tests for account rotator excluding challenged accounts."""

    @pytest.mark.asyncio
    async def test_select_next_account_excludes_challenged(self, db_session):
        """_select_next_account should not return accounts with pending challenges."""
        from tests.conftest import TestingSessionLocal
        from app.models.challenge import Challenge, ChallengeType, ChallengeStatus

        async with TestingSessionLocal() as session:
            from app.models.proxy import Proxy, ProxyStatus

            # Account 1: has pending challenge
            proxy1 = Proxy(
                id=uuid.uuid4(), host="10.0.0.3", port=1082,
                protocol="socks5", status=ProxyStatus.HEALTHY,
            )
            session.add(proxy1)
            acct_challenged = Account(
                id=uuid.uuid4(),
                email="challenged@example.com",
                type=AccountType.PREMIUM,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
                proxy_id=proxy1.id,
            )
            session.add(acct_challenged)

            # Account 2: no challenge
            proxy2 = Proxy(
                id=uuid.uuid4(), host="10.0.0.4", port=1083,
                protocol="socks5", status=ProxyStatus.HEALTHY,
            )
            session.add(proxy2)
            acct_clean = Account(
                id=uuid.uuid4(),
                email="clean@example.com",
                type=AccountType.PREMIUM,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
                proxy_id=proxy2.id,
            )
            session.add(acct_clean)
            await session.flush()

            # Pending challenge for account 1
            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=acct_challenged.id,
                type=ChallengeType.CAPTCHA,
                status=ChallengeStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add(challenge)
            await session.commit()

            rotator = AccountRotator()
            selected = await rotator._select_next_account(session)

            # Should NOT return the challenged account
            assert selected is not None
            assert selected.id != acct_challenged.id
            assert selected.id == acct_clean.id


class TestWarmupChallengeHandling:
    """Tests for warmup path challenge detection."""

    @pytest.mark.asyncio
    async def test_warmup_does_not_progress_on_challenge(
        self, mock_adb, sample_instance, sample_account
    ):
        """If warmup detects a challenge, warmup_day must not increment."""
        from app.services.antidetect.warmup import WarmupManager

        sample_account.status = AccountStatus.WARMING
        sample_account.warmup_day = 1
        original_day = sample_account.warmup_day

        warmup = WarmupManager(ws_manager=None)
        warmup.mock_mode = True

        # Mock the SpotifyController to detect a challenge
        with patch(
            "app.services.antidetect.warmup.SpotifyController"
        ) as MockSpotify:
            mock_spotify_instance = MagicMock()
            mock_spotify_instance.launch_spotify = AsyncMock(return_value=True)
            mock_spotify_instance.detect_challenge = AsyncMock(
                return_value={"type": "captcha"}
            )
            MockSpotify.return_value = mock_spotify_instance

            # Mock the challenge service to avoid DB commit issues
            with patch(
                "app.services.challenge_service.handle_detected_challenge",
                new=AsyncMock(),
            ):
                mock_db = MagicMock(spec=["execute", "add", "flush", "commit"])
                # _get_warmup_duration does: result = await db.execute(...); setting = result.scalar_one_or_none()
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None  # No setting -> default 5
                mock_db.execute = AsyncMock(return_value=mock_result)

                result = await warmup.execute_warmup_day(
                    sample_instance, sample_account, mock_db
                )

                # Warmup should return False (challenge detected)
                assert result is False
                # warmup_day should NOT have incremented
                assert sample_account.warmup_day == original_day

