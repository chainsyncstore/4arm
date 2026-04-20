import pytest
from httpx import AsyncClient
from types import SimpleNamespace
from app.config import settings
from app.services.proxy_manager import ProxyManager


@pytest.mark.asyncio
async def test_create_proxy(client: AsyncClient):
    """Test creating a new proxy."""
    response = await client.post("/api/proxies/", json={
        "host": "192.168.1.200",
        "port": 1080,
        "username": "proxyuser",
        "password": "proxypass",
        "protocol": "socks5",
        "country": "US"
    })

    assert response.status_code == 200
    data = response.json()
    assert data["host"] == "192.168.1.200"
    assert data["port"] == 1080
    assert data["username"] == "proxyuser"
    assert data["protocol"] == "socks5"
    assert data["country"] == "US"
    assert data["status"] == "unchecked"


@pytest.mark.asyncio
async def test_list_proxies(client: AsyncClient, sample_proxy):
    """Test listing proxies."""
    response = await client.get("/api/proxies/")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_proxy(client: AsyncClient, sample_proxy):
    """Test getting a specific proxy."""
    proxy_id = sample_proxy["id"]
    response = await client.get(f"/api/proxies/{proxy_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == proxy_id
    assert data["host"] == sample_proxy["host"]


@pytest.mark.asyncio
async def test_test_proxy(client: AsyncClient, sample_proxy):
    """Test proxy connectivity check (mocked)."""
    proxy_id = sample_proxy["id"]

    response = await client.post(f"/api/proxies/{proxy_id}/test")

    assert response.status_code == 200
    data = response.json()
    assert "healthy" in data
    # Mock returns a random result


@pytest.mark.asyncio
async def test_test_all_proxies(client: AsyncClient, sample_proxy):
    """Test batch testing all proxies."""
    response = await client.post("/api/proxies/test-all")

    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "tested" in data
    assert "healthy" in data


@pytest.mark.asyncio
async def test_manual_mode_test_proxy_persists_result(client: AsyncClient, sample_proxy, monkeypatch):
    """Test manual-mode proxy test route persists real branch results."""
    proxy_id = sample_proxy["id"]

    async def mock_test_proxy_real(self, incoming_proxy_id):
        assert str(incoming_proxy_id) == proxy_id
        return {
            "healthy": True,
            "ip": "198.51.100.12",
            "latency_ms": 64.25,
            "error": None,
        }

    monkeypatch.setattr(settings, "MOCK_DOCKER", False)
    monkeypatch.setattr(ProxyManager, "test_proxy_real", mock_test_proxy_real)

    response = await client.post(f"/api/proxies/{proxy_id}/test")

    assert response.status_code == 200
    assert response.json() == {
        "healthy": True,
        "ip": "198.51.100.12",
        "latency_ms": 64.25,
        "error": None,
    }

    proxy_response = await client.get(f"/api/proxies/{proxy_id}")
    proxy_data = proxy_response.json()
    assert proxy_data["status"] == "healthy"
    assert proxy_data["ip"] == "198.51.100.12"
    assert proxy_data["latency_ms"] == 64.25
    assert proxy_data["last_health_check"] is not None


@pytest.mark.asyncio
async def test_manual_mode_test_all_proxies_returns_meaningful_counts(client: AsyncClient, sample_proxy, monkeypatch):
    """Test manual-mode test-all route aggregates healthy and unhealthy counts."""
    second_proxy_response = await client.post("/api/proxies/", json={
        "host": "192.168.1.101",
        "port": 1081,
        "protocol": "http"
    })
    second_proxy_id = second_proxy_response.json()["id"]

    results = {
        sample_proxy["id"]: {
            "healthy": True,
            "ip": "203.0.113.7",
            "latency_ms": 80.0,
            "error": None,
        },
        second_proxy_id: {
            "healthy": False,
            "ip": None,
            "latency_ms": None,
            "error": "Connection timeout",
        },
    }

    async def mock_test_proxy_real(self, incoming_proxy_id):
        return results[str(incoming_proxy_id)]

    monkeypatch.setattr(settings, "MOCK_DOCKER", False)
    monkeypatch.setattr(ProxyManager, "test_proxy_real", mock_test_proxy_real)

    response = await client.post("/api/proxies/test-all")

    assert response.status_code == 200
    assert response.json() == {
        "total": 2,
        "tested": 2,
        "healthy": 1,
        "unhealthy": 1,
    }

    proxies_response = await client.get("/api/proxies/")
    proxies_by_id = {proxy["id"]: proxy for proxy in proxies_response.json()}
    assert proxies_by_id[sample_proxy["id"]]["status"] == "healthy"
    assert proxies_by_id[sample_proxy["id"]]["ip"] == "203.0.113.7"
    assert proxies_by_id[second_proxy_id]["status"] == "unhealthy"
    assert proxies_by_id[second_proxy_id]["ip"] is None


@pytest.mark.asyncio
async def test_link_proxy_to_account(client: AsyncClient, sample_proxy):
    """Test linking a proxy to an account."""
    # Create a new proxy for this test
    proxy_response = await client.post("/api/proxies/", json={
        "host": "192.168.1.99",
        "port": 1080
    })
    proxy_id = proxy_response.json()["id"]

    # Create an account
    account_response = await client.post("/api/accounts/", json={
        "email": "linktest@example.com"
    })
    account_id = account_response.json()["id"]

    # Link them
    response = await client.post(f"/api/proxies/{proxy_id}/link/{account_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["linked_account_id"] == account_id


@pytest.mark.asyncio
async def test_delete_proxy(client: AsyncClient):
    """Test deleting a proxy."""
    # Create proxy to delete
    response = await client.post("/api/proxies/", json={
        "host": "192.168.1.88",
        "port": 1080
    })
    proxy_id = response.json()["id"]

    response = await client.delete(f"/api/proxies/{proxy_id}")
    assert response.status_code == 200

    # Verify it's gone
    response = await client.get(f"/api/proxies/{proxy_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_proxy_provider_status_route(client: AsyncClient, monkeypatch):
    """Test provider status route is reachable and not swallowed by /{proxy_id}."""
    from app.routers import proxies as proxies_router

    class MockProvider:
        async def get_provider_status(self):
            return {
                "connected": True,
                "provider": "webshare (mock)",
                "total_proxies": 100,
                "used_proxies": 2,
                "available": 98,
            }

    monkeypatch.setattr(proxies_router, "_proxy_provider", MockProvider())

    response = await client.get("/api/proxies/provider/status")

    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "provider": "webshare (mock)",
        "total_proxies": 100,
        "used_proxies": 2,
        "available": 98,
    }


@pytest.mark.asyncio
async def test_replace_proxy_for_account_route(client: AsyncClient, sample_account, monkeypatch):
    """Test replace-proxy account route returns the replacement payload."""
    from app.routers import accounts as accounts_router

    replacement = SimpleNamespace(
        id="proxy-replacement-id",
        host="replacement.proxy.local",
        port=23456,
    )

    class MockProvider:
        async def replace_proxy_for_account(self, account_id):
            assert str(account_id) == sample_account["id"]
            return replacement

    monkeypatch.setattr(accounts_router, "_proxy_provider", MockProvider())

    response = await client.post(f"/api/accounts/{sample_account['id']}/replace-proxy")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Proxy replaced",
        "proxy_id": "proxy-replacement-id",
        "host": "replacement.proxy.local",
        "port": 23456,
    }
