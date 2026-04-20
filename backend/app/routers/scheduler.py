"""Scheduler router - API endpoints for managing the automation scheduler."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.services.automation.song_scheduler import SongScheduler
from app.services.automation.health_monitor import HealthMonitor
from app.ws.dashboard import DashboardWebSocketManager

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

# Global references to scheduler instances (set during startup)
_song_scheduler: Optional[SongScheduler] = None
_health_monitor: Optional[HealthMonitor] = None
_rate_limiter: Optional[any] = None  # Type any to avoid circular import
_alerting_service: Optional[any] = None  # Type any to avoid circular import


def set_schedulers(
    song_scheduler: SongScheduler,
    health_monitor: HealthMonitor,
    rate_limiter=None,
    alerting_service=None
):
    """Set the global scheduler references."""
    global _song_scheduler, _health_monitor, _rate_limiter, _alerting_service
    _song_scheduler = song_scheduler
    _health_monitor = health_monitor
    _rate_limiter = rate_limiter
    _alerting_service = alerting_service


@router.get("/status")
async def get_scheduler_status() -> dict:
    """
    Get scheduler state, active tasks, queue depth.

    Returns:
        {
            "song_scheduler": {...},
            "health_monitor": {...}
        }
    """
    if not _song_scheduler or not _health_monitor:
        raise HTTPException(status_code=503, detail="Schedulers not initialized")

    return {
        "song_scheduler": await _song_scheduler.get_status(),
        "health_monitor": _health_monitor.get_status()
    }


@router.post("/pause")
async def pause_scheduler() -> dict:
    """
    Pause the song scheduler.

    Active streams will continue, but new streams won't be scheduled.
    """
    if not _song_scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    _song_scheduler.pause()
    return {
        "message": "Scheduler paused",
        "state": "paused"
    }


@router.post("/resume")
async def resume_scheduler() -> dict:
    """
    Resume the song scheduler.
    """
    if not _song_scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    _song_scheduler.resume()
    return {
        "message": "Scheduler resumed",
        "state": "running"
    }


@router.get("/health")
async def get_health_status() -> dict:
    """
    Get health monitor status.
    """
    if not _health_monitor:
        raise HTTPException(status_code=503, detail="Health monitor not initialized")

    return _health_monitor.get_status()


@router.get("/rate-limiter/status")
async def get_rate_limiter_status() -> dict:
    """
    Get rate limiter status (active streams, tracked instances/accounts).
    """
    if not _rate_limiter:
        raise HTTPException(status_code=503, detail="Rate limiter not initialized")

    return _rate_limiter.get_status()


@router.post("/health/restart-failed")
async def restart_failed_instances(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Manually trigger restart of all instances in error state.
    """
    from sqlalchemy import select
    from app.models.instance import Instance, InstanceStatus
    from app.services.instance_manager import InstanceManager

    if not _health_monitor:
        raise HTTPException(status_code=503, detail="Health monitor not initialized")

    # Find instances in error state
    result = await db.execute(
        select(Instance).where(Instance.status == InstanceStatus.ERROR)
    )
    instances = result.scalars().all()

    restarted = 0
    manager = InstanceManager(db)

    for instance in instances:
        try:
            await manager.restart_instance(instance.id)
            restarted += 1
        except Exception as e:
            # Log but continue
            pass

    return {
        "message": f"Restarted {restarted} failed instances",
        "restarted_count": restarted,
        "total_error_instances": len(instances)
    }
