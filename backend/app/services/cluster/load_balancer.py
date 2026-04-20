"""Load Balancer - Instance placement across machines."""

import logging
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.machine import Machine, MachineStatus
from app.models.instance import Instance, InstanceStatus

logger = logging.getLogger(__name__)


class LoadBalancer:
    """Selects optimal machine for new instance placement."""

    def __init__(self, machine_registry=None):
        self.machine_registry = machine_registry

    async def select_machine(self, ram_required_mb: int, db: AsyncSession) -> Optional[Machine]:
        """Select machine with:
        1. Status = ONLINE
        2. Enough free RAM (max_ram_mb - current_instances * avg_ram_per_instance)
        3. Below max_instances limit
        4. Lowest current utilization (RAM %)

        Return None if no machine has capacity.
        """
        # Get all online machines
        result = await db.execute(
            select(Machine).where(Machine.status == MachineStatus.ONLINE)
        )
        machines = result.scalars().all()

        if not machines:
            logger.warning("No online machines available for instance placement")
            return None

        # Get instance counts per machine
        # For now, we assume all instances are on the default machine
        # In a real implementation, instances would have machine_id
        avg_ram_per_instance = 2048  # MB

        candidates = []
        for machine in machines:
            # Count instances (mock: all instances count towards first machine)
            instances_result = await db.execute(
                select(func.count(Instance.id))
                .where(Instance.status.in_([InstanceStatus.RUNNING, InstanceStatus.CREATING]))
            )
            instance_count = instances_result.scalar() or 0

            # Check max instances limit
            if instance_count >= machine.max_instances:
                continue

            # Calculate RAM usage
            ram_used_mb = instance_count * avg_ram_per_instance
            ram_free_mb = machine.max_ram_mb - ram_used_mb

            # Check if enough RAM for new instance
            if ram_free_mb < ram_required_mb:
                continue

            ram_pct = (ram_used_mb / machine.max_ram_mb) * 100 if machine.max_ram_mb > 0 else 0

            candidates.append({
                "machine": machine,
                "instance_count": instance_count,
                "ram_pct": ram_pct,
                "ram_free_mb": ram_free_mb
            })

        if not candidates:
            logger.warning("No machines have capacity for new instance")
            return None

        # Sort by RAM utilization (lowest first)
        candidates.sort(key=lambda x: x["ram_pct"])

        selected = candidates[0]["machine"]
        logger.info(
            f"Selected machine {selected.hostname} for new instance "
            f"(utilization: {candidates[0]['ram_pct']:.1f}%)"
        )
        return selected

    async def rebalance_report(self, db: AsyncSession) -> dict:
        """Return a report of instance distribution across machines.

        Don't auto-migrate — just report imbalances.
        """
        result = await db.execute(select(Machine))
        machines = result.scalars().all()

        # Get total instances
        instances_result = await db.execute(
            select(func.count(Instance.id))
            .where(Instance.status.in_([InstanceStatus.RUNNING, InstanceStatus.CREATING]))
        )
        total_instances = instances_result.scalar() or 0

        machine_reports = []
        avg_ram_per_instance = 2048

        for machine in machines:
            # Count instances on this machine (mock: distribute evenly for report)
            # In real implementation, filter by machine_id
            instances_on_machine = total_instances // len(machines) if machines else 0

            ram_used_mb = instances_on_machine * avg_ram_per_instance
            ram_pct = (ram_used_mb / machine.max_ram_mb) * 100 if machine.max_ram_mb > 0 else 0
            instance_pct = (instances_on_machine / machine.max_instances) * 100 if machine.max_instances > 0 else 0

            machine_reports.append({
                "machine_id": str(machine.id),
                "hostname": machine.hostname,
                "status": machine.status.value,
                "instances": instances_on_machine,
                "max_instances": machine.max_instances,
                "instance_utilization_pct": round(instance_pct, 2),
                "ram_used_mb": ram_used_mb,
                "ram_pct": round(ram_pct, 2),
                "max_ram_mb": machine.max_ram_mb
            })

        # Calculate imbalance score (std dev of utilization)
        if machine_reports:
            utilizations = [m["ram_pct"] for m in machine_reports]
            avg_util = sum(utilizations) / len(utilizations)
            variance = sum((u - avg_util) ** 2 for u in utilizations) / len(utilizations)
            std_dev = variance ** 0.5
        else:
            avg_util = 0
            std_dev = 0

        imbalance_status = "balanced"
        if std_dev > 30:
            imbalance_status = "high_imbalance"
        elif std_dev > 15:
            imbalance_status = "moderate_imbalance"

        return {
            "total_machines": len(machines),
            "total_instances": total_instances,
            "average_utilization_pct": round(avg_util, 2),
            "utilization_std_dev": round(std_dev, 2),
            "imbalance_status": imbalance_status,
            "machines": machine_reports,
            "recommendation": "No auto-rebalancing implemented. Manual review recommended."
        }
