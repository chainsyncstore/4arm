"""Warmup router — API endpoints for managing account warmup sequences."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account, AccountStatus
from app.services.antidetect.warmup import WarmupManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/warmup", tags=["warmup"])


@router.get("/status")
async def get_warmup_status(db: AsyncSession = Depends(get_db)) -> dict:
    """List all WARMING accounts with current day and plan."""
    result = await db.execute(
        select(Account).where(Account.status == AccountStatus.WARMING)
    )
    accounts = result.scalars().all()

    manager = WarmupManager()
    statuses = []
    for acct in accounts:
        plan = await manager.get_warmup_plan(acct, db)
        statuses.append({
            "account_id": str(acct.id),
            "email": acct.email,
            "warmup_day": acct.warmup_day,
            "plan": plan,
        })

    return {"warming_accounts": statuses, "count": len(statuses)}


@router.post("/{account_id}/skip")
async def skip_warmup(account_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Skip warmup and force account to ACTIVE."""
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.status = AccountStatus.ACTIVE
    account.warmup_day = 0
    await db.commit()

    logger.info(f"Skipped warmup for account {account.email} — status set to ACTIVE")
    return {
        "message": f"Warmup skipped for {account.email}",
        "account_id": str(account_id),
        "status": account.status.value,
    }


@router.post("/{account_id}/reset")
async def reset_warmup(account_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Reset warmup to day 1."""
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.status = AccountStatus.WARMING
    account.warmup_day = 1
    await db.commit()

    logger.info(f"Reset warmup for account {account.email} — back to day 1")
    return {
        "message": f"Warmup reset for {account.email}",
        "account_id": str(account_id),
        "warmup_day": 1,
        "status": account.status.value,
    }
