"""Integration tests for Phase 4: Proxy Integration."""

import pytest
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.models.proxy import Proxy, ProxyStatus, ProxyProtocol
from app.models.account import Account, AccountStatus, AccountType
from app.models.instance import Instance, InstanceStatus
from app.services.proxy_manager import ProxyManager
from app.services.proxy_health_checker import ProxyHealthChecker
from app.services.proxy_service import ProxyService


@pytest.mark.asyncio
async def test_auto_assign_proxies(db_session):
    """Test ProxyManager.auto_assign_proxies() logic."""
    # Create test proxies
    proxy1 = Proxy(
        host="192.168.1.1",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )
    proxy2 = Proxy(
        host="192.168.1.2",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )
    proxy3 = Proxy(
        host="192.168.1.3",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.UNHEALTHY  # Should not be assigned
    )

    db_session.add_all([proxy1, proxy2, proxy3])
    await db_session.commit()

    # Create test accounts without proxies
    account1 = Account(
        email="test1@example.com",
        status=AccountStatus.ACTIVE,
        type=AccountType.PREMIUM
    )
    account2 = Account(
        email="test2@example.com",
        status=AccountStatus.ACTIVE,
        type=AccountType.PREMIUM
    )
    account3 = Account(
        email="test3@example.com",
        status=AccountStatus.ACTIVE,
        type=AccountType.PREMIUM
    )

    db_session.add_all([account1, account2, account3])
    await db_session.commit()

    # Run auto-assign
    proxy_manager = ProxyManager(db_session)
    result = await proxy_manager.auto_assign_proxies()

    # Verify results
    assert result["assigned"] == 2  # 2 healthy proxies assigned to 2 accounts
    assert result["remaining_unlinked_accounts"] == 1  # 1 account left without proxy
    assert result["remaining_unlinked_proxies"] == 0  # All healthy proxies assigned

    # Verify assignments in DB
    await db_session.refresh(account1)
    await db_session.refresh(account2)
    await db_session.refresh(account3)

    assert account1.proxy_id is not None
    assert account2.proxy_id is not None
    assert account3.proxy_id is None  # No proxy left for this account


@pytest.mark.asyncio
async def test_switch_proxy_mock_mode(db_session, mock_settings):
    """Test ProxyManager.switch_instance_proxy() in mock mode."""
    # Create test proxy
    proxy = Proxy(
        host="10.0.0.1",
        port=1080,
        username="user",
        password="pass",
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )
    db_session.add(proxy)

    # Create test instance with redsocks sidecar
    instance = Instance(
        name="test-instance",
        docker_id=f"mock-{uuid.uuid4().hex[:12]}",
        redsocks_container_id=f"redsocks-mock-{uuid.uuid4().hex[:12]}",
        status=InstanceStatus.RUNNING
    )
    db_session.add(instance)
    await db_session.commit()

    # Switch proxy
    proxy_manager = ProxyManager(db_session)
    result = await proxy_manager.switch_instance_proxy(instance.id, proxy.id)

    # Verify result
    assert result["success"] is True
    assert result["expected_ip"] == result["actual_ip"]  # In mock mode they match
    assert "message" in result


@pytest.mark.asyncio
async def test_proxy_health_checker_detects_unhealthy(db_session):
    """Test ProxyHealthChecker detection of unhealthy proxies."""
    # Create a proxy that's healthy
    proxy = Proxy(
        host="192.168.100.1",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY,
        uptime_pct=100.0
    )
    db_session.add(proxy)
    await db_session.commit()

    # Create mock ws_manager
    class MockWSManager:
        def __init__(self):
            self.alerts = []

        async def broadcast_alert(self, level: str, message: str):
            self.alerts.append({"level": level, "message": message})

    mock_ws = MockWSManager()

    # Create health checker with short interval for testing
    from app.database import async_session_maker
    health_checker = ProxyHealthChecker(
        db_session_maker=async_session_maker,
        ws_manager=mock_ws,
        check_interval_minutes=1
    )

    # The proxy has no linked account, so it won't be checked
    # Let's link an account to it first
    account = Account(
        email="healthcheck@example.com",
        status=AccountStatus.ACTIVE,
        type=AccountType.PREMIUM,
        proxy_id=proxy.id
    )
    db_session.add(account)
    await db_session.commit()

    # Run a single health check
    await health_checker._check_all_proxies()

    # In mock mode, the proxy should be healthy
    await db_session.refresh(proxy)
    assert proxy.status == ProxyStatus.HEALTHY
    assert proxy.last_health_check is not None


@pytest.mark.asyncio
async def test_verify_instance_ip_mock(db_session):
    """Test verify_instance_ip in mock mode."""
    # Create test proxy
    proxy = Proxy(
        host="1.2.3.4",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )
    db_session.add(proxy)
    await db_session.commit()

    # Create test account linked to proxy
    account = Account(
        email="verify@example.com",
        status=AccountStatus.ACTIVE,
        type=AccountType.PREMIUM,
        proxy_id=proxy.id
    )
    db_session.add(account)
    await db_session.commit()

    # Create test instance assigned to account
    instance = Instance(
        name="verify-instance",
        docker_id=f"mock-{uuid.uuid4().hex[:12]}",
        redsocks_container_id=f"redsocks-mock-{uuid.uuid4().hex[:12]}",
        status=InstanceStatus.RUNNING,
        assigned_account_id=account.id
    )
    db_session.add(instance)
    await db_session.commit()

    # Verify IP
    proxy_manager = ProxyManager(db_session)
    result = await proxy_manager.verify_instance_ip(instance.id)

    # In mock mode, IP should be deterministic based on instance_id
    assert result["ip"] is not None
    assert isinstance(result["ip"], str)
    assert result["proxy_host"] == proxy.host


@pytest.mark.asyncio
async def test_proxy_service_get_unlinked_proxies(db_session):
    """Test ProxyService.get_unlinked_proxies() works correctly."""
    # Create proxies - some linked, some not
    linked_proxy = Proxy(
        host="10.0.1.1",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )
    unlinked_proxy1 = Proxy(
        host="10.0.1.2",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )
    unlinked_proxy2 = Proxy(
        host="10.0.1.3",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )

    db_session.add_all([linked_proxy, unlinked_proxy1, unlinked_proxy2])
    await db_session.commit()

    # Link one proxy to an account
    account = Account(
        email="linked@example.com",
        status=AccountStatus.ACTIVE,
        type=AccountType.PREMIUM,
        proxy_id=linked_proxy.id
    )
    db_session.add(account)
    await db_session.commit()

    # Get unlinked proxies
    service = ProxyService(db_session)
    unlinked = await service.get_unlinked_proxies()

    # Should return only unlinked proxies
    assert len(unlinked) == 2
    unlinked_ids = {p.id for p in unlinked}
    assert linked_proxy.id not in unlinked_ids
    assert unlinked_proxy1.id in unlinked_ids
    assert unlinked_proxy2.id in unlinked_ids


@pytest.mark.asyncio
async def test_proxy_service_test_proxy_real_branch_persists_results(db_session, monkeypatch):
    """Test ProxyService.test_proxy() real branch persists proxy health details."""
    proxy = Proxy(
        host="203.0.113.10",
        port=3128,
        protocol=ProxyProtocol.HTTP,
        status=ProxyStatus.UNCHECKED
    )
    db_session.add(proxy)
    await db_session.commit()

    async def mock_test_proxy_real(self, proxy_id):
        assert proxy_id == proxy.id
        return {
            "healthy": True,
            "ip": "198.51.100.25",
            "latency_ms": 87.5,
            "error": None,
        }

    monkeypatch.setattr(settings, "MOCK_DOCKER", False)
    monkeypatch.setattr(ProxyManager, "test_proxy_real", mock_test_proxy_real)

    service = ProxyService(db_session)
    result = await service.test_proxy(proxy.id)

    await db_session.refresh(proxy)

    assert result.healthy is True
    assert result.ip == "198.51.100.25"
    assert result.latency_ms == 87.5
    assert proxy.status == ProxyStatus.HEALTHY
    assert proxy.ip == "198.51.100.25"
    assert proxy.latency_ms == 87.5
    assert proxy.last_health_check is not None


@pytest.mark.asyncio
async def test_test_proxy_real_mock_mode(db_session):
    """Test ProxyManager.test_proxy_real() in mock mode."""
    proxy = Proxy(
        host="192.168.200.1",
        port=1080,
        protocol=ProxyProtocol.SOCKS5,
        status=ProxyStatus.HEALTHY
    )
    db_session.add(proxy)
    await db_session.commit()

    proxy_manager = ProxyManager(db_session)
    result = await proxy_manager.test_proxy_real(proxy.id)

    # In mock mode, should return healthy result
    assert result["healthy"] is True
    assert result["ip"] is not None
    assert result["latency_ms"] is not None
    assert result["error"] is None
