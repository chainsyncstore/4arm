import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.instance import Instance, InstanceStatus
from app.models.account import Account
from app.schemas.instance import InstanceCreate, InstanceResponse, InstanceUpdate, PaginatedInstanceResponse
from app.services.instance_manager import InstanceManager

router = APIRouter(prefix="/api/instances", tags=["instances"])


def get_instance_manager(db: AsyncSession = Depends(get_db)) -> InstanceManager:
    return InstanceManager(db)


@router.get("/", response_model=PaginatedInstanceResponse)
async def list_instances(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[InstanceStatus] = None,
    db: AsyncSession = Depends(get_db)
) -> PaginatedInstanceResponse:
    """List all instances with optional status filter."""
    # Build base query for count
    count_query = select(func.count(Instance.id))
    if status:
        count_query = count_query.where(Instance.status == status)

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Build data query with joined relationships
    query = select(Instance).options(
        selectinload(Instance.assigned_account).selectinload(Account.proxy)
    )
    if status:
        query = query.where(Instance.status == status)
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    instances = result.scalars().all()

    # Build response with joined data
    responses = []
    for instance in instances:
        resp = InstanceResponse.model_validate(instance)
        if instance.assigned_account:
            resp.assigned_account_email = instance.assigned_account.email
            if instance.assigned_account.proxy:
                resp.assigned_proxy_host = instance.assigned_account.proxy.host
        responses.append(resp)

    return PaginatedInstanceResponse(
        items=responses,
        total=total,
        skip=skip,
        limit=limit
    )


@router.post("/", response_model=InstanceResponse)
async def create_instance(
    data: InstanceCreate,
    manager: InstanceManager = Depends(get_instance_manager)
) -> InstanceResponse:
    """Create a new instance."""
    instance = await manager.create_instance(
        name=data.name,
        ram_limit_mb=data.ram_limit_mb,
        cpu_cores=data.cpu_cores
    )
    return InstanceResponse.model_validate(instance)


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> InstanceResponse:
    """Get instance details."""
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    resp = InstanceResponse.model_validate(instance)
    if instance.assigned_account:
        resp.assigned_account_email = instance.assigned_account.email
        if instance.assigned_account.proxy:
            resp.assigned_proxy_host = instance.assigned_account.proxy.host

    return resp


@router.post("/{instance_id}/start", response_model=InstanceResponse)
async def start_instance(
    instance_id: uuid.UUID,
    manager: InstanceManager = Depends(get_instance_manager)
) -> InstanceResponse:
    """Start a stopped instance."""
    try:
        instance = await manager.start_instance(instance_id)
        return InstanceResponse.model_validate(instance)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{instance_id}/stop", response_model=InstanceResponse)
async def stop_instance(
    instance_id: uuid.UUID,
    manager: InstanceManager = Depends(get_instance_manager)
) -> InstanceResponse:
    """Stop a running instance."""
    try:
        instance = await manager.stop_instance(instance_id)
        return InstanceResponse.model_validate(instance)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{instance_id}/restart", response_model=InstanceResponse)
async def restart_instance(
    instance_id: uuid.UUID,
    manager: InstanceManager = Depends(get_instance_manager)
) -> InstanceResponse:
    """Restart an instance."""
    try:
        instance = await manager.restart_instance(instance_id)
        return InstanceResponse.model_validate(instance)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{instance_id}")
async def destroy_instance(
    instance_id: uuid.UUID,
    manager: InstanceManager = Depends(get_instance_manager)
) -> dict:
    """Destroy an instance permanently."""
    try:
        await manager.destroy_instance(instance_id)
        return {"message": "Instance destroyed successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{instance_id}/assign-account")
async def assign_account(
    instance_id: uuid.UUID,
    account_id: uuid.UUID,
    manager: InstanceManager = Depends(get_instance_manager),
    db: AsyncSession = Depends(get_db)
) -> InstanceResponse:
    """Assign an account to an instance."""
    # Verify account exists
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        instance = await manager.assign_account(instance_id, account_id)
        return InstanceResponse.model_validate(instance)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{instance_id}/unassign-account")
async def unassign_account(
    instance_id: uuid.UUID,
    manager: InstanceManager = Depends(get_instance_manager)
) -> InstanceResponse:
    """Remove account assignment from an instance."""
    try:
        instance = await manager.unassign_account(instance_id)
        return InstanceResponse.model_validate(instance)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
