import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_instance(client: AsyncClient):
    """Test creating a new instance (mocked)."""
    response = await client.post("/api/instances/", json={
        "name": "instance-001",
        "ram_limit_mb": 2048,
        "cpu_cores": 2.0
    })

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "instance-001"
    assert data["ram_limit_mb"] == 2048
    assert data["cpu_cores"] == 2.0
    assert data["status"] == "running"  # Mock sets it to running
    assert data["docker_id"].startswith("mock-")


@pytest.mark.asyncio
async def test_list_instances(client: AsyncClient, sample_instance):
    """Test listing instances with paginated response."""
    response = await client.get("/api/instances/")

    assert response.status_code == 200
    data = response.json()
    # Verify paginated response structure
    assert "items" in data
    assert "total" in data
    assert "skip" in data
    assert "limit" in data
    assert isinstance(data["items"], list)
    assert data["total"] >= 1
    assert data["skip"] == 0
    assert data["limit"] == 50


@pytest.mark.asyncio
async def test_list_instances_pagination(client: AsyncClient):
    """Test instances pagination with skip and limit."""
    # Create multiple instances
    for i in range(3):
        await client.post("/api/instances/", json={
            "name": f"pagination-test-{i}",
            "ram_limit_mb": 1024,
            "cpu_cores": 1.0
        })

    # Test with limit
    response = await client.get("/api/instances/?skip=0&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] >= 3

    # Test with skip
    response = await client.get("/api/instances/?skip=1&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert data["skip"] == 1


@pytest.mark.asyncio
async def test_get_instance(client: AsyncClient, sample_instance):
    """Test getting a specific instance."""
    instance_id = sample_instance["id"]
    response = await client.get(f"/api/instances/{instance_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == instance_id
    assert data["name"] == sample_instance["name"]


@pytest.mark.asyncio
async def test_stop_start_instance(client: AsyncClient, sample_instance):
    """Test stopping and starting an instance."""
    instance_id = sample_instance["id"]

    # Stop
    response = await client.post(f"/api/instances/{instance_id}/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"

    # Start
    response = await client.post(f"/api/instances/{instance_id}/start")
    assert response.status_code == 200
    assert response.json()["status"] == "running"


@pytest.mark.asyncio
async def test_restart_instance(client: AsyncClient, sample_instance):
    """Test restarting an instance."""
    instance_id = sample_instance["id"]

    response = await client.post(f"/api/instances/{instance_id}/restart")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_assign_unassign_account(client: AsyncClient, sample_instance, sample_account):
    """Test assigning and unassigning an account."""
    instance_id = sample_instance["id"]
    account_id = sample_account["id"]

    # Assign
    response = await client.post(
        f"/api/instances/{instance_id}/assign-account",
        params={"account_id": account_id}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["assigned_account_id"] == account_id

    # Unassign
    response = await client.post(f"/api/instances/{instance_id}/unassign-account")

    assert response.status_code == 200
    data = response.json()
    assert data["assigned_account_id"] is None


@pytest.mark.asyncio
async def test_delete_instance(client: AsyncClient):
    """Test deleting an instance."""
    # Create instance to delete
    response = await client.post("/api/instances/", json={
        "name": "to-delete",
        "ram_limit_mb": 2048,
        "cpu_cores": 2.0
    })
    instance_id = response.json()["id"]

    response = await client.delete(f"/api/instances/{instance_id}")
    assert response.status_code == 200

    # Verify it's gone
    response = await client.get(f"/api/instances/{instance_id}")
    assert response.status_code == 404
