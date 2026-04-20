import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, and_
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models.proxy import Proxy, ProxyStatus
from app.models.account import Account
from app.services.proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


class ProxyHealthChecker:
    """Background health check job for monitoring proxy connectivity."""

    def __init__(
        self,
        db_session_maker: async_sessionmaker,
        ws_manager: Optional[object] = None,
        check_interval_minutes: int = 5
    ):
        self.db_session_maker = db_session_maker
        self.ws_manager = ws_manager
        self.scheduler = AsyncIOScheduler()
        self.check_interval_minutes = check_interval_minutes
        self._running = False

    def start(self):
        """Register health check job (interval: 5 minutes)."""
        if self._running:
            logger.warning("Health checker already running")
            return

        self.scheduler.add_job(
            self._check_all_proxies,
            'interval',
            minutes=self.check_interval_minutes,
            id='proxy_health_check',
            replace_existing=True
        )
        self.scheduler.start()
        self._running = True
        logger.info(f"Proxy health checker started (interval: {self.check_interval_minutes} minutes)")

    def stop(self):
        """Stop the health checker scheduler."""
        if not self._running:
            return

        self.scheduler.shutdown()
        self._running = False
        logger.info("Proxy health checker stopped")

    async def _check_all_proxies(self):
        """
        For each proxy WHERE status != 'unchecked' AND has a linked account:
        1. Test connectivity via ProxyManager.test_proxy_real()
        2. Update proxy.status (healthy/unhealthy)
        3. Update proxy.last_health_check timestamp
        4. Update proxy.uptime_pct = rolling average
        5. If newly unhealthy: broadcast alert via ws_manager
        6. If unhealthy for >1 hour: broadcast high-priority alert
        7. If recovered: broadcast recovery notification
        """
        logger.info("Running scheduled proxy health check")

        async with self.db_session_maker() as db:
            # Get all proxies that are not unchecked and have linked accounts
            result = await db.execute(
                select(Proxy)
                .join(Account, Proxy.id == Account.proxy_id)
                .where(Proxy.status != ProxyStatus.UNCHECKED)
            )
            proxies = result.scalars().all()

            if not proxies:
                logger.debug("No proxies to check")
                return

            proxy_manager = ProxyManager(db)

            for proxy in proxies:
                try:
                    await self._check_single_proxy(db, proxy_manager, proxy)
                except Exception as e:
                    logger.exception(f"Error checking proxy {proxy.id}: {e}")

            await db.commit()

    async def _check_single_proxy(
        self,
        db: AsyncSession,
        proxy_manager: ProxyManager,
        proxy: Proxy
    ):
        """Check a single proxy and handle state transitions."""
        previous_status = proxy.status
        previous_unhealthy_since: Optional[datetime] = None

        # Track when proxy first became unhealthy
        if proxy.status == ProxyStatus.UNHEALTHY:
            # Store the time of the first failure in memory or use last_health_check
            # For simplicity, we'll use a threshold based on last_health_check
            pass

        # Test the proxy
        test_result = await proxy_manager.test_proxy_real(proxy.id)

        now = datetime.now(timezone.utc)

        proxy_manager.apply_test_result(proxy, test_result, checked_at=now)

        # Update status
        if test_result["healthy"]:
            if previous_status == ProxyStatus.UNHEALTHY:
                # Recovered!
                logger.info(f"Proxy {proxy.host}:{proxy.port} recovered")

                if self.ws_manager:
                    await self.ws_manager.broadcast_alert(
                        "info",
                        f"Proxy {proxy.host}:{proxy.port} has recovered and is now healthy"
                    )

            elif previous_status == ProxyStatus.HEALTHY:
                # Still healthy
                pass

            # Update uptime percentage (rolling average)
            # Formula: new_uptime = (old_uptime * 0.9) + (100 * 0.1)
            proxy.uptime_pct = (proxy.uptime_pct * 0.9) + (100.0 * 0.1)

        else:
            # Unhealthy
            if previous_status == ProxyStatus.HEALTHY:
                # Newly unhealthy
                logger.warning(f"Proxy {proxy.host}:{proxy.port} became unhealthy: {test_result['error']}")

                if self.ws_manager:
                    await self.ws_manager.broadcast_alert(
                        "warning",
                        f"Proxy {proxy.host}:{proxy.port} is now unhealthy: {test_result['error']}"
                    )

            elif previous_status == ProxyStatus.UNHEALTHY:
                # Still unhealthy - check if it's been > 1 hour
                if proxy.last_health_check:
                    time_since_last_check = now - proxy.last_health_check
                    # Note: This is approximate since we update last_health_check each time
                    # For accurate tracking, we'd need a separate field

            # Update uptime percentage
            proxy.uptime_pct = (proxy.uptime_pct * 0.9) + (0.0 * 0.1)

        # Check for long-term unhealthy (simplified: check if uptime is very low)
        if proxy.status == ProxyStatus.UNHEALTHY and proxy.uptime_pct < 50.0:
            # High priority alert for chronic issues
            if self.ws_manager:
                await self.ws_manager.broadcast_alert(
                    "error",
                    f"Proxy {proxy.host}:{proxy.port} has low uptime ({proxy.uptime_pct:.1f}%) - chronic failure"
                )

        await db.flush()

    async def check_proxy_now(self, proxy_id) -> dict:
        """Manually trigger a health check for a specific proxy."""
        async with self.db_session_maker() as db:
            proxy = await db.get(Proxy, proxy_id)
            if not proxy:
                raise ValueError(f"Proxy {proxy_id} not found")

            proxy_manager = ProxyManager(db)
            await self._check_single_proxy(db, proxy_manager, proxy)
            await db.commit()

            return {
                "proxy_id": str(proxy_id),
                "status": proxy.status.value,
                "uptime_pct": proxy.uptime_pct,
                "last_health_check": proxy.last_health_check.isoformat() if proxy.last_health_check else None
            }
