import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket
from sqlalchemy import inspect, text
from sqlalchemy.exc import NoSuchTableError

from app.config import settings
from app.database import engine, async_session_maker
from app.models import Base
from app.routers import instances, accounts, proxies, songs, stream_logs, settings as settings_router, system, scheduler as scheduler_router, warmup as warmup_router
from app.ws.dashboard import dashboard_websocket_handler, ws_manager
from app.routers.settings import seed_default_settings
from app.services.automation.song_scheduler import SongScheduler
from app.services.automation.health_monitor import HealthMonitor
from app.routers.scheduler import set_schedulers
from app.services.proxy_health_checker import ProxyHealthChecker
from app.services.antidetect.rate_limiter import RateLimiter
from app.services.antidetect.warmup import WarmupManager
from app.services.alerting import AlertingService, AlertSeverity
from app.services.song_estimator import SongEstimator
from app.services.cluster import MachineRegistry, LoadBalancer
from app.routers import cluster as cluster_router, alerts as alerts_router, challenges as challenges_router
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Gauge, Counter

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def get_proxy_columns(sync_conn):
            try:
                return {column["name"] for column in inspect(sync_conn).get_columns("proxies")}
            except NoSuchTableError:
                return set()

        proxy_columns = await conn.run_sync(get_proxy_columns)
        statements: list[str] = []
        if proxy_columns:
            if "ip" not in proxy_columns:
                if conn.dialect.name == "postgresql":
                    statements.append("ALTER TABLE proxies ADD COLUMN IF NOT EXISTS ip VARCHAR(64)")
                else:
                    statements.append("ALTER TABLE proxies ADD COLUMN ip VARCHAR(64)")
            if "latency_ms" not in proxy_columns:
                if conn.dialect.name == "postgresql":
                    statements.append("ALTER TABLE proxies ADD COLUMN IF NOT EXISTS latency_ms FLOAT")
                else:
                    statements.append("ALTER TABLE proxies ADD COLUMN latency_ms FLOAT")

        for statement in statements:
            await conn.execute(text(statement))
    logger.info("Database tables initialized")


async def seed_settings():
    """Seed default settings."""
    async with async_session_maker() as session:
        await seed_default_settings(session)
    logger.info("Default settings seeded")


# Global service instances
health_checker: ProxyHealthChecker | None = None
song_scheduler: SongScheduler | None = None
health_monitor: HealthMonitor | None = None
rate_limiter: RateLimiter | None = None
warmup_manager: WarmupManager | None = None
alerting_service: AlertingService | None = None
song_estimator: SongEstimator | None = None
machine_registry: MachineRegistry | None = None
load_balancer: LoadBalancer | None = None
digest_scheduler: AsyncIOScheduler | None = None
proxy_provider = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global health_checker, song_scheduler, health_monitor, rate_limiter, warmup_manager, alerting_service, song_estimator, machine_registry, load_balancer, digest_scheduler, proxy_provider

    # Startup
    logger.info("Starting up 4ARM backend...")
    await init_db()
    await seed_settings()

    # Initialize Phase 7: Scaling & Monitoring
    alerting_service = AlertingService(
        db_session_maker=async_session_maker,
        ws_manager=ws_manager
    )
    logger.info("AlertingService initialized")

    song_estimator = SongEstimator(db_session_maker=async_session_maker)
    logger.info("SongEstimator initialized")

    if settings.CLUSTER_ENABLED:
        machine_registry = MachineRegistry(db_session_maker=async_session_maker)
        load_balancer = LoadBalancer(machine_registry=machine_registry)
        logger.info("Cluster services initialized (CLUSTER_ENABLED=true)")
    else:
        logger.info("Cluster mode disabled (CLUSTER_ENABLED=false)")

    # Initialize anti-detection components (Phase 6)
    rate_limiter = RateLimiter(
        db_session_maker=async_session_maker,
        ws_manager=ws_manager
    )
    logger.info("RateLimiter initialized")

    warmup_manager = WarmupManager()
    logger.info("WarmupManager initialized")

    # Start proxy health checker
    health_checker = ProxyHealthChecker(
        db_session_maker=async_session_maker,
        ws_manager=ws_manager,
        check_interval_minutes=5
    )
    health_checker.start()

    # Start song scheduler (Phase 3 automation) with rate limiter
    song_scheduler = SongScheduler(
        db_session_maker=async_session_maker,
        ws_manager=ws_manager,
        rate_limiter=rate_limiter
    )
    song_scheduler.start()

    # Start health monitor (Phase 3 automation)
    health_monitor = HealthMonitor(
        db_session_maker=async_session_maker,
        ws_manager=ws_manager
    )
    health_monitor.start()

    # Set scheduler references for router (with rate limiter and alerting)
    set_schedulers(song_scheduler, health_monitor, rate_limiter, alerting_service)

    # Set cluster router services
    from app.routers.cluster import set_cluster_services
    if machine_registry and load_balancer:
        set_cluster_services(machine_registry, load_balancer)

    # Set alerts router service
    from app.routers.alerts import set_alerting_service as set_alerts_service
    set_alerts_service(alerting_service)

    # Initialize proxy provider
    from app.services.proxy_provider import ProxyProviderService
    if settings.PROXY_PROVIDER.lower() == "webshare" and (settings.WEBSHARE_API_KEY or settings.PROXY_AUTO_PROVISION):
        proxy_provider = ProxyProviderService(
            api_key=settings.WEBSHARE_API_KEY,
            db_session_maker=async_session_maker
        )
        logger.info(f"ProxyProviderService initialized (mock={proxy_provider.mock_mode})")

        # Set on routers
        from app.routers.accounts import set_proxy_provider as set_accounts_proxy
        from app.routers.proxies import set_proxy_provider as set_proxies_proxy
        set_accounts_proxy(proxy_provider)
        set_proxies_proxy(proxy_provider)
    else:
        logger.info("Proxy provider disabled or set to manual mode")

    # Schedule daily digest
    async def send_daily_digest():
        """Send daily digest alert."""
        try:
            async with async_session_maker() as db:
                await alerting_service.send_daily_digest(db)
        except Exception as e:
            logger.error(f"Failed to send daily digest: {e}")

    digest_scheduler = AsyncIOScheduler()
    digest_scheduler.add_job(
        send_daily_digest,
        CronTrigger(hour=0, minute=0),  # Midnight UTC
        id="daily_digest",
        replace_existing=True
    )
    digest_scheduler.start()
    logger.info("Daily digest scheduled for midnight UTC")

    logger.info("Startup complete - Phase 7 Scaling & Monitoring active")

    yield

    # Shutdown
    logger.info("Shutting down 4ARM backend...")
    if health_checker:
        health_checker.stop()
    if song_scheduler:
        song_scheduler.stop()
    if health_monitor:
        health_monitor.stop()
    if digest_scheduler:
        digest_scheduler.shutdown(wait=True)
    await engine.dispose()
    logger.info("Shutdown complete - Phase 7 Scaling & Monitoring components stopped")


# Create FastAPI app
app = FastAPI(
    title="4ARM Backend API",
    description="Spotify streaming farm management API",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus instrumentation (must be before routers)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)

# Include routers
app.include_router(instances.router)
app.include_router(accounts.router)
app.include_router(proxies.router)
app.include_router(songs.router)
app.include_router(stream_logs.router)
app.include_router(settings_router.router)
app.include_router(system.router)
app.include_router(scheduler_router.router)
app.include_router(warmup_router.router)
app.include_router(cluster_router.router)
app.include_router(alerts_router.router)
app.include_router(challenges_router.router)


# WebSocket endpoint
@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await dashboard_websocket_handler(websocket)


# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "service": "4arm-backend"}


# Custom Prometheus metrics
ACTIVE_STREAMS = Gauge("fourarm_active_streams", "Currently active streams")
STREAMS_TOTAL = Counter("fourarm_streams_total", "Total streams", ["result"])
ACTIVE_INSTANCES = Gauge("fourarm_active_instances", "Running instances")
WARMING_ACCOUNTS = Gauge("fourarm_warming_accounts", "Accounts in warmup")
RATE_LIMIT_BLOCKS = Counter("fourarm_rate_limit_blocks", "Rate limit blocks", ["reason"])


# Root
@app.get("/")
async def root():
    return {
        "service": "4ARM Backend API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
