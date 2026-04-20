"""Alerts router - API endpoints for alert management and daily digest."""

import uuid
from typing import Optional, List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.database import get_db
from app.models.alert import Alert, AlertSeverity
from app.services.alerting import AlertingService

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Global reference (set during startup)
_alerting_service: Optional[AlertingService] = None


def set_alerting_service(alerting_service: AlertingService):
    """Set the global alerting service reference."""
    global _alerting_service
    _alerting_service = alerting_service


class AlertAcknowledge(BaseModel):
    pass  # Empty body for POST


@router.get("/")
async def list_alerts(
    severity: Optional[AlertSeverity] = None,
    acknowledged: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """List alerts (paginated, filterable by severity and acknowledged status)."""
    query = select(Alert)

    if severity:
        query = query.where(Alert.severity == severity)

    if acknowledged is not None:
        query = query.where(Alert.acknowledged == acknowledged)

    query = query.order_by(desc(Alert.created_at)).offset(skip).limit(limit)

    result = await db.execute(query)
    alerts = result.scalars().all()

    # Get total count
    count_query = select(Alert)
    if severity:
        count_query = count_query.where(Alert.severity == severity)
    if acknowledged is not None:
        count_query = count_query.where(Alert.acknowledged == acknowledged)

    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())

    return {
        "alerts": [
            {
                "id": str(a.id),
                "severity": a.severity.value,
                "channel": a.channel.value,
                "title": a.title,
                "message": a.message,
                "acknowledged": a.acknowledged,
                "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Mark an alert as acknowledged."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.acknowledged = True
    alert.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "id": str(alert_id),
        "acknowledged": True,
        "acknowledged_at": alert.acknowledged_at.isoformat()
    }


@router.get("/digest")
async def get_daily_digest(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Generate and return today's digest text."""
    if not _alerting_service:
        raise HTTPException(status_code=503, detail="Alerting service not initialized")

    digest = await _alerting_service.daily_digest(db)

    return {
        "digest": digest,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("/summary")
async def get_alerts_summary(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get summary of current alerts (counts by severity)."""
    from sqlalchemy import func

    # Count by severity
    result = await db.execute(
        select(Alert.severity, func.count(Alert.id))
        .where(Alert.acknowledged == False)
        .group_by(Alert.severity)
    )
    severity_counts = {row[0].value: row[1] for row in result.all()}

    # Total unacknowledged
    total_unacknowledged = sum(severity_counts.values())

    # Recent critical alerts (last 24h)
    from datetime import timezone, timedelta
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)

    critical_result = await db.execute(
        select(Alert)
        .where(
            Alert.severity == AlertSeverity.CRITICAL,
            Alert.created_at >= day_ago
        )
        .order_by(desc(Alert.created_at))
        .limit(5)
    )
    recent_critical = [
        {
            "id": str(a.id),
            "title": a.title,
            "created_at": a.created_at.isoformat() if a.created_at else None
        }
        for a in critical_result.scalars().all()
    ]

    return {
        "unacknowledged_by_severity": severity_counts,
        "total_unacknowledged": total_unacknowledged,
        "recent_critical": recent_critical
    }
