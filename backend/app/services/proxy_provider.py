"""Dynamic proxy provisioning via Webshare.io API."""

import logging
import uuid
import random
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.proxy import Proxy, ProxyStatus, ProxyProtocol
from app.models.account import Account
from app.config import settings

logger = logging.getLogger(__name__)


class ProxyProviderService:
    """Manages dynamic proxy provisioning and release via Webshare.io API."""

    BASE_URL = "https://proxy.webshare.io/api/v2"

    def __init__(self, api_key: str, db_session_maker):
        self.api_key = api_key
        self.db_session_maker = db_session_maker
        self.headers = {"Authorization": f"Token {api_key}"}
        self.mock_mode = not api_key  # Mock if no API key configured
        self._proxy_pool_index = 0  # Track position in proxy pool

    async def _get_proxy_list(self, page: int = 1, page_size: int = 25) -> dict:
        """Fetch proxy list from Webshare.
        GET /proxy/list/?mode=direct&page=N&page_size=N
        Returns: {"count": int, "results": [{"proxy_address": str, "port": int, "username": str, "password": str, "country_code": str, ...}]}
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/proxy/list/",
                headers=self.headers,
                params={"mode": "direct", "page": page, "page_size": page_size}
            )
            resp.raise_for_status()
            return resp.json()

    async def _get_proxy_config(self) -> dict:
        """Get current proxy configuration/quota info.
        GET /proxy/config/
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/proxy/config/",
                headers=self.headers
            )
            resp.raise_for_status()
            return resp.json()

    async def _replace_proxy(self, proxy_address: str, proxy_port: int) -> dict:
        """Request a replacement for a specific proxy.
        POST /proxy/replace/
        Body: {"proxy_address": str, "port": int}
        This removes the old proxy from your list and provides a new one.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/proxy/replace/",
                headers=self.headers,
                json={"proxy_address": proxy_address, "port": proxy_port}
            )
            resp.raise_for_status()
            return resp.json()

    async def get_provider_status(self) -> dict:
        """Get status of proxy provider connection and quota.
        Returns: {"connected": bool, "total_proxies": int, "used_proxies": int, "available": int}
        """
        if self.mock_mode:
            return {
                "connected": True,
                "provider": "webshare (mock)",
                "total_proxies": 100,
                "used_proxies": 0,
                "available": 100
            }

        try:
            config = await self._get_proxy_config()
            proxy_list = await self._get_proxy_list(page=1, page_size=1)
            total = proxy_list.get("count", 0)

            # Count how many are linked in our DB
            async with self.db_session_maker() as db:
                result = await db.execute(
                    select(Account).where(Account.proxy_id.isnot(None))
                )
                used = len(result.scalars().all())

            return {
                "connected": True,
                "provider": "webshare",
                "total_proxies": total,
                "used_proxies": used,
                "available": max(0, total - used)
            }
        except Exception as e:
            logger.error(f"Failed to get provider status: {e}")
            return {
                "connected": False,
                "provider": "webshare",
                "error": str(e)
            }

    async def provision_proxy(self, country: str = None) -> Proxy:
        """Provision a new proxy from the provider pool.

        1. Fetch proxy list from Webshare
        2. Find one not yet in our DB
        3. Create Proxy record
        4. Return Proxy ORM object

        In mock mode: creates a fake proxy record with mock data.
        """
        if self.mock_mode:
            # Create mock proxy
            async with self.db_session_maker() as db:
                proxy = Proxy(
                    host=f"mock-proxy-{random.randint(1000, 9999)}.webshare.io",
                    port=random.randint(10000, 60000),
                    username=f"user_{random.randint(100, 999)}",
                    password=f"pass_{random.randint(10000, 99999)}",
                    protocol=ProxyProtocol.SOCKS5,
                    country=country or settings.PROXY_COUNTRY or "US",
                    status=ProxyStatus.HEALTHY
                )
                db.add(proxy)
                await db.commit()
                await db.refresh(proxy)
                logger.info(f"MOCK: Provisioned proxy {proxy.host}:{proxy.port}")
                return proxy

        # Real Webshare provisioning
        country_filter = country or settings.PROXY_COUNTRY

        # Fetch available proxies from Webshare
        proxy_list = await self._get_proxy_list(page=1, page_size=100)
        results = proxy_list.get("results", [])

        if not results:
            raise RuntimeError("No proxies available from Webshare")

        # Get all proxy hosts already in our DB to avoid duplicates
        async with self.db_session_maker() as db:
            existing_result = await db.execute(select(Proxy.host, Proxy.port))
            existing = {(row[0], row[1]) for row in existing_result.all()}

            # Find an unassigned proxy from Webshare
            selected = None
            for p in results:
                addr = p["proxy_address"]
                port = p["port"]
                p_country = p.get("country_code", "")

                if (addr, port) in existing:
                    continue
                if country_filter and p_country.upper() != country_filter.upper():
                    continue
                selected = p
                break

            if not selected:
                # Try without country filter
                for p in results:
                    if (p["proxy_address"], p["port"]) not in existing:
                        selected = p
                        break

            if not selected:
                raise RuntimeError(
                    "All Webshare proxies already in use. "
                    "Upgrade your plan or release unused proxies."
                )

            # Create local Proxy record
            proxy = Proxy(
                host=selected["proxy_address"],
                port=selected["port"],
                username=selected["username"],
                password=selected["password"],
                protocol=ProxyProtocol.SOCKS5,
                country=selected.get("country_code", ""),
                status=ProxyStatus.UNCHECKED
            )
            db.add(proxy)
            await db.commit()
            await db.refresh(proxy)

            logger.info(
                f"Provisioned proxy from Webshare: {proxy.host}:{proxy.port} "
                f"(country={proxy.country})"
            )
            return proxy

    async def release_proxy(self, proxy_id: uuid.UUID) -> bool:
        """Release/burn a proxy.

        1. Look up Proxy in DB
        2. Unlink from account
        3. If real mode: call Webshare replace API to get a fresh proxy in our pool
        4. Delete local Proxy record
        5. Return True on success
        """
        async with self.db_session_maker() as db:
            proxy = await db.get(Proxy, proxy_id)
            if not proxy:
                logger.warning(f"Proxy {proxy_id} not found for release")
                return False

            host = proxy.host
            port = proxy.port

            # Unlink from account
            account_result = await db.execute(
                select(Account).where(Account.proxy_id == proxy_id)
            )
            account = account_result.scalar_one_or_none()
            if account:
                account.proxy_id = None

            # Delete local record
            await db.delete(proxy)
            await db.commit()

            logger.info(f"Released proxy {host}:{port} (id={proxy_id})")

        # In real mode, tell Webshare to replace this proxy
        if not self.mock_mode:
            try:
                await self._replace_proxy(host, port)
                logger.info(f"Requested Webshare replacement for {host}:{port}")
            except Exception as e:
                logger.warning(
                    f"Failed to request Webshare replacement for {host}:{port}: {e}"
                )

        return True

    async def replace_proxy_for_account(self, account_id: uuid.UUID) -> Proxy:
        """Release old proxy and provision a new one for an account.

        Used when an account's issue is resolved and needs a fresh proxy.
        1. Release old proxy if any
        2. Provision new proxy
        3. Link to account
        4. Return new Proxy
        """
        async with self.db_session_maker() as db:
            account = await db.get(Account, account_id)
            if not account:
                raise ValueError(f"Account {account_id} not found")

            # Release old proxy
            if account.proxy_id:
                await self.release_proxy(account.proxy_id)

            # Provision new
            proxy = await self.provision_proxy()

            # Link to account
            account.proxy_id = proxy.id
            await db.commit()
            await db.refresh(account)

            logger.info(
                f"Replaced proxy for account {account.email}: "
                f"new proxy {proxy.host}:{proxy.port}"
            )
            return proxy
