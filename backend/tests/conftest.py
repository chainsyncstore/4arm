import time
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base
from app.database import get_db
from app.config import settings

# Use an in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=StaticPool,
    future=True,
    echo=False,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def override_get_db():
    async with TestingSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def override_global_db_refs(monkeypatch):
    """Ensure modules importing app.database use the in-memory test session maker."""
    import app.database as database_module
    import app.main as main_module

    monkeypatch.setattr(database_module, "async_session_maker", TestingSessionLocal)
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(main_module, "async_session_maker", TestingSessionLocal, raising=False)
    monkeypatch.setattr(main_module, "engine", engine, raising=False)


@pytest.fixture
def mock_settings(monkeypatch):
    """Force mock infrastructure for tests that rely on mock proxy/docker behavior."""
    monkeypatch.setattr(settings, "MOCK_DOCKER", True)
    monkeypatch.setattr(settings, "MOCK_ADB", True)
    return settings


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create test database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Create a fresh database session for each test."""
    # Drop and recreate all tables for a clean slate
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session
        # Clean up after test
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_engine):
    """Create an async test client with a clean database."""
    # Drop and recreate all tables for a clean slate
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Seed default settings (normally done in app lifespan)
    from app.routers.settings import seed_default_settings
    async with TestingSessionLocal() as session:
        await seed_default_settings(session)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def sample_song(client):
    """Create a sample song for testing."""
    response = await client.post("/api/songs/", json={
        "spotify_uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
        "title": "Test Song",
        "artist": "Test Artist",
        "total_target_streams": 1000,
        "daily_rate": 100,
        "priority": "medium"
    })
    return response.json()


@pytest_asyncio.fixture
async def sample_proxy(client):
    """Create a sample proxy for testing."""
    response = await client.post("/api/proxies/", json={
        "host": "192.168.1.100",
        "port": 1080,
        "username": "user",
        "password": "pass",
        "protocol": "socks5",
        "country": "US"
    })
    return response.json()


@pytest_asyncio.fixture
async def sample_account(client, sample_proxy):
    """Create a sample account for testing."""
    response = await client.post("/api/accounts/", json={
        "email": "test@example.com",
        "display_name": "Test User",
        "type": "free",
        "proxy_id": sample_proxy["id"]
    })
    return response.json()


@pytest_asyncio.fixture
async def sample_instance(client):
    """Create a sample instance for testing."""
    response = await client.post("/api/instances/", json={
        "name": "test-instance-01",
        "ram_limit_mb": 2048,
        "cpu_cores": 2.0
    })
    return response.json()
