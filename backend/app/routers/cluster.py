"""Cluster router - API endpoints for multi-machine cluster management."""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.config import settings
from app.services.cluster import MachineRegistry, LoadBalancer
from app.models.machine import Machine, MachineStatus

router = APIRouter(prefix="/api/cluster", tags=["cluster"])

# Global references (set during startup)
_machine_registry: Optional[MachineRegistry] = None
_load_balancer: Optional[LoadBalancer] = None


def set_cluster_services(machine_registry: MachineRegistry, load_balancer: LoadBalancer):
    """Set the global cluster service references."""
    global _machine_registry, _load_balancer
    _machine_registry = machine_registry
    _load_balancer = load_balancer


class MachineCreate(BaseModel):
    hostname: str
    docker_host: str
    max_instances: int = 10
    max_ram_mb: int = 32768
    ssh_user: Optional[str] = None
    ssh_key_path: Optional[str] = None


class MachineUpdate(BaseModel):
    max_instances: Optional[int] = None
    max_ram_mb: Optional[int] = None
    status: Optional[MachineStatus] = None


def _check_cluster_enabled():
    """Return 404 if cluster mode is disabled."""
    if not settings.CLUSTER_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="Cluster mode is disabled. Set CLUSTER_ENABLED=true in .env to enable."
        )


@router.get("/machines")
async def list_machines(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """List all machines with utilization."""
    _check_cluster_enabled()
    if not _machine_registry:
        raise HTTPException(status_code=503, detail="Machine registry not initialized")

    machines = await _machine_registry.list_machines(db)

    result = []
    for machine in machines:
        util = await _machine_registry.get_machine_utilization(machine.id, db)
        result.append({
            "id": str(machine.id),
            "hostname": machine.hostname,
            "docker_host": machine.docker_host,
            "status": machine.status.value,
            "max_instances": machine.max_instances,
            "max_ram_mb": machine.max_ram_mb,
            "last_heartbeat": machine.last_heartbeat.isoformat() if machine.last_heartbeat else None,
            "utilization": util
        })

    return {"machines": result}


@router.post("/machines")
async def register_machine(
    data: MachineCreate,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Register a new machine."""
    _check_cluster_enabled()
    if not _machine_registry:
        raise HTTPException(status_code=503, detail="Machine registry not initialized")

    try:
        machine = await _machine_registry.register_machine(
            hostname=data.hostname,
            docker_host=data.docker_host,
            max_instances=data.max_instances,
            max_ram_mb=data.max_ram_mb,
            ssh_user=data.ssh_user,
            ssh_key_path=data.ssh_key_path,
            db=db
        )
        return {
            "id": str(machine.id),
            "hostname": machine.hostname,
            "docker_host": machine.docker_host,
            "status": machine.status.value,
            "message": "Machine registered successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/machines/{machine_id}")
async def get_machine(
    machine_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get machine detail with utilization and instances."""
    _check_cluster_enabled()
    if not _machine_registry:
        raise HTTPException(status_code=503, detail="Machine registry not initialized")

    machine = await _machine_registry.get_machine(machine_id, db)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")

    util = await _machine_registry.get_machine_utilization(machine_id, db)

    return {
        "id": str(machine.id),
        "hostname": machine.hostname,
        "docker_host": machine.docker_host,
        "ssh_user": machine.ssh_user,
        "max_instances": machine.max_instances,
        "max_ram_mb": machine.max_ram_mb,
        "status": machine.status.value,
        "last_heartbeat": machine.last_heartbeat.isoformat() if machine.last_heartbeat else None,
        "created_at": machine.created_at.isoformat() if machine.created_at else None,
        "utilization": util
    }


@router.delete("/machines/{machine_id}")
async def deregister_machine(
    machine_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Deregister a machine (sets status to DRAINING)."""
    _check_cluster_enabled()
    if not _machine_registry:
        raise HTTPException(status_code=503, detail="Machine registry not initialized")

    success = await _machine_registry.deregister_machine(machine_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="Machine not found")

    return {
        "message": "Machine set to DRAINING mode. Existing instances will continue running, but no new instances will be placed.",
        "machine_id": str(machine_id)
    }


@router.post("/machines/{machine_id}/heartbeat")
async def heartbeat(
    machine_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Trigger a heartbeat check for a machine."""
    _check_cluster_enabled()
    if not _machine_registry:
        raise HTTPException(status_code=503, detail="Machine registry not initialized")

    reachable = await _machine_registry.heartbeat(machine_id, db)

    return {
        "machine_id": str(machine_id),
        "reachable": reachable
    }


@router.get("/balance")
async def get_rebalance_report(
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get rebalance report (instance distribution across machines)."""
    _check_cluster_enabled()
    if not _load_balancer:
        raise HTTPException(status_code=503, detail="Load balancer not initialized")

    report = await _load_balancer.rebalance_report(db)
    return report


@router.get("/status")
async def get_cluster_status() -> dict:
    """Get cluster mode status."""
    return {
        "cluster_enabled": settings.CLUSTER_ENABLED,
        "machine_registry_initialized": _machine_registry is not None,
        "load_balancer_initialized": _load_balancer is not None
    }
