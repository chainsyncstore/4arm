import uuid
import base64
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from io import StringIO

from app.database import get_db
from app.models.account import Account, AccountStatus, AccountType
from app.schemas.account import (
    AccountCreate, AccountResponse, AccountUpdate, AccountImport, PaginatedAccountResponse
)
from app.services.account_service import AccountService

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

# Global proxy provider reference (set during startup)
_proxy_provider = None


def set_proxy_provider(provider):
    global _proxy_provider
    _proxy_provider = provider



def get_account_service(db: AsyncSession = Depends(get_db)) -> AccountService:
    return AccountService(db)


def _serialize_account(account: Account) -> AccountResponse:
    resp = AccountResponse.model_validate(account)
    resp.password = account.password_plain
    if account.proxy:
        resp.proxy_host = account.proxy.host
        resp.proxy_port = account.proxy.port
    if account.assigned_instance:
        resp.assigned_instance_id = account.assigned_instance.id
        resp.assigned_instance_name = account.assigned_instance.name
    return resp


@router.get("/", response_model=PaginatedAccountResponse)
async def list_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[AccountStatus] = None,
    type: Optional[AccountType] = None,
    db: AsyncSession = Depends(get_db)
) -> PaginatedAccountResponse:
    """List all accounts with optional filters."""
    count_query = select(func.count(Account.id))
    if status:
        count_query = count_query.where(Account.status == status)
    if type:
        count_query = count_query.where(Account.type == type)

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    query = select(Account)
    if status:
        query = query.where(Account.status == status)
    if type:
        query = query.where(Account.type == type)
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    accounts = result.scalars().all()

    responses = [_serialize_account(account) for account in accounts]

    return PaginatedAccountResponse(
        items=responses,
        total=total,
        skip=skip,
        limit=limit
    )


@router.post("/", response_model=AccountResponse)
async def create_account(
    data: AccountCreate,
    service: AccountService = Depends(get_account_service)
) -> AccountResponse:
    """Create a new account."""
    account = await service.create_account(data, proxy_provider=_proxy_provider)
    resp = AccountResponse.model_validate(account)
    resp.password = account.password_plain
    if account.proxy:
        resp.proxy_host = account.proxy.host
        resp.proxy_port = account.proxy.port
    return resp


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


@router.post("/import")
async def import_accounts(
    file: UploadFile = File(...),
    service: AccountService = Depends(get_account_service)
) -> dict:
    """Bulk import accounts from CSV."""
    content = await file.read()
    csv_content = content.decode('utf-8')

    try:
        accounts = await service.import_accounts_from_csv(csv_content, proxy_provider=_proxy_provider)
        return {"imported": len(accounts), "accounts": [str(a.id) for a in accounts]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")


@router.post("/register")
async def register_accounts(
    count: int = Query(1, ge=1, le=10),
    instance_ids: Optional[list[uuid.UUID]] = Query(None),
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
        alerting=None,
        proxy_provider=_proxy_provider
    )

    try:
        result = await reg_service.register_batch(db=db, count=count, instance_ids=instance_ids)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    finally:
        await tempmail.close()


@router.post("/create-batch")
async def create_batch(
    count: int = Query(1, ge=1, le=10),
    instance_ids: Optional[list[uuid.UUID]] = Query(None),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Alias for register endpoint."""
    return await register_accounts(count=count, instance_ids=instance_ids, db=db)


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> AccountResponse:
    """Get account details."""
    result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return _serialize_account(account)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: uuid.UUID,
    data: AccountUpdate,
    service: AccountService = Depends(get_account_service)
) -> AccountResponse:
    """Update account fields."""
    try:
        account = await service.update_account(account_id, data, proxy_provider=_proxy_provider)
        resp = AccountResponse.model_validate(account)
        resp.password = account.password_plain
        if account.proxy:
            resp.proxy_host = account.proxy.host
            resp.proxy_port = account.proxy.port
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{account_id}")
async def delete_account(
    account_id: uuid.UUID,
    service: AccountService = Depends(get_account_service)
) -> dict:
    """Delete an account."""
    try:
        await service.delete_account(account_id, proxy_provider=_proxy_provider)
        return {"message": "Account deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{account_id}/link-proxy")
async def link_proxy(
    account_id: uuid.UUID,
    proxy_id: uuid.UUID,
    service: AccountService = Depends(get_account_service)
) -> AccountResponse:
    """Link a proxy to an account."""
    try:
        account = await service.link_proxy(account_id, proxy_id)
        resp = AccountResponse.model_validate(account)
        resp.password = account.password_plain
        if account.proxy:
            resp.proxy_host = account.proxy.host
            resp.proxy_port = account.proxy.port
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{account_id}/set-cooldown")
async def set_cooldown(
    account_id: uuid.UUID,
    hours: Optional[int] = None,
    service: AccountService = Depends(get_account_service)
) -> AccountResponse:
    """Set account cooldown."""
    try:
        account = await service.set_cooldown(account_id, hours)
        resp = AccountResponse.model_validate(account)
        resp.password = account.password_plain
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{account_id}/force-active")
async def force_active(
    account_id: uuid.UUID,
    service: AccountService = Depends(get_account_service)
) -> AccountResponse:
    """Force account status to active."""
    try:
        account = await service.force_active(account_id)
        resp = AccountResponse.model_validate(account)
        resp.password = account.password_plain
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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


@router.post("/{account_id}/extract-session")
async def extract_session(
    account_id: uuid.UUID,
    device_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Extract session from a device and store it for this account.

    Args:
        account_id: The account to associate the session with
        device_id: ADB device identifier (e.g., 'localhost:5555'). If not provided,
                   will use the assigned instance's adb_port.
    """
    from app.services.adb_service import ADBService
    from app.models.instance import Instance
    from sqlalchemy import select

    # Get account
    result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Determine device_id if not provided
    if not device_id:
        if account.assigned_instance and account.assigned_instance.adb_port:
            device_id = f"localhost:{account.assigned_instance.adb_port}"
        else:
            raise HTTPException(
                status_code=400,
                detail="device_id required (account has no assigned instance with adb_port)"
            )

    # Extract session
    adb = ADBService()
    try:
        session_path = await adb.extract_session(device_id)
        if not session_path:
            raise HTTPException(status_code=500, detail="Session extraction failed")

        # Update account with session path
        account.session_blob_path = session_path
        await db.commit()

        return {
            "message": "Session extracted successfully",
            "session_blob_path": session_path,
            "account_id": str(account_id)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session extraction failed: {str(e)}")


@router.post("/{account_id}/inject-session")
async def inject_session(
    account_id: uuid.UUID,
    device_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Inject stored session for this account into a device.

    Args:
        account_id: The account whose session will be injected
        device_id: ADB device identifier (e.g., 'localhost:5555'). If not provided,
                   will use the assigned instance's adb_port.
    """
    from app.services.adb_service import ADBService
    from sqlalchemy import select

    # Get account
    result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Check account has a stored session
    if not account.session_blob_path:
        raise HTTPException(
            status_code=400,
            detail="Account has no stored session. Use extract-session first."
        )

    # Determine device_id if not provided
    if not device_id:
        if account.assigned_instance and account.assigned_instance.adb_port:
            device_id = f"localhost:{account.assigned_instance.adb_port}"
        else:
            raise HTTPException(
                status_code=400,
                detail="device_id required (account has no assigned instance with adb_port)"
            )

    # Inject session
    adb = ADBService()
    try:
        success = await adb.inject_session(device_id, session_dir=account.session_blob_path)
        if not success:
            raise HTTPException(status_code=500, detail="Session injection failed")

        return {
            "message": "Session injected successfully",
            "account_id": str(account_id),
            "device_id": device_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Session injection failed: {str(e)}")
