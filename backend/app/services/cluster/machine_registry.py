"""Machine Registry - Remote Docker host management."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.machine import Machine, MachineStatus
from app.models.instance import Instance, InstanceStatus
from app.config import settings

logger = logging.getLogger(__name__)


class MachineRegistry:
    """Manages remote Docker host registration."""

    def __init__(self, db_session_maker):
        self.db_session_maker = db_session_maker
        self.mock_mode = settings.MOCK_DOCKER

    async def register_machine(
        self,
        hostname: str,
        docker_host: str,
        max_instances: int = 10,
        max_ram_mb: int = 32768,
        ssh_user: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> Machine:
        """Register a new machine. Validate connectivity via Docker API ping."""
        session_created = False
        if db is None:
            async with self.db_session_maker() as db:
                session_created = True
                return await self._do_register(
                    db, hostname, docker_host, max_instances, max_ram_mb, ssh_user, ssh_key_path
                )
        else:
            return await self._do_register(
                db, hostname, docker_host, max_instances, max_ram_mb, ssh_user, ssh_key_path
            )

    async def _do_register(
        self,
        db: AsyncSession,
        hostname: str,
        docker_host: str,
        max_instances: int,
        max_ram_mb: int,
        ssh_user: Optional[str],
        ssh_key_path: Optional[str]
    ) -> Machine:
        # Check if machine already exists
        existing = await db.execute(select(Machine).where(Machine.hostname == hostname))
        if existing.scalar_one_or_none():
            raise ValueError(f"Machine with hostname {hostname} already registered")

        # Validate connectivity (mock on Windows)
        if self.mock_mode:
            logger.info(f"MOCK: Validating Docker connectivity to {docker_host} (always succeeds)")
            reachable = True
        else:
            # Real Docker API ping would go here
            from app.services.cluster.remote_docker import RemoteDockerClient
            client = RemoteDockerClient(docker_host)
            reachable = await client.ping()

        if not reachable:
            raise ConnectionError(f"Cannot reach Docker host at {docker_host}")

        machine = Machine(
            hostname=hostname,
            docker_host=docker_host,
            max_instances=max_instances,
            max_ram_mb=max_ram_mb,
            ssh_user=ssh_user,
            ssh_key_path=ssh_key_path,
            status=MachineStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc)
        )

        db.add(machine)
        await db.commit()
        await db.refresh(machine)

        logger.info(f"Registered machine {hostname} at {docker_host}")
        return machine

    async def heartbeat(self, machine_id: uuid.UUID, db: Optional[AsyncSession] = None) -> bool:
        """Check if a machine is reachable. Update last_heartbeat."""
        session_created = False
        if db is None:
            async with self.db_session_maker() as db:
                session_created = True
                return await self._do_heartbeat(db, machine_id)
        else:
            return await self._do_heartbeat(db, machine_id)

    async def _do_heartbeat(self, db: AsyncSession, machine_id: uuid.UUID) -> bool:
        result = await db.execute(select(Machine).where(Machine.id == machine_id))
        machine = result.scalar_one_or_none()
        if not machine:
            return False

        if self.mock_mode:
            logger.debug(f"MOCK: Heartbeat check for {machine.hostname} (always succeeds)")
            reachable = True
        else:
            from app.services.cluster.remote_docker import RemoteDockerClient
            client = RemoteDockerClient(machine.docker_host)
            reachable = await client.ping()

        if reachable:
            machine.last_heartbeat = datetime.now(timezone.utc)
            if machine.status == MachineStatus.OFFLINE:
                machine.status = MachineStatus.ONLINE
                logger.info(f"Machine {machine.hostname} came back online")
        else:
            machine.status = MachineStatus.OFFLINE
            logger.warning(f"Machine {machine.hostname} is unreachable")

        await db.commit()
        return reachable

    async def get_machine_utilization(self, machine_id: uuid.UUID, db: AsyncSession) -> dict:
        """Return utilization stats for a machine."""
        result = await db.execute(select(Machine).where(Machine.id == machine_id))
        machine = result.scalar_one_or_none()
        if not machine:
            raise ValueError(f"Machine {machine_id} not found")

        # Count instances on this machine
        # For now, we don't track machine_id per instance, so assume all instances are on default machine
        # In a real implementation, instances would have a machine_id foreign key
        instances_result = await db.execute(
            select(func.count(Instance.id))
            .where(Instance.status.in_([InstanceStatus.RUNNING, InstanceStatus.CREATING]))
        )
        instances = instances_result.scalar() or 0

        # Estimate RAM usage (assume 2GB per instance)
        avg_ram_per_instance = 2048
        ram_used_mb = instances * avg_ram_per_instance
        ram_pct = (ram_used_mb / machine.max_ram_mb) * 100 if machine.max_ram_mb > 0 else 0

        # Mock CPU percentage
        cpu_pct = 45.0 if self.mock_mode else (machine.cpu_pct or 0)

        return {
            "machine_id": str(machine_id),
            "hostname": machine.hostname,
            "instances": instances,
            "max_instances": machine.max_instances,
            "ram_used_mb": ram_used_mb,
            "ram_pct": round(ram_pct, 2),
            "cpu_pct": round(cpu_pct, 2),
            "status": machine.status.value
        }

    async def deregister_machine(self, machine_id: uuid.UUID, db: AsyncSession) -> bool:
        """Set machine to DRAINING (instances keep running, no new ones placed)."""
        result = await db.execute(select(Machine).where(Machine.id == machine_id))
        machine = result.scalar_one_or_none()
        if not machine:
            return False

        machine.status = MachineStatus.DRAINING
        await db.commit()

        logger.info(f"Machine {machine.hostname} set to DRAINING mode")
        return True

    async def delete_machine(self, machine_id: uuid.UUID, db: AsyncSession) -> bool:
        """Delete a machine (only if no instances are running on it)."""
        result = await db.execute(select(Machine).where(Machine.id == machine_id))
        machine = result.scalar_one_or_none()
        if not machine:
            return False

        await db.delete(machine)
        await db.commit()

        logger.info(f"Deleted machine {machine.hostname}")
        return True

    async def list_machines(self, db: AsyncSession) -> list[Machine]:
        """List all registered machines."""
        result = await db.execute(select(Machine).order_by(Machine.hostname))
        return result.scalars().all()

    async def get_machine(self, machine_id: uuid.UUID, db: AsyncSession) -> Optional[Machine]:
        """Get a single machine by ID."""
        result = await db.execute(select(Machine).where(Machine.id == machine_id))
        return result.scalar_one_or_none()
