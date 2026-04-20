import logging
import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.instance import Instance, InstanceStatus
from app.config import settings

logger = logging.getLogger(__name__)


class InstanceManager:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.mock_mode = settings.MOCK_DOCKER

    async def create_instance(
        self,
        name: str,
        ram_limit_mb: int = 2048,
        cpu_cores: float = 2.0
    ) -> Instance:
        """Create a new Redroid + redsocks instance pod.

        After creation, generates and applies a device fingerprint,
        and assigns a behavior profile.
        """
        instance = Instance(
            name=name,
            ram_limit_mb=ram_limit_mb,
            cpu_cores=cpu_cores,
            status=InstanceStatus.CREATING
        )

        if self.mock_mode:
            # Mock Docker operations on Windows
            mock_id = f"mock-{uuid.uuid4().hex[:12]}"
            instance.docker_id = mock_id
            instance.redsocks_container_id = f"redsocks-{mock_id}"
            instance.adb_port = 5555
            instance.status = InstanceStatus.RUNNING
            logger.info(f"MOCK: Created instance {name} with docker_id={mock_id}")
        else:
            # Real Docker operations
            import docker

            docker_client = docker.from_env()

            # 1. Create Redroid container
            redroid = docker_client.containers.run(
                "redroid/redroid:12.0.0-latest",
                name=f"redroid-{name}",
                detach=True,
                mem_limit=f"{ram_limit_mb}m",
                cpu_quota=int(cpu_cores * 100000),
                cpu_period=100000,
                network="4arm-net",
                volumes={f"redroid-{name}-data": {"bind": "/data", "mode": "rw"}},
                environment={
                    "androidboot.hardware": "redroid",
                    "androidboot.redroid_gpu_mode": "guest",
                },
                privileged=True,
                cap_add=["NET_ADMIN"]
            )

            # 2. Create redsocks sidecar (shares network with redroid)
            redsocks = docker_client.containers.run(
                "4arm-redsocks:latest",
                name=f"redsocks-{name}",
                detach=True,
                network_mode=f"container:redroid-{name}",
                cap_add=["NET_ADMIN"],
                environment={
                    "PROXY_HOST": "0.0.0.0",  # No proxy configured yet
                    "PROXY_PORT": "1080",
                    "PROXY_TYPE": "socks5",
                    "PROXY_USER": "",
                    "PROXY_PASS": "",
                }
            )

            # 3. Get ADB port (inspect redroid container network settings)
            redroid.reload()
            ports = redroid.attrs.get("NetworkSettings", {}).get("Ports", {})
            adb_port = None
            if "5555/tcp" in ports:
                adb_port = ports["5555/tcp"][0].get("HostPort") if ports["5555/tcp"] else None

            # 4. Store both IDs
            instance.docker_id = redroid.id
            instance.redsocks_container_id = redsocks.id
            instance.adb_port = int(adb_port) if adb_port else 5555
            instance.status = InstanceStatus.RUNNING

            logger.info(f"Created instance {name}: redroid={redroid.id}, redsocks={redsocks.id}, adb_port={instance.adb_port}")

        self.db.add(instance)
        await self.db.commit()
        await self.db.refresh(instance)

        # Generate and apply fingerprint (lazy import to avoid circular dependency)
        from app.services.adb_service import ADBService
        from app.services.antidetect.fingerprint import FingerprintManager
        from app.services.antidetect.behavior_profiles import BehaviorProfileManager

        adb = ADBService()
        fp_manager = FingerprintManager(adb)

        device_id = f"localhost:{instance.adb_port}" if instance.adb_port else "localhost:5555"
        fingerprint = await fp_manager.generate_fingerprint()
        await fp_manager.apply_fingerprint(device_id, fingerprint)
        await fp_manager.store_fingerprint(instance.id, fingerprint, self.db)

        # Assign behavior profile
        bp_manager = BehaviorProfileManager()
        profile_name = await bp_manager.assign_profile(instance.id, self.db)
        instance.behavior_profile = profile_name

        await self.db.commit()
        await self.db.refresh(instance)

        return instance

    async def start_instance(self, instance_id: uuid.UUID) -> Instance:
        """Start a stopped instance."""
        result = await self.db.execute(select(Instance).where(Instance.id == instance_id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        if self.mock_mode:
            logger.info(f"MOCK: Starting instance {instance.name}")
            instance.status = InstanceStatus.RUNNING
        else:
            # Real Docker start
            import docker
            docker_client = docker.from_env()

            try:
                if instance.docker_id:
                    redroid = docker_client.containers.get(instance.docker_id)
                    redroid.start()
                if instance.redsocks_container_id:
                    redsocks = docker_client.containers.get(instance.redsocks_container_id)
                    redsocks.start()
                instance.status = InstanceStatus.RUNNING
                logger.info(f"Started instance {instance.name}")
            except docker.errors.NotFound as e:
                logger.error(f"Container not found: {e}")
                instance.status = InstanceStatus.ERROR

        await self.db.commit()
        await self.db.refresh(instance)
        return instance

    async def stop_instance(self, instance_id: uuid.UUID) -> Instance:
        """Stop a running instance."""
        result = await self.db.execute(select(Instance).where(Instance.id == instance_id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        if self.mock_mode:
            logger.info(f"MOCK: Stopping instance {instance.name}")
            instance.status = InstanceStatus.STOPPED
        else:
            # Real Docker stop
            import docker
            docker_client = docker.from_env()

            try:
                if instance.redsocks_container_id:
                    try:
                        redsocks = docker_client.containers.get(instance.redsocks_container_id)
                        redsocks.stop(timeout=30)
                    except docker.errors.NotFound:
                        pass
                if instance.docker_id:
                    try:
                        redroid = docker_client.containers.get(instance.docker_id)
                        redroid.stop(timeout=30)
                    except docker.errors.NotFound:
                        pass
                instance.status = InstanceStatus.STOPPED
                logger.info(f"Stopped instance {instance.name}")
            except Exception as e:
                logger.error(f"Error stopping instance: {e}")
                raise

        await self.db.commit()
        await self.db.refresh(instance)
        return instance

    async def restart_instance(self, instance_id: uuid.UUID) -> Instance:
        """Restart an instance."""
        await self.stop_instance(instance_id)
        return await self.start_instance(instance_id)

    async def destroy_instance(self, instance_id: uuid.UUID) -> bool:
        """Destroy an instance permanently."""
        result = await self.db.execute(select(Instance).where(Instance.id == instance_id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        if self.mock_mode:
            logger.info(f"MOCK: Destroying instance {instance.name}")
        else:
            # Real Docker destroy
            import docker
            docker_client = docker.from_env()

            try:
                if instance.redsocks_container_id:
                    try:
                        redsocks = docker_client.containers.get(instance.redsocks_container_id)
                        redsocks.stop(timeout=10)
                        redsocks.remove(force=True)
                        logger.info(f"Removed redsocks container {instance.redsocks_container_id}")
                    except docker.errors.NotFound:
                        pass

                if instance.docker_id:
                    try:
                        redroid = docker_client.containers.get(instance.docker_id)
                        redroid.stop(timeout=10)
                        redroid.remove(force=True, v=True)
                        logger.info(f"Removed redroid container {instance.docker_id}")
                    except docker.errors.NotFound:
                        pass
            except Exception as e:
                logger.error(f"Error destroying instance: {e}")
                raise

        await self.db.delete(instance)
        await self.db.commit()
        return True

    async def assign_account(self, instance_id: uuid.UUID, account_id: uuid.UUID) -> Instance:
        """Assign an account to an instance."""
        result = await self.db.execute(select(Instance).where(Instance.id == instance_id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        instance.assigned_account_id = account_id
        await self.db.commit()
        await self.db.refresh(instance)
        logger.info(f"Assigned account {account_id} to instance {instance.name}")
        return instance

    async def unassign_account(self, instance_id: uuid.UUID) -> Instance:
        """Remove account assignment from an instance."""
        result = await self.db.execute(select(Instance).where(Instance.id == instance_id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")

        instance.assigned_account_id = None
        await self.db.commit()
        await self.db.refresh(instance)
        logger.info(f"Unassigned account from instance {instance.name}")
        return instance
