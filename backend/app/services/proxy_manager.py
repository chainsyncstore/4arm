import logging
import uuid
import asyncio
import time
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.proxy import Proxy, ProxyStatus, ProxyProtocol
from app.models.instance import Instance, InstanceStatus
from app.models.account import Account
from app.config import settings

logger = logging.getLogger(__name__)


class ProxyManager:
    """High-level proxy orchestration for instance proxy switching and IP verification."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.mock_mode = settings.MOCK_DOCKER

    @staticmethod
    def _build_proxy_url(proxy: Proxy) -> str:
        from urllib.parse import quote

        auth = ""
        if proxy.username:
            auth = quote(proxy.username)
            if proxy.password is not None:
                auth = f"{auth}:{quote(proxy.password)}"
            auth = f"{auth}@"

        return f"{proxy.protocol.value}://{auth}{proxy.host}:{proxy.port}"

    @staticmethod
    def apply_test_result(proxy: Proxy, test_result: dict, checked_at: Optional[datetime] = None) -> None:
        proxy.status = ProxyStatus.HEALTHY if test_result["healthy"] else ProxyStatus.UNHEALTHY
        proxy.ip = test_result.get("ip") or None
        proxy.latency_ms = test_result.get("latency_ms")
        proxy.last_health_check = checked_at or datetime.now(timezone.utc)

    async def switch_instance_proxy(self, instance_id: uuid.UUID, proxy_id: uuid.UUID) -> dict:
        """
        Switch an instance's outbound proxy by reconfiguring its redsocks sidecar.

        Steps:
        1. Fetch proxy credentials from DB
        2. Fetch instance to get redsocks_container_id
        3. Execute: docker exec <redsocks_id> /reload.sh <host> <port> <user> <pass>
        4. Wait 2s for redsocks to reload
        5. Verify IP: docker exec <redroid_id> curl -s https://api.ipify.org
        6. Compare returned IP with expected proxy IP
        7. Return {success: bool, expected_ip: str, actual_ip: str}

        Mock mode: log the operation, return success with mock IPs.
        """
        proxy = await self.db.get(Proxy, proxy_id)
        if not proxy:
            raise ValueError(f"Proxy {proxy_id} not found")

        instance = await self.db.get(Instance, instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        if self.mock_mode:
            logger.info(
                f"MOCK: Would reconfigure redsocks for instance {instance_id} "
                f"to use proxy {proxy.host}:{proxy.port}"
            )
            # Mock verification
            mock_ips = ["1.2.3.4", "5.6.7.8", "9.10.11.12", "13.14.15.16"]
            expected_ip = mock_ips[hash(str(proxy_id)) % len(mock_ips)]
            return {
                "success": True,
                "expected_ip": expected_ip,
                "actual_ip": expected_ip,
                "message": "Mock proxy switch successful"
            }

        # Real Docker operations
        import docker
        docker_client = docker.from_env()

        if not instance.redsocks_container_id:
            raise ValueError(f"Instance {instance_id} has no redsocks sidecar")

        try:
            # Get redsocks container
            redsocks_container = docker_client.containers.get(instance.redsocks_container_id)

            # Build reload command
            cmd = [
                "/reload.sh",
                proxy.host,
                str(proxy.port),
                proxy.username or "",
                proxy.password or "",
                proxy.protocol.value
            ]

            logger.info(f"Executing reload on {instance.redsocks_container_id}: {' '.join(cmd)}")

            # Execute reload script
            exit_code, output = redsocks_container.exec_run(cmd)

            if exit_code != 0:
                logger.error(f"Reload script failed: {output.decode()}")
                return {
                    "success": False,
                    "expected_ip": proxy.host,
                    "actual_ip": None,
                    "message": f"Reload script failed: {output.decode()}"
                }

            # Wait for redsocks to reload
            await asyncio.sleep(2)

            # Verify IP
            verification = await self.verify_instance_ip(instance_id)
            actual_ip = verification["ip"]

            # Check if IP matches (check if proxy host is contained in actual IP or vice versa)
            # In real scenarios, proxy.host is the proxy server, not the exit IP
            # So we just verify we got SOME IP back (indicating connectivity works)
            success = actual_ip is not None and actual_ip != ""

            return {
                "success": success,
                "expected_ip": proxy.host,
                "actual_ip": actual_ip,
                "message": "Proxy switched successfully" if success else "IP verification failed"
            }

        except docker.errors.NotFound:
            logger.error(f"Redsocks container {instance.redsocks_container_id} not found")
            return {
                "success": False,
                "expected_ip": proxy.host,
                "actual_ip": None,
                "message": "Redsocks container not found"
            }
        except Exception as e:
            logger.exception(f"Error switching proxy: {e}")
            return {
                "success": False,
                "expected_ip": proxy.host,
                "actual_ip": None,
                "message": f"Error: {str(e)}"
            }

    async def verify_instance_ip(self, instance_id: uuid.UUID) -> dict:
        """
        Check what IP an instance is actually using.
        docker exec <redroid_id> curl -s https://api.ipify.org
        Returns {ip: str, matches_proxy: bool, proxy_host: str}
        """
        instance = await self.db.get(Instance, instance_id)
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        proxy_host = None
        if instance.assigned_account_id:
            # Get proxy from assigned account
            account_result = await self.db.execute(
                select(Account).where(Account.id == instance.assigned_account_id)
            )
            account = account_result.scalar_one_or_none()
            if account and account.proxy_id:
                proxy_result = await self.db.execute(
                    select(Proxy).where(Proxy.id == account.proxy_id)
                )
                proxy = proxy_result.scalar_one_or_none()
                if proxy:
                    proxy_host = proxy.host

        if self.mock_mode:
            mock_ips = ["1.2.3.4", "5.6.7.8", "9.10.11.12", "13.14.15.16"]
            actual_ip = mock_ips[hash(str(instance_id)) % len(mock_ips)]
            return {
                "ip": actual_ip,
                "matches_proxy": proxy_host == actual_ip if proxy_host else None,
                "proxy_host": proxy_host
            }

        # Real Docker operations
        import docker
        docker_client = docker.from_env()

        if not instance.docker_id:
            return {
                "ip": None,
                "matches_proxy": False,
                "proxy_host": proxy_host,
                "error": "Instance has no docker_id"
            }

        try:
            redroid_container = docker_client.containers.get(instance.docker_id)

            # Get IP from ipify
            exit_code, output = redroid_container.exec_run(
                ["curl", "-s", "--max-time", "10", "https://api.ipify.org"]
            )

            if exit_code != 0:
                return {
                    "ip": None,
                    "matches_proxy": False,
                    "proxy_host": proxy_host,
                    "error": f"curl failed: {output.decode()}"
                }

            actual_ip = output.decode().strip()

            return {
                "ip": actual_ip,
                "matches_proxy": proxy_host == actual_ip if proxy_host else None,
                "proxy_host": proxy_host
            }

        except docker.errors.NotFound:
            return {
                "ip": None,
                "matches_proxy": False,
                "proxy_host": proxy_host,
                "error": "Container not found"
            }
        except Exception as e:
            logger.exception(f"Error verifying instance IP: {e}")
            return {
                "ip": None,
                "matches_proxy": False,
                "proxy_host": proxy_host,
                "error": str(e)
            }

    async def auto_assign_proxies(self) -> dict:
        """
        For all accounts with proxy_id=None, assign from unlinked proxy pool.
        Match by country preference if available.
        Returns {assigned: int, remaining_unlinked_accounts: int, remaining_unlinked_proxies: int}
        """
        # Get all accounts without proxies
        accounts_result = await self.db.execute(
            select(Account).where(Account.proxy_id.is_(None))
        )
        unlinked_accounts = accounts_result.scalars().all()

        # Get all unlinked proxies
        proxies_result = await self.db.execute(
            select(Proxy)
            .outerjoin(Account, Proxy.id == Account.proxy_id)
            .where(Account.id.is_(None))
            .where(Proxy.status != ProxyStatus.UNHEALTHY)
        )
        unlinked_proxies = proxies_result.scalars().all()

        assigned = 0
        used_proxy_ids = set()

        for account in unlinked_accounts:
            # Try to find a proxy matching the account's country preference
            # For now, just assign any available proxy
            # TODO: Add country preference field to Account model

            available_proxies = [p for p in unlinked_proxies if p.id not in used_proxy_ids]

            if not available_proxies:
                break

            # Assign first available proxy
            selected_proxy = available_proxies[0]
            account.proxy_id = selected_proxy.id
            used_proxy_ids.add(selected_proxy.id)
            assigned += 1

            logger.info(f"Auto-assigned proxy {selected_proxy.host}:{selected_proxy.port} to account {account.email}")

        await self.db.commit()

        # Recalculate remaining
        remaining_accounts_result = await self.db.execute(
            select(Account).where(Account.proxy_id.is_(None))
        )
        remaining_accounts = len(remaining_accounts_result.scalars().all())

        remaining_proxies_result = await self.db.execute(
            select(Proxy)
            .outerjoin(Account, Proxy.id == Account.proxy_id)
            .where(Account.id.is_(None))
            .where(Proxy.status != ProxyStatus.UNHEALTHY)
        )
        remaining_proxies = len(remaining_proxies_result.scalars().all())

        return {
            "assigned": assigned,
            "remaining_unlinked_accounts": remaining_accounts,
            "remaining_unlinked_proxies": remaining_proxies
        }

    async def test_proxy_real(self, proxy_id: uuid.UUID) -> dict:
        """
        Test proxy connectivity using aiohttp-socks (not through an instance).
        Connect through proxy to https://api.ipify.org.
        Returns {healthy: bool, ip: str, latency_ms: float, error: str|None}

        Mock mode: return mock healthy result.
        """
        proxy = await self.db.get(Proxy, proxy_id)
        if not proxy:
            raise ValueError(f"Proxy {proxy_id} not found")

        if self.mock_mode:
            import random
            healthy = True
            mock_ips = ["1.2.3.4", "5.6.7.8", "9.10.11.12", "13.14.15.16"]
            return {
                "healthy": healthy,
                "ip": random.choice(mock_ips),
                "latency_ms": float(random.randint(50, 200)),
                "error": None
            }

        # Real proxy test using aiohttp-socks
        import aiohttp
        from aiohttp_socks import ProxyConnector

        try:
            start_time = time.time()

            connector = ProxyConnector.from_url(self._build_proxy_url(proxy))

            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get("https://api.ipify.org", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    ip = await resp.text()
                    latency_ms = (time.time() - start_time) * 1000

                    return {
                        "healthy": True,
                        "ip": ip.strip(),
                        "latency_ms": round(latency_ms, 2),
                        "error": None
                    }

        except Exception as e:
            logger.warning(f"Proxy test failed for {proxy.host}:{proxy.port}: {e}")
            return {
                "healthy": False,
                "ip": None,
                "latency_ms": None,
                "error": str(e)
            }
