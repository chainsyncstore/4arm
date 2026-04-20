import os
import psutil
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.instance import Instance, InstanceStatus

router = APIRouter(prefix="/api/system", tags=["system"])

# Constants
RAM_PER_INSTANCE_MB = 2048
RESERVED_RAM_MB = 4096


@router.get("/capacity")
async def get_capacity(db: AsyncSession = Depends(get_db)) -> dict:
    """Get system capacity information for instance planning."""
    # Get total and available RAM
    mem = psutil.virtual_memory()
    total_ram_mb = mem.total // (1024 * 1024)
    available_ram_mb = mem.available // (1024 * 1024)

    # Count running instances
    result = await db.execute(
        select(func.count(Instance.id)).where(Instance.status == InstanceStatus.RUNNING)
    )
    running_instances = result.scalar() or 0

    # Calculate capacity
    free_ram_mb = available_ram_mb
    max_safe_instances = (total_ram_mb - RESERVED_RAM_MB) // RAM_PER_INSTANCE_MB
    possible_more = max(0, (free_ram_mb - RESERVED_RAM_MB) // RAM_PER_INSTANCE_MB)

    return {
        "total_ram_mb": total_ram_mb,
        "used_ram_mb": total_ram_mb - available_ram_mb,
        "free_ram_mb": free_ram_mb,
        "running_instances": running_instances,
        "max_safe_instances": max_safe_instances,
        "reserved_ram_mb": RESERVED_RAM_MB,
        "possible_more_instances": possible_more
    }


@router.get("/resources")
async def get_resources() -> dict:
    """Get current system resource usage."""
    # CPU
    cpu_percent = psutil.cpu_percent(interval=0.5)

    # RAM
    mem = psutil.virtual_memory()

    # Disk
    disk = psutil.disk_usage(os.path.splitdrive(os.getcwd())[0] or '/')

    return {
        "cpu_percent": cpu_percent,
        "ram_percent": mem.percent,
        "ram_used_gb": mem.used // (1024 ** 3),
        "ram_total_gb": mem.total // (1024 ** 3),
        "disk_percent": (disk.used / disk.total) * 100,
        "disk_used_gb": disk.used // (1024 ** 3),
        "disk_total_gb": disk.total // (1024 ** 3)
    }


@router.get("/health")
async def health_check() -> dict:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
