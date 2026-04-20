import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_song(client: AsyncClient):
    """Test creating a new song."""
    response = await client.post("/api/songs/", json={
        "spotify_uri": "spotify:track:1234567890",
        "title": "My Test Song",
        "artist": "Test Artist",
        "album_art_url": "https://example.com/art.jpg",
        "total_target_streams": 5000,
        "daily_rate": 500,
        "priority": "high"
    })

    assert response.status_code == 200
    data = response.json()
    assert data["spotify_uri"] == "spotify:track:1234567890"
    assert data["title"] == "My Test Song"
    assert data["artist"] == "Test Artist"
    assert data["total_target_streams"] == 5000
    assert data["daily_rate"] == 500
    assert data["priority"] == "high"
    assert data["status"] == "active"
    assert data["completed_streams"] == 0
    assert data["progress_pct"] == 0.0


@pytest.mark.asyncio
async def test_create_duplicate_song(client: AsyncClient):
    """Test that creating a song with duplicate URI fails."""
    # Create first song
    await client.post("/api/songs/", json={
        "spotify_uri": "spotify:track:duplicate",
        "total_target_streams": 100,
        "daily_rate": 10
    })

    # Try to create second with same URI
    response = await client.post("/api/songs/", json={
        "spotify_uri": "spotify:track:duplicate",
        "total_target_streams": 200,
        "daily_rate": 20
    })

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_songs(client: AsyncClient, sample_song):
    """Test listing songs with paginated response."""
    response = await client.get("/api/songs/")

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
    # Check that our sample song is in the items list
    assert any(s["id"] == sample_song["id"] for s in data["items"])


@pytest.mark.asyncio
async def test_list_songs_pagination(client: AsyncClient):
    """Test songs pagination with skip and limit."""
    # Create multiple songs
    for i in range(3):
        await client.post("/api/songs/", json={
            "spotify_uri": f"spotify:track:pagination{i}",
            "total_target_streams": 100,
            "daily_rate": 10
        })

    # Test with limit
    response = await client.get("/api/songs/?skip=0&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] >= 3

    # Test with skip
    response = await client.get("/api/songs/?skip=1&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert data["skip"] == 1


@pytest.mark.asyncio
async def test_get_song(client: AsyncClient, sample_song):
    """Test getting a specific song."""
    song_id = sample_song["id"]
    response = await client.get(f"/api/songs/{song_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == song_id
    assert data["spotify_uri"] == sample_song["spotify_uri"]


@pytest.mark.asyncio
async def test_get_nonexistent_song(client: AsyncClient):
    """Test getting a song that doesn't exist."""
    response = await client.get("/api/songs/123e4567-e89b-12d3-a456-426614174000")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_song(client: AsyncClient, sample_song):
    """Test updating a song."""
    song_id = sample_song["id"]

    response = await client.patch(f"/api/songs/{song_id}", json={
        "title": "Updated Title",
        "daily_rate": 200
    })

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["daily_rate"] == 200
    # Other fields should remain unchanged
    assert data["artist"] == sample_song["artist"]


@pytest.mark.asyncio
async def test_pause_resume_song(client: AsyncClient, sample_song):
    """Test pausing and resuming a song."""
    song_id = sample_song["id"]

    # Pause
    response = await client.post(f"/api/songs/{song_id}/pause")
    assert response.status_code == 200
    assert response.json()["status"] == "paused"

    # Resume
    response = await client.post(f"/api/songs/{song_id}/resume")
    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_delete_song(client: AsyncClient, sample_song):
    """Test deleting a song."""
    song_id = sample_song["id"]

    response = await client.delete(f"/api/songs/{song_id}")
    assert response.status_code == 200
    assert "deleted" in response.json()["message"]

    # Verify it's gone
    response = await client.get(f"/api/songs/{song_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_song_eta(client: AsyncClient, sample_song):
    """Test getting song ETA."""
    song_id = sample_song["id"]

    response = await client.get(f"/api/songs/{song_id}/eta")

    assert response.status_code == 200
    data = response.json()
    assert data["song_id"] == song_id
    assert "remaining_streams" in data
    assert "estimated_hours" in data
    assert "based_on_current_rate" in data


@pytest.mark.asyncio
async def test_filter_songs_by_status(client: AsyncClient):
    """Test filtering songs by status."""
    # Create active song
    await client.post("/api/songs/", json={
        "spotify_uri": "spotify:track:active1",
        "total_target_streams": 100,
        "daily_rate": 10,
        "status": "active"
    })

    # Create paused song
    await client.post("/api/songs/", json={
        "spotify_uri": "spotify:track:paused1",
        "total_target_streams": 100,
        "daily_rate": 10,
        "status": "paused"
    })

    # Filter active
    response = await client.get("/api/songs/?status=active")
    assert response.status_code == 200
    data = response.json()
    assert all(s["status"] == "active" for s in data["items"])

    # Filter paused
    response = await client.get("/api/songs/?status=paused")
    assert response.status_code == 200
    data = response.json()
    assert all(s["status"] == "paused" for s in data["items"])
