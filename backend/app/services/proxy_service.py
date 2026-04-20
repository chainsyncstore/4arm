import logging
import uuid
import random
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.proxy import Proxy, ProxyStatus, ProxyProtocol
from app.models.account import Account
from app.schemas.proxy import ProxyCreate, ProxyUpdate, ProxyTestResult
from app.config import settings
from app.services.proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


class ProxyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.mock_mode = settings.MOCK_DOCKER

    async def _persist_test_result(self, proxy: Proxy, result: dict, checked_at: Optional[datetime] = None) -> ProxyTestResult:
        ProxyManager.apply_test_result(proxy, result, checked_at=checked_at)
        await self.db.commit()
        await self.db.refresh(proxy)
        return ProxyTestResult(**result)

    async def create_proxy(self, data: ProxyCreate) -> Proxy:
        """Create a new proxy."""
        proxy = Proxy(
            host=data.host,
            port=data.port,
            username=data.username,
            password=data.password,
            protocol=data.protocol,
            country=data.country,
            status=ProxyStatus.UNCHECKED
        )
        self.db.add(proxy)
        await self.db.commit()
        await self.db.refresh(proxy)
        logger.info(f"Created proxy {proxy.host}:{proxy.port}")
        return proxy

    async def import_proxies_from_csv(self, csv_content: str) -> list[Proxy]:
        """Import proxies from CSV.
        Expected columns: host,port,username,password,protocol,country
        """
        import csv
        from io import StringIO

        proxies = []
        f = StringIO(csv_content)
        reader = csv.DictReader(f)

        for row in reader:
            try:
                proxy = Proxy(
                    host=row['host'],
                    port=int(row['port']),
                    username=row.get('username'),
                    password=row.get('password'),
                    protocol=row.get('protocol', 'socks5'),
                    country=row.get('country'),
                    status=ProxyStatus.UNCHECKED
                )
                self.db.add(proxy)
                proxies.append(proxy)
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping invalid proxy row: {e}")
                continue

        await self.db.commit()
        for p in proxies:
            await self.db.refresh(p)

        logger.info(f"Imported {len(proxies)} proxies from CSV")
        return proxies

    async def get_proxy(self, proxy_id: uuid.UUID) -> Optional[Proxy]:
        """Get proxy by ID."""
        result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id)
        )
        return result.scalar_one_or_none()

    async def get_unlinked_proxies(self) -> list[Proxy]:
        """Get proxies not assigned to any account."""
        result = await self.db.execute(
            select(Proxy)
            .outerjoin(Account, Proxy.id == Account.proxy_id)
            .where(Account.id.is_(None))
        )
        return result.scalars().all()

    async def update_proxy(self, proxy_id: uuid.UUID, data: ProxyUpdate) -> Proxy:
        """Update proxy fields."""
        result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id)
        )
        proxy = result.scalar_one_or_none()
        if not proxy:
            raise ValueError(f"Proxy {proxy_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(proxy, field, value)

        proxy.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(proxy)
        return proxy

    async def test_proxy(self, proxy_id: uuid.UUID) -> ProxyTestResult:
        """Test proxy connectivity."""
        proxy = await self.get_proxy(proxy_id)
        if not proxy:
            raise ValueError(f"Proxy {proxy_id} not found")

        checked_at = datetime.now(timezone.utc)
        if self.mock_mode:
            # Mock test result
            healthy = random.random() > 0.1  # 90% success rate in mock
            mock_ips = ["1.2.3.4", "5.6.7.8", "9.10.11.12", "13.14.15.16"]

            result = ProxyTestResult(
                healthy=healthy,
                ip=random.choice(mock_ips) if healthy else None,
                latency_ms=random.randint(50, 200) if healthy else None,
                error=None if healthy else "Connection timeout (MOCK)"
            )
            return await self._persist_test_result(proxy, result.model_dump(), checked_at=checked_at)

        proxy_manager = ProxyManager(self.db)
        result = await proxy_manager.test_proxy_real(proxy_id)
        return await self._persist_test_result(proxy, result, checked_at=checked_at)

    async def batch_test_proxies(self) -> dict:
        """Test all proxies and return summary."""
        result = await self.db.execute(select(Proxy))
        proxies = result.scalars().all()

        tested = 0
        healthy = 0
        unhealthy = 0
        for proxy in proxies:
            try:
                test_result = await self.test_proxy(proxy.id)
                tested += 1
                if test_result.healthy:
                    healthy += 1
                else:
                    unhealthy += 1
            except Exception as e:
                logger.warning(f"Failed to test proxy {proxy.id}: {e}")
                tested += 1
                unhealthy += 1

        return {
            "total": len(proxies),
            "tested": tested,
            "healthy": healthy,
            "unhealthy": unhealthy
        }

    async def switch_proxy(self, instance_id: uuid.UUID, proxy_id: uuid.UUID) -> dict:
        """Switch proxy for an instance by reconfiguring redsocks."""
        from app.services.proxy_manager import ProxyManager

        proxy_manager = ProxyManager(self.db)
        result = await proxy_manager.switch_instance_proxy(instance_id, proxy_id)
        return result

    async def delete_proxy(self, proxy_id: uuid.UUID) -> bool:
        """Delete a proxy (unlinks from account first)."""
        result = await self.db.execute(
            select(Proxy).where(Proxy.id == proxy_id)
        )
        proxy = result.scalar_one_or_none()
        if not proxy:
            raise ValueError(f"Proxy {proxy_id} not found")

        # Unlink from account if linked
        account_result = await self.db.execute(
            select(Account).where(Account.proxy_id == proxy_id)
        )
        account = account_result.scalar_one_or_none()
        if account:
            account.proxy_id = None

        await self.db.delete(proxy)
        await self.db.commit()
        logger.info(f"Deleted proxy {proxy.host}:{proxy.port}")
        return True
