import pytest
import uuid
from httpx import AsyncClient
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
from app.models.account import AccountStatus


@pytest.mark.asyncio
async def test_create_account(client: AsyncClient, sample_proxy):
    """Test creating a new account."""
    response = await client.post("/api/accounts/", json={
        "email": "newuser@example.com",
        "display_name": "New User",
        "type": "premium",
        "proxy_id": sample_proxy["id"]
    })

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["display_name"] == "New User"
    assert data["type"] == "premium"
    assert data["status"] == "new"
    assert data["proxy_id"] == sample_proxy["id"]


@pytest.mark.asyncio
async def test_create_account_auto_provisions_proxy(client: AsyncClient, monkeypatch):
    """Test creating an account auto-provisions a proxy when a provider is configured."""
    from app.routers import accounts as accounts_router

    proxy_response = await client.post("/api/proxies/", json={
        "host": "192.168.20.10",
        "port": 1080
    })
    proxy = proxy_response.json()

    mock_provider = type("MockProvider", (), {
        "provision_proxy": AsyncMock(return_value=SimpleNamespace(
            id=uuid.UUID(proxy["id"]),
            host=proxy["host"],
            port=proxy["port"],
        ))
    })()
    monkeypatch.setattr(accounts_router, "_proxy_provider", mock_provider)

    response = await client.post("/api/accounts/", json={
        "email": "autoprovision@example.com"
    })

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "autoprovision@example.com"
    assert data["proxy_id"] == proxy["id"]
    mock_provider.provision_proxy.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_accounts(client: AsyncClient, sample_account):
    """Test listing accounts."""
    response = await client.get("/api/accounts/")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "skip" in data
    assert "limit" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) >= 1


@pytest.mark.asyncio
async def test_filter_accounts_by_status(client: AsyncClient, sample_account):
    """Test filtering accounts by status."""
    # The sample account is 'new'
    response = await client.get("/api/accounts/?status=new")

    assert response.status_code == 200
    data = response.json()
    assert all(a["status"] == "new" for a in data["items"])


@pytest.mark.asyncio
async def test_filter_accounts_by_type(client: AsyncClient, sample_account):
    """Test filtering accounts by type."""
    # Create a premium account
    await client.post("/api/proxies/", json={
        "host": "192.168.1.101",
        "port": 1080
    })
    proxy_result = await client.get("/api/proxies/?unlinked=true")
    unlinked = proxy_result.json()
    if unlinked:
        await client.post("/api/accounts/", json={
            "email": "premium@example.com",
            "type": "premium",
            "proxy_id": unlinked[0]["id"]
        })

    response = await client.get("/api/accounts/?type=free")

    assert response.status_code == 200
    data = response.json()
    assert all(a["type"] == "free" for a in data["items"])


@pytest.mark.asyncio
async def test_import_accounts_auto_provisions_proxies(client: AsyncClient, monkeypatch):
    """Test CSV import auto-provisions proxies for imported accounts."""
    from app.routers import accounts as accounts_router

    proxy1_response = await client.post("/api/proxies/", json={
        "host": "192.168.20.11",
        "port": 1080
    })
    proxy2_response = await client.post("/api/proxies/", json={
        "host": "192.168.20.12",
        "port": 1080
    })
    proxy1 = proxy1_response.json()
    proxy2 = proxy2_response.json()

    mock_provider = type("MockProvider", (), {
        "provision_proxy": AsyncMock(side_effect=[
            SimpleNamespace(id=uuid.UUID(proxy1["id"]), host=proxy1["host"], port=proxy1["port"]),
            SimpleNamespace(id=uuid.UUID(proxy2["id"]), host=proxy2["host"], port=proxy2["port"]),
        ])
    })()
    monkeypatch.setattr(accounts_router, "_proxy_provider", mock_provider)

    csv_content = "email,password,type\nimport1@example.com,pass123,free\nimport2@example.com,pass456,free\n"
    response = await client.post(
        "/api/accounts/import",
        files={"file": ("accounts.csv", csv_content, "text/csv")}
    )

    assert response.status_code == 200
    assert response.json()["imported"] == 2
    assert mock_provider.provision_proxy.await_count == 2

    accounts_response = await client.get("/api/accounts/")
    assert accounts_response.status_code == 200
    accounts = {account["email"]: account for account in accounts_response.json()["items"]}
    assert accounts["import1@example.com"]["proxy_id"] == proxy1["id"]
    assert accounts["import2@example.com"]["proxy_id"] == proxy2["id"]


@pytest.mark.asyncio
async def test_get_account(client: AsyncClient, sample_account):
    """Test getting a specific account."""
    account_id = sample_account["id"]
    response = await client.get(f"/api/accounts/{account_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == account_id
    assert data["email"] == sample_account["email"]


@pytest.mark.asyncio
async def test_update_account(client: AsyncClient, sample_account):
    """Test updating an account."""
    account_id = sample_account["id"]

    response = await client.patch(f"/api/accounts/{account_id}", json={
        "display_name": "Updated Name"
    })

    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_set_cooldown(client: AsyncClient, sample_account):
    """Test setting account cooldown."""
    account_id = sample_account["id"]

    response = await client.post(
        f"/api/accounts/{account_id}/set-cooldown",
        params={"hours": 12}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cooldown"
    assert data["cooldown_until"] is not None


@pytest.mark.asyncio
async def test_force_active(client: AsyncClient, sample_account):
    """Test forcing account to active status."""
    account_id = sample_account["id"]

    # First set cooldown
    await client.post(f"/api/accounts/{account_id}/set-cooldown", params={"hours": 6})

    # Then force active
    response = await client.post(f"/api/accounts/{account_id}/force-active")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["cooldown_until"] is None


@pytest.mark.asyncio
async def test_delete_account(client: AsyncClient, sample_proxy):
    """Test deleting an account."""
    # Create an account to delete
    response = await client.post("/api/accounts/", json={
        "email": "todelete@example.com",
        "proxy_id": sample_proxy["id"]
    })
    account_id = response.json()["id"]

    response = await client.delete(f"/api/accounts/{account_id}")
    assert response.status_code == 200

    # Verify it's gone
    response = await client.get(f"/api/accounts/{account_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_account_burns_proxy(client: AsyncClient, monkeypatch):
    """Test deleting an account burns its proxy through the configured provider."""
    from app.routers import accounts as accounts_router

    proxy_response = await client.post("/api/proxies/", json={
        "host": "192.168.10.10",
        "port": 1080
    })
    proxy_id = proxy_response.json()["id"]

    account_response = await client.post("/api/accounts/", json={
        "email": "burndelete@example.com",
        "proxy_id": proxy_id
    })
    account_id = account_response.json()["id"]

    mock_provider = type("MockProvider", (), {"release_proxy": AsyncMock(return_value=True)})()
    monkeypatch.setattr(accounts_router, "_proxy_provider", mock_provider)

    response = await client.delete(f"/api/accounts/{account_id}")

    assert response.status_code == 200
    mock_provider.release_proxy.assert_awaited_once()
    burned_proxy_id = str(mock_provider.release_proxy.await_args.args[0])
    assert burned_proxy_id == proxy_id


@pytest.mark.asyncio
async def test_banning_account_burns_proxy(client: AsyncClient, monkeypatch):
    """Test banning an account burns its proxy through the configured provider."""
    from app.routers import accounts as accounts_router

    proxy_response = await client.post("/api/proxies/", json={
        "host": "192.168.10.11",
        "port": 1080
    })
    proxy_id = proxy_response.json()["id"]

    account_response = await client.post("/api/accounts/", json={
        "email": "burnban@example.com",
        "proxy_id": proxy_id
    })
    account_id = account_response.json()["id"]

    mock_provider = type("MockProvider", (), {"release_proxy": AsyncMock(return_value=True)})()
    monkeypatch.setattr(accounts_router, "_proxy_provider", mock_provider)

    response = await client.patch(f"/api/accounts/{account_id}", json={
        "status": AccountStatus.BANNED.value
    })

    assert response.status_code == 200
    assert response.json()["status"] == AccountStatus.BANNED.value
    mock_provider.release_proxy.assert_awaited_once()
    burned_proxy_id = str(mock_provider.release_proxy.await_args.args[0])
    assert burned_proxy_id == proxy_id


@pytest.mark.asyncio
async def test_register_accounts_route(client: AsyncClient, monkeypatch):
    """Test the registration endpoint is reachable and returns the batch result."""
    from app.services.registration_service import RegistrationService
    instance_id = str(uuid.uuid4())

    mock_register_batch = AsyncMock(return_value={
        "registered": 1,
        "failed": 0,
        "accounts": ["account-1"],
        "capped_at": None,
    })
    monkeypatch.setattr(RegistrationService, "register_batch", mock_register_batch)

    response = await client.post(
        "/api/accounts/register",
        params=[("count", "1"), ("instance_ids", instance_id)],
    )

    assert response.status_code == 200
    assert response.json() == {
        "registered": 1,
        "failed": 0,
        "accounts": ["account-1"],
        "capped_at": None,
    }
    mock_register_batch.assert_awaited_once()
    assert mock_register_batch.await_args.kwargs["instance_ids"] == [uuid.UUID(instance_id)]


@pytest.mark.asyncio
async def test_create_batch_alias_route(client: AsyncClient, monkeypatch):
    """Test the legacy create-batch alias still routes to registration."""
    from app.services.registration_service import RegistrationService
    instance_id = str(uuid.uuid4())

    mock_register_batch = AsyncMock(return_value={
        "registered": 2,
        "failed": 0,
        "accounts": ["account-1", "account-2"],
        "capped_at": None,
    })
    monkeypatch.setattr(RegistrationService, "register_batch", mock_register_batch)

    response = await client.post(
        "/api/accounts/create-batch",
        params=[("count", "2"), ("instance_ids", instance_id)],
    )

    assert response.status_code == 200
    assert response.json() == {
        "registered": 2,
        "failed": 0,
        "accounts": ["account-1", "account-2"],
        "capped_at": None,
    }
    mock_register_batch.assert_awaited_once()
    assert mock_register_batch.await_args.kwargs["instance_ids"] == [uuid.UUID(instance_id)]


@pytest.mark.asyncio
async def test_extract_session_route(client: AsyncClient, sample_account, monkeypatch):
    """Test extracting session for an account via the API."""
    from app.services import adb_service

    account_id = sample_account["id"]

    # Mock extract_session to return a path
    mock_extract = AsyncMock(return_value="/data/sessions/test_device/session")
    monkeypatch.setattr(adb_service.ADBService, "extract_session", mock_extract)

    response = await client.post(
        f"/api/accounts/{account_id}/extract-session",
        params={"device_id": "localhost:5555"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Session extracted successfully"
    assert data["session_blob_path"] == "/data/sessions/test_device/session"
    assert data["account_id"] == account_id
    mock_extract.assert_awaited_once_with("localhost:5555")

    # Verify account now has session_blob_path
    account_response = await client.get(f"/api/accounts/{account_id}")
    assert account_response.json()["session_blob_path"] == "/data/sessions/test_device/session"


@pytest.mark.asyncio
async def test_extract_session_no_device_id(client: AsyncClient, sample_account, monkeypatch):
    """Test extracting session without device_id requires an assigned instance with adb_port."""
    from app.services import adb_service

    account_id = sample_account["id"]

    # Mock extract_session
    mock_extract = AsyncMock(return_value="/data/sessions/instance_session/session")
    monkeypatch.setattr(adb_service.ADBService, "extract_session", mock_extract)

    # Should fail because account has no assigned instance with adb_port
    response = await client.post(f"/api/accounts/{account_id}/extract-session")

    # Should fail with 400 because no instance is assigned
    assert response.status_code == 400
    assert "device_id required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_inject_session_route(client: AsyncClient, sample_account, monkeypatch):
    """Test injecting session for an account via the API."""
    from app.services import adb_service

    account_id = sample_account["id"]

    # First set up a session on the account
    mock_extract = AsyncMock(return_value="/data/sessions/inject_test/session")
    monkeypatch.setattr(adb_service.ADBService, "extract_session", mock_extract)

    await client.post(
        f"/api/accounts/{account_id}/extract-session",
        params={"device_id": "localhost:5556"}
    )

    # Now test injection
    mock_inject = AsyncMock(return_value=True)
    monkeypatch.setattr(adb_service.ADBService, "inject_session", mock_inject)

    response = await client.post(
        f"/api/accounts/{account_id}/inject-session",
        params={"device_id": "localhost:5556"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Session injected successfully"
    assert data["account_id"] == account_id
    assert data["device_id"] == "localhost:5556"
    mock_inject.assert_awaited_once_with("localhost:5556", session_dir="/data/sessions/inject_test/session")


@pytest.mark.asyncio
async def test_inject_session_no_stored_session(client: AsyncClient, sample_account):
    """Test injecting session fails when account has no stored session."""
    account_id = sample_account["id"]

    response = await client.post(
        f"/api/accounts/{account_id}/inject-session",
        params={"device_id": "localhost:5557"}
    )

    assert response.status_code == 400
    assert "no stored session" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_registration_real_mode_fails_without_device_context(monkeypatch):
    """Test that real-mode registration fails explicitly without device context."""
    from app.services.registration_service import RegistrationService
    from app.config import settings

    # Force real mode
    monkeypatch.setattr(settings, "REGISTRATION_MOCK", False)

    # Create service with mocked dependencies
    reg_service = RegistrationService(
        tempmail=AsyncMock(),
        adb=AsyncMock(),
        spotify=AsyncMock(),
        db_session_maker=None,
        alerting=None,
        proxy_provider=None
    )

    # Mock tempmail to avoid actual API calls
    reg_service.tempmail.create_mailbox = AsyncMock(return_value={
        "address": "test@example.com",
        "token": "test_token"
    })

    # Attempt registration without device_id should fail
    mock_db = AsyncMock()

    with pytest.raises(RuntimeError, match="device_id required"):
        await reg_service.register_account(mock_db, instance_id=None, device_id=None)


@pytest.mark.asyncio
async def test_registration_does_not_create_account_on_failure(monkeypatch):
    """Test that registration does not commit account if verification fails."""
    from app.services.registration_service import RegistrationService
    from app.config import settings

    # Force real mode
    monkeypatch.setattr(settings, "REGISTRATION_MOCK", False)

    # Create service with mocked dependencies
    reg_service = RegistrationService(
        tempmail=AsyncMock(),
        adb=AsyncMock(),
        spotify=AsyncMock(),
        db_session_maker=None,
        alerting=None,
        proxy_provider=None
    )

    # Mock tempmail
    reg_service.tempmail.create_mailbox = AsyncMock(return_value={
        "address": "test@example.com",
        "token": "test_token"
    })
    reg_service.tempmail.wait_for_message = AsyncMock(return_value=None)  # Simulate no verification email

    # Mock spotify
    reg_service.spotify.launch_spotify = AsyncMock(return_value=True)
    reg_service._complete_signup_flow = AsyncMock(return_value=None)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    # Should raise error when verification fails
    with pytest.raises(RuntimeError, match="No verification email received"):
        await reg_service.register_account(mock_db, instance_id=None, device_id="localhost:5555")

    # Verify db.commit was never called (no account created)
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_registration_does_not_create_account_when_session_extraction_fails(monkeypatch):
    """Test that registration aborts before commit if session extraction fails."""
    from app.services.registration_service import RegistrationService
    from app.config import settings

    monkeypatch.setattr(settings, "REGISTRATION_MOCK", False)

    reg_service = RegistrationService(
        tempmail=AsyncMock(),
        adb=AsyncMock(),
        spotify=AsyncMock(),
        db_session_maker=None,
        alerting=None,
        proxy_provider=None
    )

    reg_service.tempmail.create_mailbox = AsyncMock(return_value={
        "address": "sessionfail@example.com",
        "token": "test_token"
    })
    reg_service.tempmail.wait_for_message = AsyncMock(return_value={"text": "Your Spotify code is 123456"})
    reg_service.tempmail.extract_otp = Mock(return_value="123456")
    reg_service.tempmail.extract_verification_link = Mock(return_value=None)
    reg_service._complete_signup_flow = AsyncMock(return_value=None)
    reg_service._complete_email_verification = AsyncMock(return_value=None)
    reg_service.adb.extract_session = AsyncMock(return_value=None)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    with pytest.raises(RuntimeError, match="Session extraction failed"):
        await reg_service.register_account(mock_db, instance_id=None, device_id="localhost:5555")

    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_batch_requires_instances_in_real_mode(monkeypatch):
    """Test that register_batch requires instance_ids in real mode."""
    from app.services.registration_service import RegistrationService
    from app.config import settings
    from app.models.setting import Setting

    # Force real mode
    monkeypatch.setattr(settings, "REGISTRATION_MOCK", False)

    reg_service = RegistrationService(
        tempmail=AsyncMock(),
        adb=AsyncMock(),
        spotify=AsyncMock(),
        db_session_maker=None,
        alerting=None,
        proxy_provider=None
    )

    # Setup mock DB with proper setting return
    mock_db = AsyncMock()

    # Create a mock setting that looks like a real Setting object
    mock_setting = Setting(key="daily_account_creation_cap", value="20")
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = Mock(return_value=mock_setting)
    mock_db.execute = AsyncMock(return_value=mock_result)

    # Should fail when no instance_ids provided in real mode
    with pytest.raises(RuntimeError, match="instance_ids required"):
        await reg_service.register_batch(mock_db, count=1, instance_ids=None)
