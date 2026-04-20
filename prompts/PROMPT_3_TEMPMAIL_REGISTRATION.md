# SUB-AGENT PROMPT 3 — Temporary Mail + Auto-Registration

You are working on a Spotify streaming farm management system called **4ARM**.  
Your task is to integrate a disposable email provider and build an end-to-end automated Spotify account registration flow. Every auto-created account must be marked as **free** type.

**Do NOT create new files unless explicitly instructed. Prefer editing existing files.**

---

## CONTEXT — Existing Code You Must Know

### Backend config
**File: `backend/app/config.py`**
```python
class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://..."
    MOCK_DOCKER: bool = True
    MOCK_ADB: bool = True
    SECRET_KEY: str = "change-me-in-production"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    # ... other fields
```
You will add new config fields here.

### Account model
**File: `backend/app/models/account.py`**
- `Account` has: `email`, `password_hash`, `password_plain` (added by Prompt 1), `display_name`, `type` (FREE/PREMIUM), `status` (NEW/WARMING/ACTIVE/COOLDOWN/BANNED), `proxy_id` (FK to proxies), etc.
- `AccountType.FREE` and `AccountType.PREMIUM` enums
- `AccountStatus.NEW` is the default

### Account service
**File: `backend/app/services/account_service.py`**
- `AccountService.create_account(data: AccountCreate)` — creates an account with email, type, proxy_id, password_plain
- `AccountService.import_accounts_from_csv(csv_content)` — bulk import

### Account schema
**File: `backend/app/schemas/account.py`**
- `AccountCreate`: `email`, `display_name`, `type` (default FREE), `password` (optional), `proxy_id` (optional)

### ADB service
**File: `backend/app/services/adb_service.py`**
- `ADBService` with methods: `launch_app()`, `tap()`, `swipe()`, `input_text()`, `key_event()`, `get_screen_xml()`
- Has `self.mock_mode` flag

### Spotify controller
**File: `backend/app/services/automation/spotify_controller.py`**
- `SpotifyController` wraps ADB interactions with Spotify app
- Has `self.mock_mode` flag
- Has `launch_spotify()`, `play_track_premium()`, `play_track_free()`, `detect_challenge()` (added by Prompt 2)

### Account router
**File: `backend/app/routers/accounts.py`**
- Has a placeholder endpoint at line 186-193:
```python
@router.post("/create-batch")
async def create_batch(
    count: int = Query(..., ge=1, le=10),
    service: AccountService = Depends(get_account_service)
) -> dict:
    """Batch create accounts (placeholder - Phase 1.5 implementation)."""
    return {"message": "Batch account creation - Phase 1.5 feature", "requested": count}
```
This will be replaced.

### Settings model
**File: `backend/app/routers/settings.py`**
- Settings like `creation_delay_min_sec`, `creation_delay_max_sec`, `daily_account_creation_cap` already exist as seeded defaults

### Main entry
**File: `backend/app/main.py`**
- Services initialized in `lifespan()` (lines 64-170)
- Routers included at lines 194-205
- Global service references declared at lines 51-61

### Frontend Accounts page
**File: `frontend/src/pages/Accounts.tsx`**
- Already has import/batch UI (being overhauled by Prompt 1)
- The "Create Batch" button exists but calls a placeholder endpoint

### Frontend API
**File: `frontend/src/api/accounts.ts`**
- `createBatch: async (count: number) => apiClient.post('/accounts/create-batch', null, { params: { count } })`
- This needs to be updated to call the new registration endpoint

---

## PART A — Temp Mail Provider: mail.tm

**Why mail.tm**: Free REST API, no API key required, disposable domains, supports programmatic mailbox creation and message retrieval. Varied domains available.

**Create new file: `backend/app/services/tempmail_service.py`**

```python
"""Temporary email service using mail.tm API for disposable mailboxes."""

import asyncio
import logging
import random
import string
import re
from typing import Optional
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


class TempMailService:
    """Wraps mail.tm REST API for disposable email management."""

    BASE_URL = "https://api.mail.tm"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_available_domains(self) -> list[str]:
        """Fetch available email domains from mail.tm.
        GET https://api.mail.tm/domains
        Returns list of domain strings like ['mail.tm', 'inbox.fr', ...]
        """
        client = await self._get_client()
        resp = await client.get(f"{self.BASE_URL}/domains")
        resp.raise_for_status()
        data = resp.json()
        # API returns {"hydra:member": [{"domain": "...", ...}, ...]}
        members = data.get("hydra:member", [])
        return [m["domain"] for m in members if m.get("isActive", True)]

    def _random_local_part(self, length: int = 10) -> str:
        """Generate random local part for email: lowercase + digits."""
        chars = string.ascii_lowercase + string.digits
        return ''.join(random.choices(chars, k=length))

    async def create_mailbox(self, address: str = None, password: str = None) -> dict:
        """Create a disposable mailbox.

        If address is None, generates random address using an available domain.
        If password is None, generates random 12-char password.

        Returns: {
            "id": str,          # mail.tm account ID
            "address": str,     # full email address
            "password": str,    # mailbox password
            "token": str        # JWT for reading messages
        }
        """
        client = await self._get_client()

        # Get a domain if no address given
        if not address:
            domains = await self.get_available_domains()
            if not domains:
                raise RuntimeError("No mail.tm domains available")
            domain = random.choice(domains)
            local = self._random_local_part()
            address = f"{local}@{domain}"

        if not password:
            password = ''.join(random.choices(
                string.ascii_letters + string.digits, k=12
            ))

        # Create account
        create_resp = await client.post(
            f"{self.BASE_URL}/accounts",
            json={"address": address, "password": password}
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create mailbox: {create_resp.status_code} {create_resp.text}"
            )
        account_data = create_resp.json()

        # Get auth token
        token_resp = await client.post(
            f"{self.BASE_URL}/token",
            json={"address": address, "password": password}
        )
        if token_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to get mail token: {token_resp.status_code} {token_resp.text}"
            )
        token = token_resp.json().get("token", "")

        logger.info(f"Created temp mailbox: {address}")

        return {
            "id": account_data.get("id", ""),
            "address": address,
            "password": password,
            "token": token
        }

    async def get_messages(self, token: str) -> list[dict]:
        """List messages in inbox.
        GET https://api.mail.tm/messages with Bearer token
        """
        client = await self._get_client()
        resp = await client.get(
            f"{self.BASE_URL}/messages",
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("hydra:member", [])

    async def get_message(self, token: str, message_id: str) -> dict:
        """Get full message content.
        GET https://api.mail.tm/messages/{id}
        """
        client = await self._get_client()
        resp = await client.get(
            f"{self.BASE_URL}/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json()

    def extract_otp(self, message_body: str) -> Optional[str]:
        """Extract 6-digit OTP from message text/HTML."""
        match = re.search(r'\b(\d{6})\b', message_body)
        return match.group(1) if match else None

    def extract_verification_link(self, message_body: str) -> Optional[str]:
        """Extract Spotify verification/confirmation link from message."""
        patterns = [
            r'https?://[^\s"<>]*spotify[^\s"<>]*confirm[^\s"<>]*',
            r'https?://[^\s"<>]*spotify[^\s"<>]*verify[^\s"<>]*',
            r'https?://[^\s"<>]*spotify[^\s"<>]*activate[^\s"<>]*',
        ]
        for pattern in patterns:
            match = re.search(pattern, message_body, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    async def wait_for_message(
        self,
        token: str,
        from_contains: str = "spotify",
        timeout_sec: int = 120,
        poll_interval_sec: int = 5
    ) -> Optional[dict]:
        """Poll inbox until a message from a matching sender arrives or timeout.

        Args:
            token: Bearer token for mailbox
            from_contains: substring to match in sender address (case-insensitive)
            timeout_sec: max seconds to wait
            poll_interval_sec: seconds between polls

        Returns: Full message dict or None if timeout
        """
        deadline = asyncio.get_event_loop().time() + timeout_sec

        while asyncio.get_event_loop().time() < deadline:
            try:
                messages = await self.get_messages(token)
                for msg in messages:
                    sender = msg.get("from", {}).get("address", "")
                    if from_contains.lower() in sender.lower():
                        # Fetch full message
                        full = await self.get_message(token, msg["id"])
                        return full
            except Exception as e:
                logger.warning(f"Error polling mailbox: {e}")

            await asyncio.sleep(poll_interval_sec)

        logger.warning(f"Timed out waiting for message from '{from_contains}'")
        return None
```

---

## PART B — Registration Service

**Create new file: `backend/app/services/registration_service.py`**

```python
"""Automated Spotify account registration using temp mail + ADB."""

import asyncio
import logging
import random
import string
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType, AccountStatus
from app.schemas.account import AccountCreate
from app.services.tempmail_service import TempMailService
from app.services.adb_service import ADBService
from app.services.automation.spotify_controller import SpotifyController
from app.services.alerting import AlertingService, AlertSeverity
from app.config import settings

logger = logging.getLogger(__name__)


class RegistrationService:
    """End-to-end Spotify account registration."""

    def __init__(
        self,
        tempmail: TempMailService,
        adb: ADBService,
        spotify: SpotifyController,
        db_session_maker,
        alerting: Optional[AlertingService] = None,
        proxy_provider=None  # Will be wired in Prompt 4
    ):
        self.tempmail = tempmail
        self.adb = adb
        self.spotify = spotify
        self.db_session_maker = db_session_maker
        self.alerting = alerting
        self.proxy_provider = proxy_provider
        self.mock_mode = settings.MOCK_ADB

    def _random_password(self, length: int = 14) -> str:
        """Generate a random Spotify-compatible password."""
        chars = string.ascii_letters + string.digits + "!@#$%"
        return ''.join(random.choices(chars, k=length))

    def _random_display_name(self) -> str:
        """Generate a plausible display name."""
        first_names = [
            "Alex", "Jordan", "Sam", "Chris", "Morgan", "Taylor", "Casey",
            "Riley", "Quinn", "Avery", "Jamie", "Drew", "Skyler", "Dakota"
        ]
        last_initials = list(string.ascii_uppercase)
        return f"{random.choice(first_names)} {random.choice(last_initials)}."

    def _random_dob(self) -> dict:
        """Generate random date of birth (age 18-35)."""
        year = random.randint(datetime.now().year - 35, datetime.now().year - 18)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        return {"year": year, "month": month, "day": day}

    async def register_account(
        self,
        db: AsyncSession,
        instance_id: Optional[UUID] = None,
        device_id: Optional[str] = None
    ) -> Account:
        """Full automated registration flow.

        Steps:
        1. Create temp mailbox via mail.tm
        2. Generate Spotify password + display name
        3. (Real mode) Drive Spotify signup via ADB on target instance
        4. Wait for verification email
        5. Extract OTP or verification link
        6. (Real mode) Complete verification via ADB
        7. Create Account record in DB (type=FREE, status=NEW)
        8. Return Account

        In mock mode: skips ADB steps, simulates the flow with delays.
        """
        logger.info("Starting automated account registration...")

        # Step 1: Create temp mailbox
        try:
            mailbox = await self.tempmail.create_mailbox()
        except Exception as e:
            logger.error(f"Failed to create temp mailbox: {e}")
            raise RuntimeError(f"Temp mail creation failed: {e}")

        email = mailbox["address"]
        mail_token = mailbox["token"]
        spotify_password = self._random_password()
        display_name = self._random_display_name()
        dob = self._random_dob()

        logger.info(f"Temp mailbox created: {email}")

        if self.mock_mode:
            # Simulate registration with delays
            logger.info(f"MOCK: Registering {email} on Spotify (simulated)")
            await asyncio.sleep(random.uniform(2, 5))
            logger.info(f"MOCK: Registration form submitted for {email}")
            await asyncio.sleep(random.uniform(1, 3))
            logger.info(f"MOCK: Verification completed for {email}")
        else:
            # Real ADB-driven registration
            if not device_id:
                raise RuntimeError("device_id required for real registration")

            # Open Spotify signup page
            # This would involve detailed ADB UI automation:
            # - Launch Spotify
            # - Navigate to Sign Up
            # - Fill email, password, DOB, display name
            # - Submit form
            # - Wait for and handle verification

            # Placeholder for real implementation:
            await self.spotify.launch_spotify(device_id)
            await asyncio.sleep(3)
            # ... detailed ADB taps/inputs would go here ...

            # Wait for verification email
            logger.info(f"Waiting for Spotify verification email at {email}...")
            message = await self.tempmail.wait_for_message(
                token=mail_token,
                from_contains="spotify",
                timeout_sec=120
            )

            if message:
                body = message.get("text", "") or message.get("html", [""])[0]

                otp = self.tempmail.extract_otp(body)
                link = self.tempmail.extract_verification_link(body)

                if otp:
                    logger.info(f"OTP extracted: {otp}")
                    # Enter OTP via ADB
                    # await self.adb.input_text(device_id, otp)
                elif link:
                    logger.info(f"Verification link extracted: {link}")
                    # Click link via ADB browser or HTTP
                    # await self.adb.launch_url(device_id, link)
                else:
                    logger.warning("No OTP or link found in verification email")
            else:
                logger.warning(f"No verification email received for {email}")
                if self.alerting:
                    await self.alerting.send_alert(
                        severity=AlertSeverity.WARNING,
                        title="Registration: No verification email",
                        message=f"Account {email} did not receive verification email within timeout."
                    )

        # Step 7: Create Account in DB
        account = Account(
            email=email,
            password_plain=spotify_password,
            display_name=display_name,
            type=AccountType.FREE,  # Always FREE for auto-created accounts
            status=AccountStatus.NEW,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)

        logger.info(f"Account registered: {email} (id={account.id})")

        # Alert success
        if self.alerting:
            await self.alerting.send_alert(
                severity=AlertSeverity.INFO,
                title="Account registered",
                message=f"Auto-registered: {email}",
                db=db
            )

        return account

    async def register_batch(
        self,
        db: AsyncSession,
        count: int,
        instance_ids: Optional[list[UUID]] = None
    ) -> dict:
        """Register multiple accounts with delays between each.

        Respects settings: daily_account_creation_cap, creation_delay_min_sec,
        creation_delay_max_sec.

        Returns: {"registered": int, "failed": int, "accounts": [account_ids]}
        """
        from app.models.setting import Setting
        from sqlalchemy import select

        # Read settings
        async def get_setting(key: str, default: int) -> int:
            result = await db.execute(select(Setting).where(Setting.key == key))
            setting = result.scalar_one_or_none()
            return int(setting.value) if setting else default

        daily_cap = await get_setting("daily_account_creation_cap", 20)
        delay_min = await get_setting("creation_delay_min_sec", 30)
        delay_max = await get_setting("creation_delay_max_sec", 120)

        # Respect cap
        actual_count = min(count, daily_cap)
        if actual_count < count:
            logger.warning(
                f"Requested {count} registrations but daily cap is {daily_cap}, "
                f"creating {actual_count}"
            )

        registered = 0
        failed = 0
        account_ids = []

        for i in range(actual_count):
            try:
                logger.info(f"Registering account {i + 1}/{actual_count}...")
                account = await self.register_account(db)

                # Auto-provision proxy if provider available (wired in Prompt 4)
                if self.proxy_provider:
                    try:
                        proxy = await self.proxy_provider.provision_proxy()
                        account.proxy_id = proxy.id
                        await db.commit()
                        logger.info(f"Proxy provisioned for {account.email}: {proxy.id}")
                    except Exception as e:
                        logger.warning(f"Failed to provision proxy for {account.email}: {e}")

                registered += 1
                account_ids.append(str(account.id))

            except Exception as e:
                logger.error(f"Registration {i + 1}/{actual_count} failed: {e}")
                failed += 1

            # Delay between registrations (except last)
            if i < actual_count - 1:
                delay = random.randint(delay_min, delay_max)
                logger.info(f"Waiting {delay}s before next registration...")
                await asyncio.sleep(delay)

        return {
            "registered": registered,
            "failed": failed,
            "accounts": account_ids,
            "capped_at": actual_count if actual_count < count else None
        }
```

---

## PART C — Backend Config Additions

**File: `backend/app/config.py`**

Add these fields to the `Settings` class (after the existing `CLUSTER_ENABLED` field):

```python
# Phase 8: Auto-registration
TEMPMAIL_ENABLED: bool = True
REGISTRATION_MOCK: bool = True  # If True, skip real ADB steps during registration
```

---

## PART D — Backend Router: Replace Batch Endpoint

**File: `backend/app/routers/accounts.py`**

Replace the placeholder `create-batch` endpoint (lines 186-193) with a real registration endpoint:

```python
@router.post("/register")
async def register_accounts(
    count: int = Query(1, ge=1, le=10),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Auto-register new Spotify accounts using temp mail.
    Each account is created as type=FREE.
    """
    from app.services.registration_service import RegistrationService
    from app.services.tempmail_service import TempMailService
    from app.services.adb_service import ADBService
    from app.services.automation.spotify_controller import SpotifyController

    tempmail = TempMailService()
    adb = ADBService()
    spotify = SpotifyController(adb)
    reg_service = RegistrationService(
        tempmail=tempmail,
        adb=adb,
        spotify=spotify,
        db_session_maker=None,
        alerting=None  # Could wire global alerting_service here
    )

    try:
        result = await reg_service.register_batch(db=db, count=count)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    finally:
        await tempmail.close()
```

Also keep the old endpoint for backwards compat but redirect:
```python
@router.post("/create-batch")
async def create_batch(
    count: int = Query(1, ge=1, le=10),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Alias for register endpoint."""
    return await register_accounts(count=count, db=db)
```

---

## PART E — Frontend: Update API & Accounts Page

**File: `frontend/src/api/accounts.ts`**

Update the `createBatch` method to call the new endpoint:
```typescript
register: async (count: number) => {
  return apiClient.post<{ registered: number; failed: number; accounts: string[] }>(
    '/accounts/register',
    null,
    { params: { count } }
  )
},
```

Keep the old `createBatch` as an alias if needed, or remove it.

**File: `frontend/src/hooks/useAccounts.ts`**

Update `useCreateBatchAccounts` to use the new method name:
```typescript
export function useRegisterAccounts() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (count: number) => accountsApi.register(count),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [ACCOUNTS_KEY] })
    },
  })
}
```

**File: `frontend/src/pages/Accounts.tsx`**

Update the "Create Batch" button section (if it exists after Prompt 1 overhaul) to become "Register Accounts":
- Button label: "Register New"
- Dialog title: "Register New Accounts"
- Dialog description: "Auto-create Spotify accounts using temporary emails. All accounts are created as Free type."
- Number input: 1-10
- On submit: call `useRegisterAccounts().mutateAsync(count)`
- Toast: "Registering {count} accounts..." (since this is async/long-running)
- On success toast: "{result.registered} accounts registered, {result.failed} failed"

---

## PART F — Add httpx dependency

**File: `backend/requirements.txt`** (or equivalent)

Ensure `httpx` is listed as a dependency. Check if it already exists (it's used in `alerting.py`). If not present, add:
```
httpx>=0.24.0
```

---

## Acceptance Criteria

1. `TempMailService` can create mailboxes and retrieve messages from mail.tm API
2. `RegistrationService.register_account()` creates a temp mailbox, simulates registration (mock mode), and creates an Account record with `type=FREE` and `password_plain` set
3. `RegistrationService.register_batch()` respects daily cap and inter-registration delays
4. `POST /api/accounts/register?count=3` triggers registration and returns `{"registered": N, "failed": N, "accounts": [...]}`
5. All auto-created accounts have `type=FREE`
6. Frontend "Register New" button triggers the registration flow
7. Success/failure toasts display correctly
8. No import errors, no runtime crashes, no broken existing functionality
9. `TempMailService` is properly closed after use (no connection leaks)
10. The `create-batch` endpoint still works (aliased to register)
