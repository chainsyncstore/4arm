# SUB-AGENT PROMPT 1 — Accounts Page Overhaul

You are working on a Spotify streaming farm management system called **4ARM**.  
Your task is to overhaul the Accounts page (backend + frontend) to support:
- Displaying & editing passwords
- Account type (free/premium) filtering
- CSV template download with sample data
- Inline edit & delete per account row
- Auto-downgrade of premium accounts to free when shuffle-miss behavior is detected

**Do NOT create new files unless explicitly instructed. Prefer editing existing files.**

---

## PART A — Backend Model Change

**File: `backend/app/models/account.py`**

The `Account` model currently has `password_hash` (line 29) but no way to store/return the plaintext password for dashboard display. This is an internal-only tool, not user-facing SaaS.

**Action**: Add a new column `password_plain` (String(255), nullable=True) on the line directly after `password_hash`:

```python
password_plain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```

Do NOT remove `password_hash`. Both columns coexist.

---

## PART B — Backend Schema Changes

**File: `backend/app/schemas/account.py`**

Current `AccountResponse` (line 32-50) does NOT include password. Current `AccountUpdate` (line 20-25) does NOT include password. Current `AccountCreate` (line 15-17) has `password: Optional[str] = None`.

**Actions**:
1. In `AccountResponse`, add: `password: Optional[str] = None` (this maps from `password_plain`)
2. In `AccountUpdate`, add: `password: Optional[str] = None`

---

## PART C — Backend Service Changes

**File: `backend/app/services/account_service.py`**

### In `create_account()` (line 19-38):
Replace the password handling block (lines 30-32):
```python
if hasattr(data, 'password') and data.password:
    # In production: account.password_hash = hash_password(data.password)
    pass
```
With:
```python
if hasattr(data, 'password') and data.password:
    account.password_plain = data.password
```

### In `import_accounts_from_csv()` (line 40-66):
After `account = Account(email=row['email'], ...)` (around line 50-54), add:
```python
if 'password' in row and row['password']:
    account.password_plain = row['password']
```
Replace the existing empty `if 'password' in row: pass` block.

Also update the `type` assignment: currently `type=row.get('type', 'free')` — this is correct and should stay.

### In `update_account()` (line 75-91):
The existing code uses `data.model_dump(exclude_unset=True)` and `setattr`. This will naturally handle `password` if it's in the update payload, BUT it will set `account.password` which doesn't exist as a column. 

Add a special case: if `'password'` is in `update_data`, pop it out and set `account.password_plain` instead:
```python
update_data = data.model_dump(exclude_unset=True)
if 'password' in update_data:
    account.password_plain = update_data.pop('password')
for field, value in update_data.items():
    setattr(account, field, value)
```

---

## PART D — Backend Router Changes

**File: `backend/app/routers/accounts.py`**

### Fix `AccountResponse` building in all endpoints:
Everywhere `AccountResponse.model_validate(account)` is called, the `password` field in the response should be populated from `account.password_plain`. Since Pydantic's `from_attributes=True` won't auto-map `password_plain` → `password`, add a manual mapping after each `model_validate` call:

```python
resp = AccountResponse.model_validate(account)
resp.password = account.password_plain
```

Apply this in: `list_accounts`, `create_account`, `get_account`, `update_account`, `link_proxy` (5 places).

### Add CSV template endpoint:
Add this new endpoint BEFORE the `/{account_id}` routes (to avoid path collision):

```python
from fastapi.responses import StreamingResponse
from io import StringIO

@router.get("/csv-template")
async def download_csv_template():
    """Download a sample CSV template for bulk account import."""
    csv_content = """email,password,type,display_name
user1@example.com,StrongPass123,free,User One
user2@example.com,SecurePass456,premium,User Two
user3@example.com,MyPassword789,free,User Three
"""
    return StreamingResponse(
        StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=accounts_template.csv"}
    )
```

**IMPORTANT**: This route MUST be placed before any `/{account_id}` routes (before line 86), otherwise FastAPI will try to match "csv-template" as an account_id UUID and return 422.

---

## PART E — Auto-Downgrade Premium → Free

**File: `backend/app/services/automation/stream_worker.py`**

In `execute_stream()`, after the streaming loop completes and before the `StreamLog` is created (around line 178, after the result determination block), add:

```python
# Auto-downgrade premium account if shuffle behavior detected
if account.type == AccountType.PREMIUM and shuffle_miss_count > 0:
    logger.warning(
        f"Premium account {account.email} hit {shuffle_miss_count} shuffle misses "
        f"— downgrading to FREE"
    )
    account.type = AccountType.FREE
    if db:
        db.add(account)
        await db.flush()
    if self.ws_manager:
        try:
            await self.ws_manager.broadcast({
                "type": "account_downgraded",
                "payload": {
                    "account_id": str(account.id),
                    "email": account.email,
                    "reason": "shuffle_miss_detected"
                }
            })
        except Exception:
            pass
```

Place this AFTER line 182 (`result = StreamResult.SUCCESS`) and BEFORE line 184 (`logger.info(...)`).

---

## PART F — Frontend Type Changes

**File: `frontend/src/types/index.ts`**

In the `Account` interface (line 43-58), add after `email`:
```typescript
password?: string
```

In `AccountCreateRequest` (line 60-65), add after `email`:
```typescript
password?: string
```

---

## PART G — Frontend API Changes

**File: `frontend/src/api/accounts.ts`**

Add this method to the `accountsApi` object (after the existing `importCSV` method around line 31):

```typescript
downloadTemplate: () => {
  const isLocal = import.meta.env.DEV && ['localhost', '127.0.0.1'].includes(window.location.hostname)
  const base = isLocal
    ? `${window.location.protocol}//${window.location.hostname}:8000/api`
    : '/api'
  window.open(`${base}/accounts/csv-template`, '_blank')
},
```

Also add an `update` method that accepts password:
The existing `update` method (line 34-36) is fine — it already sends `Partial<AccountCreateRequest>` which will include `password` after the types change.

---

## PART H — Frontend Accounts Page Rewrite

**File: `frontend/src/pages/Accounts.tsx`**

Rewrite this file completely. Requirements:

### Imports needed:
```typescript
import { useState, type ChangeEvent } from 'react'
import { useAccounts, useUpdateAccount, useImportAccounts, useDeleteAccount } from '@/hooks/useAccounts'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Upload, Trash2, Pencil, Eye, EyeOff, Download } from 'lucide-react'
import { toast } from 'sonner'
import { accountsApi } from '@/api'
import type { Account, AccountStatus, AccountType } from '@/types'
```

### State:
```typescript
const [statusFilter, setStatusFilter] = useState<AccountStatus | 'all'>('all')
const [typeFilter, setTypeFilter] = useState<AccountType | 'all'>('all')
const [visiblePasswords, setVisiblePasswords] = useState<Set<string>>(new Set())
const [editAccount, setEditAccount] = useState<Account | null>(null)
const [editPassword, setEditPassword] = useState('')
const [editType, setEditType] = useState<AccountType>('free')
```

### Two filter rows:
1. Status filter tabs: `['all', 'new', 'warming', 'active', 'cooldown', 'banned']`
2. Type filter tabs: `['all', 'free', 'premium']`

Both filters are passed to `useAccounts(0, 50, statusFilter === 'all' ? undefined : statusFilter, typeFilter === 'all' ? undefined : typeFilter)`.

### Table columns:
| Email | Password | Type | Status | Proxy | Streams | Actions |
|-------|----------|------|--------|-------|---------|---------|

- **Password**: Show `••••••••` by default. Eye icon toggles visibility per row using the `visiblePasswords` Set. Show actual `account.password` when visible, or "—" if null.
- **Type**: Show `<Badge variant={account.type === 'premium' ? 'default' : 'secondary'}>{account.type}</Badge>`
- **Proxy**: Show `account.proxy_host + ':' + account.proxy_port` if both exist, else "None"  
  Note: The Account type in frontend doesn't have proxy_host/proxy_port. You'll need to add `proxy_host?: string` and `proxy_port?: number` to the `Account` interface in `frontend/src/types/index.ts`.
- **Streams**: `{account.streams_today} / {account.total_streams}`
- **Actions**: Pencil icon (opens edit dialog) + Trash icon (confirm & delete)

### Header row with buttons:
- **Download Template** button: calls `accountsApi.downloadTemplate()`
- **Import CSV** button: file input (existing logic)
- Remove the "Create Batch" button (it's a placeholder that does nothing useful yet)

### Edit dialog:
When Pencil is clicked, set `editAccount` to that account, `editPassword` to `account.password || ''`, `editType` to `account.type`.

Dialog shows:
- Email (read-only, displayed as text not input)
- Password input (pre-filled, editable)
- Type select (free/premium dropdown)
- Cancel + Save buttons

Save calls `updateAccount.mutateAsync({ id: editAccount.id, data: { password: editPassword, type: editType } })`.

### Password toggle helper:
```typescript
const togglePasswordVisibility = (id: string) => {
  setVisiblePasswords(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
}
```

---

## PART I — Frontend Types Addition

**File: `frontend/src/types/index.ts`**

Add to `Account` interface (around line 43-58):
```typescript
proxy_host?: string
proxy_port?: number
```

These already come from the backend `AccountResponse` but weren't typed in the frontend.

---

## Acceptance Criteria

1. `GET /api/accounts/` returns accounts with `password` field populated from `password_plain`
2. `GET /api/accounts/csv-template` downloads a CSV file with headers: `email,password,type,display_name`
3. `POST /api/accounts/import` with a CSV that includes `password` and `type` columns stores them correctly
4. `PATCH /api/accounts/{id}` with `{"password": "new", "type": "premium"}` updates both fields
5. Frontend Accounts page shows two filter rows (status + type)
6. Frontend table shows Password column with eye toggle
7. Frontend edit dialog allows changing password and type
8. Frontend has "Download Template" button that fetches the CSV
9. In `stream_worker.py`, a premium account that hits shuffle misses is auto-downgraded to free
10. No existing tests are broken, no new import errors, no runtime crashes
