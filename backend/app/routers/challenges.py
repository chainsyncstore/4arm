"""Challenges router - CAPTCHA and verification challenge management."""

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.challenge import Challenge, ChallengeStatus
from app.schemas.challenge import ChallengeResponse, ChallengeResolveRequest, PaginatedChallengeResponse

router = APIRouter(prefix="/api/challenges", tags=["challenges"])


@router.get("/", response_model=PaginatedChallengeResponse)
async def list_challenges(
    status: Optional[ChallengeStatus] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """List challenges with optional status filter."""
    # Build query
    query = select(Challenge)
    if status:
        query = query.where(Challenge.status == status)
    query = query.order_by(Challenge.created_at.desc())
    
    # Get total count
    count_query = select(func.count(Challenge.id))
    if status:
        count_query = count_query.where(Challenge.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Get paginated results
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    challenges = result.scalars().all()
    
    # Build response with populated relationships
    items = []
    for challenge in challenges:
        items.append(ChallengeResponse(
            id=challenge.id,
            account_id=challenge.account_id,
            account_email=challenge.account.email if challenge.account else None,
            instance_id=challenge.instance_id,
            instance_name=challenge.instance.name if challenge.instance else None,
            type=challenge.type,
            status=challenge.status,
            screenshot_path=challenge.screenshot_path,
            resolved_at=challenge.resolved_at,
            expires_at=challenge.expires_at,
            notes=challenge.notes,
            created_at=challenge.created_at,
            updated_at=challenge.updated_at
        ))
    
    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/pending-count")
async def get_pending_count(db: AsyncSession = Depends(get_db)):
    """Get the count of pending challenges."""
    result = await db.execute(
        select(func.count(Challenge.id))
        .where(Challenge.status == ChallengeStatus.PENDING)
    )
    count = result.scalar()
    return {"count": count}


@router.get("/{challenge_id}")
async def get_challenge(
    challenge_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get a single challenge by ID."""
    result = await db.execute(
        select(Challenge).where(Challenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    return ChallengeResponse(
        id=challenge.id,
        account_id=challenge.account_id,
        account_email=challenge.account.email if challenge.account else None,
        instance_id=challenge.instance_id,
        instance_name=challenge.instance.name if challenge.instance else None,
        type=challenge.type,
        status=challenge.status,
        screenshot_path=challenge.screenshot_path,
        resolved_at=challenge.resolved_at,
        expires_at=challenge.expires_at,
        notes=challenge.notes,
        created_at=challenge.created_at,
        updated_at=challenge.updated_at
    )


@router.post("/{challenge_id}/resolve")
async def resolve_challenge(
    challenge_id: UUID,
    request: ChallengeResolveRequest,
    db: AsyncSession = Depends(get_db)
):
    """Resolve a challenge with the specified action."""
    result = await db.execute(
        select(Challenge).where(Challenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    now = datetime.now(timezone.utc)
    
    if request.action == "resolve":
        challenge.status = ChallengeStatus.RESOLVED
        challenge.resolved_at = now
    elif request.action == "skip":
        challenge.status = ChallengeStatus.EXPIRED
    elif request.action == "fail":
        challenge.status = ChallengeStatus.FAILED
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'resolve', 'skip', or 'fail'")
    
    if request.notes:
        challenge.notes = request.notes
    
    await db.commit()
    await db.refresh(challenge)
    
    return ChallengeResponse(
        id=challenge.id,
        account_id=challenge.account_id,
        account_email=challenge.account.email if challenge.account else None,
        instance_id=challenge.instance_id,
        instance_name=challenge.instance.name if challenge.instance else None,
        type=challenge.type,
        status=challenge.status,
        screenshot_path=challenge.screenshot_path,
        resolved_at=challenge.resolved_at,
        expires_at=challenge.expires_at,
        notes=challenge.notes,
        created_at=challenge.created_at,
        updated_at=challenge.updated_at
    )


@router.get("/{challenge_id}/screenshot")
async def get_screenshot(challenge_id: UUID, db: AsyncSession = Depends(get_db)):
    """Serve the screenshot for a challenge."""
    result = await db.execute(
        select(Challenge).where(Challenge.id == challenge_id)
    )
    challenge = result.scalar_one_or_none()
    
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    
    if not challenge.screenshot_path:
        raise HTTPException(status_code=404, detail="No screenshot available")
    
    if not os.path.exists(challenge.screenshot_path):
        raise HTTPException(status_code=404, detail="Screenshot file not found")
    
    return FileResponse(challenge.screenshot_path)
