"""Remote Docker Client - Docker operations on remote hosts."""

import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class RemoteDockerClient:
    """Client for Docker operations on remote hosts."""

    def __init__(self, docker_host: str):
        self.docker_host = docker_host
        self.mock_mode = settings.MOCK_DOCKER

    async def ping(self) -> bool:
        """Check if Docker daemon is reachable."""
        if self.mock_mode:
            logger.debug(f"MOCK: Docker ping to {self.docker_host} (always succeeds)")
            return True

        try:
            import docker
            client = docker.DockerClient(base_url=self.docker_host)
            return client.ping()
        except Exception as e:
            logger.warning(f"Docker ping failed for {self.docker_host}: {e}")
            return False

    async def list_containers(self) -> list[dict]:
        """List containers on remote host."""
        if self.mock_mode:
            logger.debug(f"MOCK: Listing containers on {self.docker_host}")
            return [
                {"id": "mock-1", "name": "redroid-mock-1", "status": "running"},
                {"id": "mock-2", "name": "redsocks-mock-1", "status": "running"}
            ]

        try:
            import docker
            client = docker.DockerClient(base_url=self.docker_host)
            containers = client.containers.list()
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status
                }
                for c in containers
            ]
        except Exception as e:
            logger.error(f"Failed to list containers on {self.docker_host}: {e}")
            return []

    async def create_container(
        self,
        image: str,
        name: str,
        **kwargs
    ) -> Optional[str]:
        """Create a container on remote host."""
        if self.mock_mode:
            import uuid
            mock_id = f"mock-{uuid.uuid4().hex[:12]}"
            logger.info(f"MOCK: Created container {name} with ID {mock_id}")
            return mock_id

        try:
            import docker
            client = docker.DockerClient(base_url=self.docker_host)
            container = client.containers.run(image, name=name, detach=True, **kwargs)
            return container.id
        except Exception as e:
            logger.error(f"Failed to create container on {self.docker_host}: {e}")
            return None

    async def stop_container(self, container_id: str) -> bool:
        """Stop a container on remote host."""
        if self.mock_mode:
            logger.info(f"MOCK: Stopped container {container_id}")
            return True

        try:
            import docker
            client = docker.DockerClient(base_url=self.docker_host)
            container = client.containers.get(container_id)
            container.stop()
            return True
        except Exception as e:
            logger.error(f"Failed to stop container {container_id}: {e}")
            return False

    async def remove_container(self, container_id: str) -> bool:
        """Remove a container on remote host."""
        if self.mock_mode:
            logger.info(f"MOCK: Removed container {container_id}")
            return True

        try:
            import docker
            client = docker.DockerClient(base_url=self.docker_host)
            container = client.containers.get(container_id)
            container.remove(force=True)
            return True
        except Exception as e:
            logger.error(f"Failed to remove container {container_id}: {e}")
            return False

    async def get_stats(self) -> dict:
        """Get Docker daemon stats."""
        if self.mock_mode:
            return {
                "containers_running": 2,
                "containers_total": 5,
                "images": 3,
                "cpu_pct": 35.5,
                "ram_pct": 42.0
            }

        try:
            import docker
            client = docker.DockerClient(base_url=self.docker_host)
            info = client.info()
            return {
                "containers_running": info.get("ContainersRunning", 0),
                "containers_total": info.get("Containers", 0),
                "images": info.get("Images", 0),
                "cpu_pct": None,  # Would need cAdvisor or similar
                "ram_pct": None
            }
        except Exception as e:
            logger.error(f"Failed to get stats from {self.docker_host}: {e}")
            return {}
