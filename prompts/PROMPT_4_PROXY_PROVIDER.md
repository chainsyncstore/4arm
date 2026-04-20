# SUB-AGENT PROMPT 4 — Proxy Provider API (Dynamic Provisioning & Burn)

You are working on a Spotify streaming farm management system called **4ARM**.  
Your task is to integrate a proxy provider API so that proxies are **provisioned dynamically** (not added manually). A new proxy is spun up for every account added. When an account is deleted, removed, or banned, its proxy is **burned** (released). If an account's issue is resolved, a fresh proxy can be spun.

**Do NOT create new files unless explicitly instructed. Prefer editing existing files.**

---

## CONTEXT — Existing Code You Must Know

### Proxy model
**File: `backend/app/models/proxy.py`**
```python
class ProxyProtocol(str, enum.Enum):
    SOCKS5 = "socks5"
    HTTP = "http"
    HTTPS = "https"

class ProxyStatus(str, enum.Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNCHECKED = "unchecked"

class Proxy(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "proxies"
    host, port, username, password, protocol, country, status, last_health_check, uptime_pct
    account: 1:1 relationship with Account
```

### Account model
**File: `backend/app/models/account.py`**
```python
class Account(Base, TimestampMixin, UUIDMixin):
    proxy_id: FK → proxies.id (unique=True, nullable=True)
    status: AccountStatus (NEW, WARMING, ACTIVE, COOLDOWN, BANNED)
    # ... other fields
```

### Account service
**File: `backend/app/services/account_service.py`**
- `create_account(data)` — creates account, sets `proxy_id` if provided in data
- `delete_account(account_id)` — deletes account (currently does NOT handle proxy cleanup)
- `import_accounts_from_csv(csv_content)` — bulk creates accounts from CSV

### Proxy service
**File: `backend/app/services/proxy_service.py`**
- `create_proxy(data: ProxyCreate)` — creates a proxy record manually
- `delete_proxy(proxy_id)` — deletes proxy, unlinks from account first
- `test_proxy(proxy_id)` — tests connectivity (mock mode returns random result)
- `get_unlinked_proxies()` — gets proxies not assigned to any account

### Proxy manager
**File: `backend/app/services/proxy_manager.py`**
- `auto_assign_proxies()` — bulk-assigns unlinked proxies to unlinked accounts
- `switch_instance_proxy()` — reconfigures redsocks container for an instance
- `verify_instance_ip()` — checks what IP an instance is using

### Account router
**File: `backend/app/routers/accounts.py`**
- `DELETE /api/accounts/{account_id}` — calls `service.delete_account()`
- `POST /api/accounts/{account_id}/link-proxy` — links a proxy to an account
- Routes at `/api/accounts/...`

### Proxy router  
**File: `backend/app/routers/proxies.py`** — standard CRUD for proxies

### Config
**File: `backend/app/config.py`**
```python
class Settings(BaseSettings):
    MOCK_DOCKER: bool = True
    MOCK_ADB: bool = True
    # You will add proxy provider settings here
```

### Main
**File: `backend/app/main.py`**
- Global service instances declared at lines 51-61
- Services initialized in `lifespan()` at lines 64-170
- The proxy_provider service needs to be initialized here and injected

---

## PROVIDER CHOICE: Webshare.io

**Why Webshare**: 
- REST API for proxy management
- Datacenter proxies at ~$0.05-0.10/proxy
- SOCKS5 + HTTP support
- API key authentication
- 10 free proxies on signup for testing
- Endpoint: `https://proxy.webshare.io/api/v2`

**How Webshare works**:
- You purchase a proxy plan (e.g., 100 datacenter proxies)
- `GET /proxy/list/` returns your allocated proxies (host, port, username, password)
- Proxies are from a pool; "burning" means removing from your active list and getting a replacement
- `POST /proxy/config/` to manage proxy list configuration
- Authentication via `Token <API_KEY>` header

---

## PART A — Config

**File: `backend/app/config.py`**

Add these fields to the `Settings` class:

```python
# Phase 8: Proxy provider
PROXY_PROVIDER: str = "webshare"  # "webshare" or "manual" (manual = legacy behavior)
WEBSHARE_API_KEY: str = ""
PROXY_COUNTRY: str = ""  # Default country code (e.g., "US"), empty = any
PROXY_AUTO_PROVISION: bool = True  # Auto-provision on account creation
```

---

## PART B — Proxy Provider Service

**Create new file: `backend/app/services/proxy_provider.py`**

```python
"""Dynamic proxy provisioning via Webshare.io API."""

import logging
import uuid
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
            import random
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
```

---

## PART C — Wire Into Account Lifecycle

### Delete account burns proxy
**File: `backend/app/services/account_service.py`**

Modify `delete_account()` method. Currently it just deletes the account. Change it to also burn the proxy:

Current code (around line 158-170):
```python
async def delete_account(self, account_id: uuid.UUID) -> bool:
    result = await self.db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise ValueError(f"Account {account_id} not found")
    await self.db.delete(account)
    await self.db.commit()
    ...
```

Change to:
```python
async def delete_account(self, account_id: uuid.UUID, proxy_provider=None) -> bool:
    result = await self.db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise ValueError(f"Account {account_id} not found")

    # Burn proxy if provider is configured
    proxy_id_to_burn = account.proxy_id
    
    await self.db.delete(account)
    await self.db.commit()
    
    if proxy_id_to_burn and proxy_provider:
        try:
            await proxy_provider.release_proxy(proxy_id_to_burn)
            logger.info(f"Burned proxy {proxy_id_to_burn} for deleted account {account.email}")
        except Exception as e:
            logger.warning(f"Failed to burn proxy {proxy_id_to_burn}: {e}")
    
    logger.info(f"Deleted account {account.email}")
    return True
```

### Create account auto-provisions proxy
**File: `backend/app/services/account_service.py`**

Modify `create_account()`. Currently:
```python
async def create_account(self, data: AccountCreate) -> Account:
    account = Account(email=str(data.email), ...)
    self.db.add(account)
    await self.db.commit()
    ...
```

Change to accept optional proxy_provider:
```python
async def create_account(self, data: AccountCreate, proxy_provider=None) -> Account:
    account = Account(
        email=str(data.email),
        display_name=data.display_name,
        type=data.type,
        proxy_id=data.proxy_id,
        status=AccountStatus.NEW
    )
    if hasattr(data, 'password') and data.password:
        account.password_plain = data.password

    self.db.add(account)
    await self.db.commit()
    await self.db.refresh(account)

    # Auto-provision proxy if no proxy was provided and provider is available
    if not account.proxy_id and proxy_provider:
        try:
            proxy = await proxy_provider.provision_proxy()
            account.proxy_id = proxy.id
            await self.db.commit()
            await self.db.refresh(account)
            logger.info(f"Auto-provisioned proxy {proxy.host}:{proxy.port} for {account.email}")
        except Exception as e:
            logger.warning(f"Failed to auto-provision proxy for {account.email}: {e}")

    logger.info(f"Created account {account.email}")
    return account
```

### CSV import auto-provisions proxies
Modify `import_accounts_from_csv()` similarly — add `proxy_provider=None` param. After bulk commit, loop through accounts and provision:
```python
async def import_accounts_from_csv(self, csv_content: str, proxy_provider=None) -> list[Account]:
    # ... existing CSV parsing and account creation ...
    
    await self.db.commit()
    for acc in accounts:
        await self.db.refresh(acc)

    # Auto-provision proxies for imported accounts
    if proxy_provider:
        for acc in accounts:
            if not acc.proxy_id:
                try:
                    proxy = await proxy_provider.provision_proxy()
                    acc.proxy_id = proxy.id
                except Exception as e:
                    logger.warning(f"Failed to auto-provision proxy for {acc.email}: {e}")
        await self.db.commit()

    logger.info(f"Imported {len(accounts)} accounts from CSV")
    return accounts
```

---

## PART D — Wire Into Account Router

**File: `backend/app/routers/accounts.py`**

The router needs access to the global proxy_provider. Add at the top of the file:

```python
from typing import Optional
# ... existing imports ...

# Global proxy provider reference (set during startup)
_proxy_provider = None

def set_proxy_provider(provider):
    global _proxy_provider
    _proxy_provider = provider
```

Then update these endpoints:

### `create_account` endpoint:
```python
account = await service.create_account(data, proxy_provider=_proxy_provider)
```

### `import_accounts` endpoint:
```python
accounts = await service.import_accounts_from_csv(csv_content, proxy_provider=_proxy_provider)
```

### `delete_account` endpoint:
```python
await service.delete_account(account_id, proxy_provider=_proxy_provider)
```

### Add new endpoint for replacing proxy:
```python
@router.post("/{account_id}/replace-proxy")
async def replace_proxy(
    account_id: uuid.UUID,
    service: AccountService = Depends(get_account_service)
) -> dict:
    """Release current proxy and provision a fresh one for the account."""
    if not _proxy_provider:
        raise HTTPException(status_code=503, detail="Proxy provider not configured")
    try:
        proxy = await _proxy_provider.replace_proxy_for_account(account_id)
        return {
            "message": "Proxy replaced",
            "proxy_id": str(proxy.id),
            "host": proxy.host,
            "port": proxy.port
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
```

### Add provider status endpoint to proxies router:
**File: `backend/app/routers/proxies.py`**

Add endpoint:
```python
@router.get("/provider/status")
async def proxy_provider_status() -> dict:
    """Get proxy provider connection status and quota."""
    if not _proxy_provider:
        return {"connected": False, "provider": "manual", "message": "No provider configured"}
    return await _proxy_provider.get_provider_status()
```

You'll need to add a similar `_proxy_provider` global + `set_proxy_provider()` to the proxies router, or import from accounts router.

---

## PART E — Initialize in main.py

**File: `backend/app/main.py`**

In the global declarations section (around line 51-61), add:
```python
proxy_provider: ProxyProviderService | None = None
```

In the `lifespan()` function, after the existing service initializations (before `yield`), add:
```python
# Initialize proxy provider
from app.services.proxy_provider import ProxyProviderService
global proxy_provider

if settings.WEBSHARE_API_KEY or settings.PROXY_AUTO_PROVISION:
    proxy_provider = ProxyProviderService(
        api_key=settings.WEBSHARE_API_KEY,
        db_session_maker=async_session_maker
    )
    logger.info(f"ProxyProviderService initialized (mock={proxy_provider.mock_mode})")

    # Set on routers
    from app.routers.accounts import set_proxy_provider as set_accounts_proxy
    set_accounts_proxy(proxy_provider)
else:
    logger.info("Proxy auto-provisioning disabled (no WEBSHARE_API_KEY)")
```

Add `proxy_provider` to the `global` statement in `lifespan()` (line 67).

---

## PART F — Frontend Changes

### Types
**File: `frontend/src/types/index.ts`**

The `Account` interface should already have `proxy_host?: string` and `proxy_port?: number` (from Prompt 1). No additional changes needed.

Add a new type:
```typescript
export interface ProxyProviderStatus {
  connected: boolean
  provider: string
  total_proxies?: number
  used_proxies?: number
  available?: number
  error?: string
}
```

### API
**File: `frontend/src/api/accounts.ts`**

Add method:
```typescript
replaceProxy: async (accountId: string) => {
  return apiClient.post<{ message: string; proxy_id: string; host: string; port: number }>(
    `/accounts/${accountId}/replace-proxy`
  )
},
```

**File: `frontend/src/api/proxies.ts`** (find and edit this file)

Add method:
```typescript
getProviderStatus: async () => {
  return apiClient.get<ProxyProviderStatus>('/proxies/provider/status')
},
```

### Accounts page
**File: `frontend/src/pages/Accounts.tsx`** (after Prompt 1 overhaul)

In the Actions column per row, add a "Replace Proxy" button (use `RefreshCw` icon from lucide-react) that:
- Is only visible if the account has a proxy linked
- On click, calls `accountsApi.replaceProxy(account.id)`
- Shows toast on success/failure
- Refetches account list

### Proxies page
**File: `frontend/src/pages/Proxies.tsx`**

At the top of the page, add a provider status banner:
- Fetch from `proxiesApi.getProviderStatus()` on mount
- Show: "Provider: {provider} | Status: Connected/Disconnected | Available: {available}/{total}"
- If `connected: false`, show warning banner
- If provider is "manual", show info: "Proxies are managed manually. Configure WEBSHARE_API_KEY to enable auto-provisioning."

---

## Acceptance Criteria

1. `ProxyProviderService.provision_proxy()` creates a Proxy record (mock mode: fake data; real mode: from Webshare API)
2. `ProxyProviderService.release_proxy(proxy_id)` deletes the Proxy record and unlinks from account
3. `ProxyProviderService.replace_proxy_for_account(account_id)` releases old + provisions new
4. Creating an account via `POST /api/accounts/` auto-provisions a proxy
5. Importing accounts via CSV auto-provisions proxies for each account
6. Deleting an account via `DELETE /api/accounts/{id}` burns its proxy
7. `POST /api/accounts/{id}/replace-proxy` replaces the proxy
8. `GET /api/proxies/provider/status` returns provider status
9. Frontend shows "Replace Proxy" action per account row
10. Frontend Proxies page shows provider status banner
11. All operations work in mock mode (no Webshare API key needed for testing)
12. No import errors, no runtime crashes, no broken existing functionality
