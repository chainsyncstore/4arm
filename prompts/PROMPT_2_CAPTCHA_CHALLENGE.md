# SUB-AGENT PROMPT 2 — CAPTCHA / Challenge Bypass Flow

You are working on a Spotify streaming farm management system called **4ARM**.  
Your task is to build a challenge detection and manual resolution system. When the stream worker detects a CAPTCHA or verification screen on an Android instance, the system should:
1. Pause that instance's streaming
2. Take a screenshot
3. Alert the user via Telegram
4. Show the challenge on a dashboard page for manual resolution

---

## CONTEXT — Existing Code You Must Know

### Backend entry point
**File: `backend/app/main.py`**
- FastAPI app created at line 174 with `lifespan` handler
- Services initialized in `lifespan()` (lines 64-170): `alerting_service`, `song_scheduler`, `health_monitor`, etc.
- Routers included at lines 194-205
- `AlertingService` is already initialized and has `send_alert()` and `_send_telegram()` methods
- Telegram config: `settings.TELEGRAM_BOT_TOKEN` and `settings.TELEGRAM_CHAT_ID` in `backend/app/config.py`

### Alerting service (already exists)
**File: `backend/app/services/alerting.py`**
- `AlertingService.send_alert(severity, title, message, db)` — stores in DB, sends Telegram if configured, broadcasts via WebSocket
- `AlertSeverity` imported from `backend/app/models/alert.py`

### Stream worker (where detection hooks in)
**File: `backend/app/services/automation/stream_worker.py`**
- `StreamWorker.execute_stream()` at line 50 — the main streaming method
- After launching Spotify (line 99) and before playing track (line 106), this is where challenge detection should happen
- Has access to `self.adb` (ADBService) and `self.spotify` (SpotifyController)

### Spotify controller
**File: `backend/app/services/automation/spotify_controller.py`**
- Has `self.mock_mode` flag
- Methods like `launch_spotify()`, `play_track_premium()`, `play_track_free()`
- You will add a `detect_challenge()` method here

### ADB service
**File: `backend/app/services/adb_service.py`**
- Provides `launch_app()`, `tap()`, `swipe()`, etc.
- You'll need to add a `take_screenshot()` method if it doesn't exist

### Base model pattern
**File: `backend/app/models/base.py`**
- Models inherit from `Base, TimestampMixin, UUIDMixin`
- `UUIDMixin` provides `id` column (UUID primary key)
- `TimestampMixin` provides `created_at` and `updated_at`

### Frontend routing
**File: `frontend/src/App.tsx`**
- Routes defined at lines 30-38 inside `<Route path="/" element={<Layout />}>`
- Add new route for challenges page

### Frontend sidebar
**File: `frontend/src/components/layout/Layout.tsx`**
- Navigation links are defined here
- Add "Challenges" link

### Available UI components
Located in `frontend/src/components/ui/`: badge, button, card, dialog, dropdown-menu, input, label, select, table, tabs, progress, separator, sheet

### Frontend API pattern
**File: `frontend/src/api/client.ts`**
- `apiClient` with `.get()`, `.post()`, `.patch()`, `.delete()` methods
- Base URL logic for local dev at lines 4-7

**File: `frontend/src/api/index.ts`**
- All API modules exported here — add yours

---

## PART A — Backend: Challenge Model

**Create new file: `backend/app/models/challenge.py`**

```python
import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import Enum, ForeignKey, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ChallengeType(str, enum.Enum):
    CAPTCHA = "captcha"
    EMAIL_VERIFY = "email_verify"
    PHONE_VERIFY = "phone_verify"
    TERMS_ACCEPT = "terms_accept"
    UNKNOWN = "unknown"


class ChallengeStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    FAILED = "failed"


class Challenge(Base, TimestampMixin, UUIDMixin):
    __tablename__ = "challenges"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=True
    )
    type: Mapped[ChallengeType] = mapped_column(
        Enum(ChallengeType, name="challenge_type"),
        default=ChallengeType.UNKNOWN, nullable=False
    )
    status: Mapped[ChallengeStatus] = mapped_column(
        Enum(ChallengeStatus, name="challenge_status"),
        default=ChallengeStatus.PENDING, nullable=False
    )
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    account = relationship("Account", lazy="selectin")
    instance = relationship("Instance", lazy="selectin")
```

**File: `backend/app/models/__init__.py`**
- Import `Challenge` so it's included in `Base.metadata.create_all()`. Check the existing imports in this file and add `from app.models.challenge import Challenge`.

---

## PART B — Backend: Challenge Schema

**Create new file: `backend/app/schemas/challenge.py`**

```python
from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict

from app.models.challenge import ChallengeType, ChallengeStatus


class ChallengeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    account_email: Optional[str] = None
    instance_id: Optional[UUID] = None
    instance_name: Optional[str] = None
    type: ChallengeType
    status: ChallengeStatus
    screenshot_path: Optional[str] = None
    resolved_at: Optional[datetime] = None
    expires_at: datetime
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChallengeResolveRequest(BaseModel):
    action: str  # "resolve", "skip", or "fail"
    notes: Optional[str] = None
```

---

## PART C — Backend: Challenge Router

**Create new file: `backend/app/routers/challenges.py`**

Prefix: `/api/challenges`

Endpoints:

### `GET /` — List challenges
Query params: `status: Optional[ChallengeStatus]`, `skip: int = 0`, `limit: int = 50`
- Query `Challenge` table, filtered by status if provided
- Order by `created_at` desc
- For each challenge, populate `account_email` from the relationship and `instance_name`
- Return `{"items": [...], "total": int}`

### `GET /{challenge_id}` — Get single challenge
- Return `ChallengeResponse` with populated relationships

### `POST /{challenge_id}/resolve` — Resolve a challenge
Body: `ChallengeResolveRequest`
- If `action == "resolve"`: set `status = RESOLVED`, `resolved_at = now`
- If `action == "skip"`: set `status = EXPIRED`
- If `action == "fail"`: set `status = FAILED`
- Set `notes` from request
- Commit and return updated challenge

### `GET /{challenge_id}/screenshot` — Serve screenshot
- Read `challenge.screenshot_path`
- If file exists, return `FileResponse`
- If not, return 404
- In mock mode (if path is None), return a placeholder or 404

### `GET /pending-count` — Count pending challenges
- `SELECT COUNT(*) FROM challenges WHERE status = 'pending'`
- Return `{"count": int}`

**File: `backend/app/main.py`**
- Add import: `from app.routers import challenges as challenges_router`
- Add: `app.include_router(challenges_router.router)` alongside the other router includes (around line 205)

---

## PART D — Backend: Challenge Detection in Stream Worker

**File: `backend/app/services/automation/spotify_controller.py`**

Add this method to the `SpotifyController` class:

```python
async def detect_challenge(self, device_id: str) -> Optional[dict]:
    """Check if the current screen shows a CAPTCHA or verification challenge.
    
    In real mode: dump UI hierarchy via `adb shell uiautomator dump` and
    parse the XML for known challenge indicators (captcha elements,
    verification prompts, etc.)
    
    Returns: {"type": "captcha"|"email_verify"|...} or None
    """
    if self.mock_mode:
        import random
        # 2% chance of challenge in mock mode for testing
        if random.random() < 0.02:
            challenge_types = ["captcha", "email_verify", "terms_accept"]
            return {"type": random.choice(challenge_types)}
        return None

    try:
        # Dump UI hierarchy
        # In real implementation:
        # xml = await self.adb.shell(device_id, "uiautomator dump /dev/tty")
        # Parse XML for challenge indicators
        # Look for text containing "captcha", "verify", "confirm", "robot"
        return None
    except Exception as e:
        logger.warning(f"Challenge detection failed on {device_id}: {e}")
        return None
```

**File: `backend/app/services/automation/stream_worker.py`**

In `execute_stream()`, AFTER the Spotify launch check (around line 100: `if not await self.spotify.launch_spotify(device_id): raise RuntimeError(...)`) and BEFORE the pre-stream delay (line 103: `await humanizer.pre_stream_delay()`), insert:

```python
# Detect challenges (captcha, verification, etc.)
challenge_info = await self.spotify.detect_challenge(device_id)
if challenge_info:
    logger.warning(
        f"Challenge detected on {instance.name} for {account.email}: "
        f"{challenge_info['type']}"
    )
    # Create challenge record if DB session available
    if db:
        from app.models.challenge import Challenge, ChallengeType
        from datetime import timedelta
        challenge = Challenge(
            account_id=account.id,
            instance_id=instance.id,
            type=ChallengeType(challenge_info.get("type", "unknown")),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.add(challenge)
        await db.flush()
    
    # Send alert (Telegram + WebSocket)
    if self.ws_manager:
        try:
            await self.ws_manager.broadcast({
                "type": "challenge_detected",
                "payload": {
                    "account_id": str(account.id),
                    "account_email": account.email,
                    "instance_name": instance.name,
                    "challenge_type": challenge_info["type"]
                }
            })
        except Exception:
            pass
    
    raise RuntimeError(f"Challenge detected: {challenge_info['type']}")
```

You also need to import `datetime` and `timedelta` at the top if not already imported (check existing imports at the top of the file).

---

## PART E — Frontend: Types

**File: `frontend/src/types/index.ts`**

Add these types (place them after the Account types section, around line 69):

```typescript
// ==================== Challenge Types ====================
export type ChallengeType = 'captcha' | 'email_verify' | 'phone_verify' | 'terms_accept' | 'unknown'
export type ChallengeStatus = 'pending' | 'resolved' | 'expired' | 'failed'

export interface Challenge {
  id: string
  account_id: string
  account_email?: string
  instance_id?: string
  instance_name?: string
  type: ChallengeType
  status: ChallengeStatus
  screenshot_path?: string
  resolved_at?: string
  expires_at: string
  notes?: string
  created_at: string
  updated_at: string
}
```

---

## PART F — Frontend: API Module

**Create new file: `frontend/src/api/challenges.ts`**

```typescript
import { apiClient } from './client'
import type { Challenge, PaginatedResponse } from '@/types'

export const challengesApi = {
  list: async (status?: string, skip = 0, limit = 50) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) })
    if (status) params.append('status', status)
    return apiClient.get<PaginatedResponse<Challenge>>(`/challenges?${params}`)
  },

  get: async (id: string) => {
    return apiClient.get<Challenge>(`/challenges/${id}`)
  },

  resolve: async (id: string, action: string, notes?: string) => {
    return apiClient.post<Challenge>(`/challenges/${id}/resolve`, { action, notes })
  },

  getPendingCount: async () => {
    return apiClient.get<{ count: number }>('/challenges/pending-count')
  },

  getScreenshotUrl: (id: string) => {
    const isLocal = import.meta.env.DEV && ['localhost', '127.0.0.1'].includes(window.location.hostname)
    const base = isLocal
      ? `${window.location.protocol}//${window.location.hostname}:8000/api`
      : '/api'
    return `${base}/challenges/${id}/screenshot`
  },
}
```

**File: `frontend/src/api/index.ts`**
Add: `export { challengesApi } from './challenges'`

---

## PART G — Frontend: Hooks

**Create new file: `frontend/src/hooks/useChallenges.ts`**

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { challengesApi } from '@/api'

const CHALLENGES_KEY = 'challenges'

export function useChallenges(status?: string) {
  return useQuery({
    queryKey: [CHALLENGES_KEY, status],
    queryFn: () => challengesApi.list(status),
    refetchInterval: 10000, // Poll every 10s for urgent challenges
  })
}

export function usePendingChallengeCount() {
  return useQuery({
    queryKey: [CHALLENGES_KEY, 'pending-count'],
    queryFn: () => challengesApi.getPendingCount(),
    refetchInterval: 15000,
  })
}

export function useResolveChallenge() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action, notes }: { id: string; action: string; notes?: string }) =>
      challengesApi.resolve(id, action, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [CHALLENGES_KEY] })
    },
  })
}
```

---

## PART H — Frontend: Challenges Page

**Create new file: `frontend/src/pages/Challenges.tsx`**

Build a page with:

1. **Header**: "Challenges" title + pending count badge
2. **Filter tabs**: `['all', 'pending', 'resolved', 'expired', 'failed']`
3. **Table** with columns:
   - Account (email)
   - Instance (name)
   - Type (badge with color: captcha=red, email_verify=yellow, etc.)
   - Status (badge)
   - Expires (countdown timer showing remaining minutes/seconds, or "Expired" if past)
   - Created (relative time)
   - Actions (Resolve / Skip / Fail buttons, only shown for pending)

4. **Detail dialog**: Clicking a row opens a dialog showing:
   - Screenshot image (from `challengesApi.getScreenshotUrl(id)`) — show a placeholder if no screenshot
   - All challenge info
   - Action buttons: "Mark Resolved", "Skip", "Mark Failed"
   - Optional notes textarea
   - After action, close dialog, toast result, refetch list

Use existing UI components: Card, Table, Dialog, Button, Badge, Tabs, Input.

---

## PART I — Frontend: Routing & Navigation

**File: `frontend/src/App.tsx`**
- Import: `import { Challenges } from '@/pages/Challenges'`
- Add route inside the Layout route: `<Route path="challenges" element={<Challenges />} />`

**File: `frontend/src/components/layout/Layout.tsx`**
- Read this file first to understand the sidebar structure
- Add a "Challenges" nav link with an icon (use `ShieldAlert` from lucide-react)
- If possible, show a badge with pending count next to the nav text (use `usePendingChallengeCount()`)

---

## Acceptance Criteria

1. `Challenge` model creates table on startup via `create_all`
2. `GET /api/challenges/` returns paginated list with account_email and instance_name populated
3. `POST /api/challenges/{id}/resolve` with `{"action": "resolve"}` sets status to resolved
4. `GET /api/challenges/pending-count` returns `{"count": N}`
5. Stream worker detects challenges (2% in mock mode) and creates Challenge records
6. Telegram alert is sent when challenge is detected (if configured)
7. Frontend Challenges page renders with filters, table, and action buttons
8. Detail dialog shows screenshot (or placeholder) and resolve actions
9. Sidebar shows "Challenges" link with pending count badge
10. No import errors, no runtime crashes, no broken existing functionality
