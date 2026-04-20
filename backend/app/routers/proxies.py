import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.proxy import Proxy, ProxyStatus
from app.schemas.proxy import ProxyCreate, ProxyResponse, ProxyUpdate, ProxyTestResult
from app.services.proxy_service import ProxyService

router = APIRouter(prefix="/api/proxies", tags=["proxies"])

# Global proxy provider reference (set during startup)
_proxy_provider = None


def set_proxy_provider(provider):
    global _proxy_provider
    _proxy_provider = provider


def get_proxy_service(db: AsyncSession = Depends(get_db)) -> ProxyService:
    return ProxyService(db)


@router.get("/", response_model=list[ProxyResponse])
async def list_proxies(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[ProxyStatus] = None,
    unlinked: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
) -> list[ProxyResponse]:
    """List all proxies with optional filters."""
    query = select(Proxy)
    if status:
        query = query.where(Proxy.status == status)
    if unlinked:
        # Get proxies not linked to any account
        from app.models.account import Account
        query = query.outerjoin(Account, Proxy.id == Account.proxy_id).where(Account.id.is_(None))
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    proxies = result.scalars().all()

    # Build response with joined data
    responses = []
    for proxy in proxies:
        resp = ProxyResponse.model_validate(proxy)
        if proxy.account:
            resp.linked_account_id = proxy.account.id
            resp.linked_account_email = proxy.account.email
        responses.append(resp)

    return responses


@router.post("/", response_model=ProxyResponse)
async def create_proxy(
    data: ProxyCreate,
    service: ProxyService = Depends(get_proxy_service)
) -> ProxyResponse:
    """Create a new proxy."""
    proxy = await service.create_proxy(data)
    resp = ProxyResponse.model_validate(proxy)
    if proxy.account:
        resp.linked_account_id = proxy.account.id
        resp.linked_account_email = proxy.account.email
    return resp


@router.post("/import")
async def import_proxies(
    file: UploadFile = File(...),
    service: ProxyService = Depends(get_proxy_service)
) -> dict:
    """Bulk import proxies from CSV."""
    content = await file.read()
    csv_content = content.decode('utf-8')

    try:
        proxies = await service.import_proxies_from_csv(csv_content)
        return {"imported": len(proxies), "proxies": [str(p.id) for p in proxies]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")


@router.get("/provider/status")
async def proxy_provider_status() -> dict:
    """Get proxy provider connection status and quota."""
    if not _proxy_provider:
        return {"connected": False, "provider": "manual", "message": "No provider configured"}
    return await _proxy_provider.get_provider_status()


@router.get("/{proxy_id}", response_model=ProxyResponse)
async def get_proxy(
    proxy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> ProxyResponse:
    """Get proxy details."""
    result = await db.execute(select(Proxy).where(Proxy.id == proxy_id))
    proxy = result.scalar_one_or_none()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")

    resp = ProxyResponse.model_validate(proxy)
    if proxy.account:
        resp.linked_account_id = proxy.account.id
        resp.linked_account_email = proxy.account.email

    return resp


@router.delete("/{proxy_id}")
async def delete_proxy(
    proxy_id: uuid.UUID,
    service: ProxyService = Depends(get_proxy_service)
) -> dict:
    """Delete a proxy."""
    try:
        await service.delete_proxy(proxy_id)
        return {"message": "Proxy deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{proxy_id}/test", response_model=ProxyTestResult)
async def test_proxy(
    proxy_id: uuid.UUID,
    service: ProxyService = Depends(get_proxy_service)
) -> ProxyTestResult:
    """Test proxy connectivity."""
    try:
        return await service.test_proxy(proxy_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/test-all")
async def test_all_proxies(
    service: ProxyService = Depends(get_proxy_service)
) -> dict:
    """Batch test all proxies."""
    summary = await service.batch_test_proxies()
    return summary


@router.post("/{proxy_id}/link/{account_id}")
async def link_proxy_to_account(
    proxy_id: uuid.UUID,
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> ProxyResponse:
    """Bind proxy to account (1:1 relationship)."""
    from app.models.account import Account
    from app.services.account_service import AccountService
    service = AccountService(db)

    try:
        account = await service.link_proxy(account_id, proxy_id)
        # Return the proxy info
        result = await db.execute(select(Proxy).where(Proxy.id == proxy_id))
        proxy = result.scalar_one()
        linked_account_result = await db.execute(
            select(Account).where(Account.proxy_id == proxy_id)
        )
        linked_account = linked_account_result.scalar_one_or_none()
        resp = ProxyResponse.model_validate(proxy)
        if linked_account:
            resp.linked_account_id = linked_account.id
            resp.linked_account_email = linked_account.email
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/auto-assign")
async def auto_assign_proxies(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Auto-assign unlinked proxies to accounts without proxies."""
    from app.services.proxy_manager import ProxyManager

    proxy_manager = ProxyManager(db)
    result = await proxy_manager.auto_assign_proxies()
    return result


@router.get("/{proxy_id}/verify-ip")
async def verify_proxy_ip(
    proxy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Verify the IP of the instance using this proxy."""
    from app.services.proxy_manager import ProxyManager
    from app.models.instance import Instance
    from app.models.account import Account

    proxy_manager = ProxyManager(db)

    # Find the account using this proxy
    result = await db.execute(
        select(Account).where(Account.proxy_id == proxy_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="No account linked to this proxy")

    # Find the instance assigned to this account
    result = await db.execute(
        select(Instance).where(Instance.assigned_account_id == account.id)
    )
    instance = result.scalar_one_or_none()

    if not instance:
        raise HTTPException(status_code=404, detail="Account not assigned to any instance")

    verification = await proxy_manager.verify_instance_ip(instance.id)
    return {
        "proxy_id": str(proxy_id),
        "account_id": str(account.id),
        "instance_id": str(instance.id),
        "ip": verification["ip"],
        "matches_proxy": verification["matches_proxy"],
        "proxy_host": verification["proxy_host"]
    }


@router.post("/{proxy_id}/switch-on-instance/{instance_id}")
async def switch_proxy_on_instance(
    proxy_id: uuid.UUID,
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Switch the proxy configuration for a specific instance."""
    from app.services.proxy_manager import ProxyManager

    proxy_manager = ProxyManager(db)
    result = await proxy_manager.switch_instance_proxy(instance_id, proxy_id)
    return result

