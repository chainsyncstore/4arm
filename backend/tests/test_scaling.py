"""Tests for Phase 7: Scaling & Monitoring."""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.services.song_estimator import SongEstimator
from app.services.alerting import AlertingService, AlertSeverity, AlertChannel
from app.services.cluster.machine_registry import MachineRegistry
from app.services.cluster.load_balancer import LoadBalancer
from app.models.song import Song, SongStatus
from app.models.alert import Alert
from app.models.machine import Machine, MachineStatus
from app.models.instance import Instance, InstanceStatus
from app.models.account import Account, AccountStatus
from app.models.stream_log import StreamLog, StreamResult


@pytest.fixture
def song_estimator():
    """Create a SongEstimator instance."""
    return SongEstimator(db_session_maker=None)


@pytest.fixture
def alerting_service():
    """Create an AlertingService instance."""
    return AlertingService(db_session_maker=None, ws_manager=None)


@pytest.fixture
def machine_registry():
    """Create a MachineRegistry instance."""
    return MachineRegistry(db_session_maker=None)


@pytest.fixture
def load_balancer():
    """Create a LoadBalancer instance."""
    return LoadBalancer(machine_registry=None)


class TestSongEstimator:
    """Tests for SongEstimator service."""

    @pytest.mark.asyncio
    async def test_estimate_eta_returns_expected_fields(self, db_session, song_estimator):
        """estimate_eta() returns expected fields."""
        # Create a song
        song = Song(
            spotify_uri="spotify:track:test123",
            title="Test Song",
            total_target_streams=100,
            daily_rate=10,
            status=SongStatus.ACTIVE,
            completed_streams=50
        )
        db_session.add(song)
        await db_session.commit()
        await db_session.refresh(song)

        # Create an instance to have active instances
        instance = Instance(
            name="test-instance",
            status=InstanceStatus.RUNNING,
            docker_id="mock-123"
        )
        db_session.add(instance)
        await db_session.commit()

        eta = await song_estimator.estimate_eta(song.id, db_session)

        assert "song_id" in eta
        assert "remaining_streams" in eta
        assert "daily_capacity" in eta
        assert "estimated_days" in eta
        assert "estimated_completion" in eta
        assert "confidence" in eta
        assert "bottleneck" in eta

        assert eta["song_id"] == str(song.id)
        assert eta["remaining_streams"] == 50
        assert eta["confidence"] in ["high", "medium", "low"]
        assert eta["bottleneck"] in ["daily_rate_cap", "instance_capacity", "account_limit", "none"]

    @pytest.mark.asyncio
    async def test_estimate_eta_returns_low_confidence_with_limited_data(self, db_session, song_estimator):
        """Returns 'low' confidence when <24h of data."""
        song = Song(
            spotify_uri="spotify:track:test456",
            title="Low Confidence Song",
            total_target_streams=100,
            daily_rate=10,
            status=SongStatus.ACTIVE,
            completed_streams=0
        )
        db_session.add(song)

        instance = Instance(
            name="test-instance-2",
            status=InstanceStatus.RUNNING,
            docker_id="mock-456"
        )
        db_session.add(instance)
        await db_session.commit()

        # No stream logs = no data = low confidence
        eta = await song_estimator.estimate_eta(song.id, db_session)
        assert eta["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_estimate_eta_identifies_bottleneck_daily_rate_cap(self, db_session, song_estimator):
        """Correctly identifies bottleneck as daily_rate_cap."""
        song = Song(
            spotify_uri="spotify:track:test789",
            title="Rate Limited Song",
            total_target_streams=1000,
            daily_rate=5,  # Low daily rate
            status=SongStatus.ACTIVE,
            completed_streams=0
        )
        db_session.add(song)

        # Add stream logs for high throughput
        for i in range(5):
            log = StreamLog(
                spotify_uri="spotify:track:test",
                started_at=datetime.now(timezone.utc) - timedelta(hours=i),
                result=StreamResult.SUCCESS,
                duration_sec=60
            )
            db_session.add(log)

        instance = Instance(
            name="test-instance-3",
            status=InstanceStatus.RUNNING,
            docker_id="mock-789"
        )
        db_session.add(instance)
        await db_session.commit()

        eta = await song_estimator.estimate_eta(song.id, db_session)
        # With capacity > daily_rate, bottleneck should be daily_rate_cap
        assert eta["bottleneck"] == "daily_rate_cap"

    @pytest.mark.asyncio
    async def test_estimate_all_returns_batch_eta(self, db_session, song_estimator):
        """estimate_all() returns batch ETA for all active songs."""
        song1 = Song(
            spotify_uri="spotify:track:batch1",
            title="Batch Song 1",
            total_target_streams=100,
            daily_rate=10,
            status=SongStatus.ACTIVE
        )
        song2 = Song(
            spotify_uri="spotify:track:batch2",
            title="Batch Song 2",
            total_target_streams=200,
            daily_rate=20,
            status=SongStatus.ACTIVE
        )
        db_session.add(song1)
        db_session.add(song2)

        instance = Instance(
            name="test-instance-4",
            status=InstanceStatus.RUNNING,
            docker_id="mock-batch"
        )
        db_session.add(instance)
        await db_session.commit()

        eta_list = await song_estimator.estimate_all(db_session)

        assert len(eta_list) == 2
        for eta in eta_list:
            assert "song_id" in eta
            assert "remaining_streams" in eta


class TestAlertingService:
    """Tests for AlertingService."""

    @pytest.mark.asyncio
    async def test_send_alert_stores_in_db(self, db_session, alerting_service):
        """send_alert() stores alert in DB."""
        # Manually inject db_session into the service for testing
        alerting_service.db_session_maker = lambda: db_session

        await alerting_service.send_alert(
            severity=AlertSeverity.INFO,
            title="Test Alert",
            message="This is a test alert",
            db=db_session
        )

        # Query the alert
        result = await db_session.execute(
            select(Alert).where(Alert.title == "Test Alert")
        )
        alert = result.scalar_one_or_none()

        assert alert is not None
        assert alert.severity == AlertSeverity.INFO
        assert alert.message == "This is a test alert"
        assert alert.acknowledged is False

    @pytest.mark.asyncio
    async def test_send_alert_respects_cooldown(self, db_session, alerting_service):
        """send_alert() respects cooldown window (dedup)."""
        await alerting_service.send_alert(
            severity=AlertSeverity.WARNING,
            title="Cooldown Test",
            message="First alert",
            db=db_session
        )

        # Second alert with same title should be skipped due to cooldown
        await alerting_service.send_alert(
            severity=AlertSeverity.WARNING,
            title="Cooldown Test",
            message="Second alert (should be deduped)",
            db=db_session
        )

        # Query all alerts with this title
        result = await db_session.execute(
            select(Alert).where(Alert.title == "Cooldown Test")
        )
        alerts = result.scalars().all()

        # Should only have one alert due to cooldown
        assert len(alerts) == 1
        assert alerts[0].message == "First alert"

    @pytest.mark.asyncio
    async def test_daily_digest_returns_formatted_string(self, db_session, alerting_service):
        """daily_digest() returns formatted string with all sections."""
        # Create some test data
        song = Song(
            spotify_uri="spotify:track:digest1",
            title="Digest Test Song",
            total_target_streams=100,
            daily_rate=10,
            streams_today=5,
            status=SongStatus.ACTIVE
        )
        db_session.add(song)

        account = Account(
            email="digest@test.com",
            status=AccountStatus.ACTIVE,
            streams_today=3
        )
        db_session.add(account)

        instance = Instance(
            name="digest-instance",
            status=InstanceStatus.RUNNING,
            docker_id="mock-digest"
        )
        db_session.add(instance)

        # Add stream logs
        for i in range(3):
            log = StreamLog(
                spotify_uri="spotify:track:digest",
                started_at=datetime.now(timezone.utc) - timedelta(hours=i),
                result=StreamResult.SUCCESS,
                duration_sec=60
            )
            db_session.add(log)

        await db_session.commit()

        digest = await alerting_service.daily_digest(db_session)

        # Check for expected sections in digest
        assert "Daily Digest" in digest
        assert "Streaming Activity" in digest
        assert "Resources" in digest
        assert "Songs" in digest
        assert "Infrastructure" in digest

    @pytest.mark.asyncio
    async def test_telegram_not_called_when_token_empty(self, db_session, alerting_service):
        """Telegram not called when token is empty."""
        # Ensure no telegram config
        alerting_service.telegram_token = ""
        alerting_service.telegram_chat_id = ""

        # Should not raise, just skip telegram
        await alerting_service.send_alert(
            severity=AlertSeverity.INFO,
            title="No Telegram Test",
            message="This should not send to Telegram",
            db=db_session
        )

        # Alert should still be in DB
        result = await db_session.execute(
            select(Alert).where(Alert.title == "No Telegram Test")
        )
        alert = result.scalar_one_or_none()
        assert alert is not None


class TestMachineRegistry:
    """Tests for MachineRegistry."""

    @pytest.mark.asyncio
    async def test_register_machine_creates_db_record(self, db_session):
        """register_machine() creates DB record."""
        registry = MachineRegistry(db_session_maker=None)

        machine = await registry.register_machine(
            hostname="test-machine-01",
            docker_host="tcp://192.168.1.100:2376",
            max_instances=10,
            max_ram_mb=32768,
            db=db_session
        )

        assert machine.id is not None
        assert machine.hostname == "test-machine-01"
        assert machine.status == MachineStatus.ONLINE
        assert machine.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_heartbeat_updates_last_heartbeat(self, db_session):
        """heartbeat() updates last_heartbeat."""
        registry = MachineRegistry(db_session_maker=None)

        # Create machine
        machine = await registry.register_machine(
            hostname="test-machine-02",
            docker_host="tcp://192.168.1.101:2376",
            db=db_session
        )

        original_heartbeat = machine.last_heartbeat.replace(tzinfo=None) if machine.last_heartbeat else None

        # Wait a tiny bit and do heartbeat
        import asyncio
        await asyncio.sleep(0.01)

        reachable = await registry.heartbeat(machine.id, db_session)

        assert reachable is True
        new_heartbeat = machine.last_heartbeat.replace(tzinfo=None) if machine.last_heartbeat.tzinfo else machine.last_heartbeat
        assert new_heartbeat > original_heartbeat

    @pytest.mark.asyncio
    async def test_deregister_machine_sets_draining(self, db_session):
        """deregister_machine() sets status to DRAINING."""
        registry = MachineRegistry(db_session_maker=None)

        machine = await registry.register_machine(
            hostname="test-machine-03",
            docker_host="tcp://192.168.1.102:2376",
            db=db_session
        )

        success = await registry.deregister_machine(machine.id, db_session)

        assert success is True
        assert machine.status == MachineStatus.DRAINING

    @pytest.mark.asyncio
    async def test_get_machine_utilization_returns_stats(self, db_session):
        """get_machine_utilization() returns utilization stats."""
        registry = MachineRegistry(db_session_maker=None)

        machine = await registry.register_machine(
            hostname="test-machine-04",
            docker_host="tcp://192.168.1.103:2376",
            max_instances=10,
            max_ram_mb=32768,
            db=db_session
        )

        # Create an instance
        instance = Instance(
            name="test-on-machine",
            status=InstanceStatus.RUNNING,
            docker_id="mock-on-machine"
        )
        db_session.add(instance)
        await db_session.commit()

        util = await registry.get_machine_utilization(machine.id, db_session)

        assert "instances" in util
        assert "ram_used_mb" in util
        assert "ram_pct" in util
        assert "cpu_pct" in util


class TestLoadBalancer:
    """Tests for LoadBalancer."""

    @pytest.mark.asyncio
    async def test_select_machine_picks_lowest_utilization(self, db_session, load_balancer):
        """select_machine() picks lowest utilization."""
        # Create two machines with different specs
        machine1 = Machine(
            hostname="machine-low-util",
            docker_host="tcp://192.168.1.200:2376",
            max_instances=10,
            max_ram_mb=32768,
            status=MachineStatus.ONLINE
        )
        machine2 = Machine(
            hostname="machine-high-util",
            docker_host="tcp://192.168.1.201:2376",
            max_instances=10,
            max_ram_mb=16384,  # Less RAM = higher utilization
            status=MachineStatus.ONLINE
        )
        db_session.add(machine1)
        db_session.add(machine2)
        await db_session.commit()

        selected = await load_balancer.select_machine(2048, db_session)

        # Should pick machine1 (higher RAM = lower utilization)
        assert selected is not None
        assert selected.id == machine1.id

    @pytest.mark.asyncio
    async def test_select_machine_returns_none_when_all_full(self, db_session, load_balancer):
        """select_machine() returns None when all machines full."""
        # Create a machine with 0 max instances
        machine = Machine(
            hostname="full-machine",
            docker_host="tcp://192.168.1.202:2376",
            max_instances=0,  # Full
            max_ram_mb=32768,
            status=MachineStatus.ONLINE
        )
        db_session.add(machine)
        await db_session.commit()

        selected = await load_balancer.select_machine(2048, db_session)

        assert selected is None

    @pytest.mark.asyncio
    async def test_select_machine_skips_draining(self, db_session, load_balancer):
        """select_machine() skips DRAINING machines."""
        draining_machine = Machine(
            hostname="draining-machine",
            docker_host="tcp://192.168.1.203:2376",
            max_instances=10,
            max_ram_mb=32768,
            status=MachineStatus.DRAINING  # Draining
        )
        db_session.add(draining_machine)
        await db_session.commit()

        selected = await load_balancer.select_machine(2048, db_session)

        # Should skip draining machine and return None (no online machines)
        assert selected is None

    @pytest.mark.asyncio
    async def test_rebalance_report_returns_distribution(self, db_session, load_balancer):
        """rebalance_report() returns instance distribution report."""
        # Create machines
        machine1 = Machine(
            hostname="balance-machine-1",
            docker_host="tcp://192.168.1.204:2376",
            max_instances=10,
            max_ram_mb=32768,
            status=MachineStatus.ONLINE
        )
        machine2 = Machine(
            hostname="balance-machine-2",
            docker_host="tcp://192.168.1.205:2376",
            max_instances=10,
            max_ram_mb=16384,
            status=MachineStatus.ONLINE
        )
        db_session.add(machine1)
        db_session.add(machine2)
        await db_session.commit()

        report = await load_balancer.rebalance_report(db_session)

        assert "total_machines" in report
        assert report["total_machines"] == 2
        assert "machines" in report
        assert len(report["machines"]) == 2
        assert "imbalance_status" in report
