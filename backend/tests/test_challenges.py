"""Tests for Challenges API endpoints."""

import os
import uuid
import tempfile
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta

from app.models.account import Account, AccountStatus, AccountType
from app.models.instance import Instance, InstanceStatus
from app.models.challenge import Challenge, ChallengeType, ChallengeStatus


@pytest_asyncio.fixture
async def challenge_fixtures(db_session):
    """Create account, instance, and challenge directly in DB."""
    account = Account(
        id=uuid.uuid4(),
        email="challenge-test@example.com",
        type=AccountType.FREE,
        status=AccountStatus.ACTIVE,
        streams_today=0,
        total_streams=0,
    )
    db_session.add(account)

    instance = Instance(
        id=uuid.uuid4(),
        name="challenge-instance-01",
        status=InstanceStatus.RUNNING,
        ram_limit_mb=2048,
        cpu_cores=2.0,
    )
    db_session.add(instance)
    await db_session.flush()

    challenge = Challenge(
        id=uuid.uuid4(),
        account_id=account.id,
        instance_id=instance.id,
        type=ChallengeType.CAPTCHA,
        status=ChallengeStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db_session.add(challenge)
    await db_session.commit()

    return {"account": account, "instance": instance, "challenge": challenge}


class TestListChallenges:
    """Tests for GET /api/challenges/."""

    @pytest.mark.asyncio
    async def test_list_populates_relationships(self, client, db_session):
        """Listing challenges should populate account_email and instance_name."""
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            account = Account(
                id=uuid.uuid4(),
                email="list-test@example.com",
                type=AccountType.FREE,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
            )
            session.add(account)

            instance = Instance(
                id=uuid.uuid4(),
                name="list-instance-01",
                status=InstanceStatus.RUNNING,
                ram_limit_mb=2048,
                cpu_cores=2.0,
            )
            session.add(instance)
            await session.flush()

            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=account.id,
                instance_id=instance.id,
                type=ChallengeType.CAPTCHA,
                status=ChallengeStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add(challenge)
            await session.commit()

            expected_id = str(challenge.id)
            expected_email = account.email
            expected_name = instance.name

        response = await client.get("/api/challenges/")
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        assert data["skip"] == 0
        assert data["limit"] == 50

        found = [c for c in data["items"] if c["id"] == expected_id]
        assert len(found) == 1
        assert found[0]["account_email"] == expected_email
        assert found[0]["instance_name"] == expected_name


class TestPendingCount:
    """Tests for GET /api/challenges/pending-count."""

    @pytest.mark.asyncio
    async def test_pending_count_only_counts_pending(self, client, db_session):
        """Only challenges with status=pending should be counted."""
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            account = Account(
                id=uuid.uuid4(),
                email="count-test@example.com",
                type=AccountType.FREE,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
            )
            session.add(account)
            await session.flush()

            statuses = [
                ChallengeStatus.PENDING,
                ChallengeStatus.PENDING,
                ChallengeStatus.RESOLVED,
                ChallengeStatus.FAILED,
                ChallengeStatus.EXPIRED,
            ]
            for status in statuses:
                c = Challenge(
                    id=uuid.uuid4(),
                    account_id=account.id,
                    type=ChallengeType.CAPTCHA,
                    status=status,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                )
                if status == ChallengeStatus.RESOLVED:
                    c.resolved_at = datetime.now(timezone.utc)
                session.add(c)

            await session.commit()

        response = await client.get("/api/challenges/pending-count")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2


class TestResolveChallenge:
    """Tests for POST /api/challenges/{id}/resolve."""

    @pytest.mark.asyncio
    async def test_resolve_updates_status_and_notes(self, client, db_session):
        """Resolving a challenge should update status and persist notes."""
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            account = Account(
                id=uuid.uuid4(),
                email="resolve-test@example.com",
                type=AccountType.FREE,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
            )
            session.add(account)
            await session.flush()

            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=account.id,
                type=ChallengeType.EMAIL_VERIFY,
                status=ChallengeStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add(challenge)
            await session.commit()
            challenge_id = str(challenge.id)

        response = await client.post(
            f"/api/challenges/{challenge_id}/resolve",
            json={"action": "resolve", "notes": "Manually solved captcha"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert data["notes"] == "Manually solved captcha"
        assert data["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_skip_sets_expired(self, client, db_session):
        """Skip action should set status to expired."""
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            account = Account(
                id=uuid.uuid4(),
                email="skip-test@example.com",
                type=AccountType.FREE,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
            )
            session.add(account)
            await session.flush()

            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=account.id,
                type=ChallengeType.CAPTCHA,
                status=ChallengeStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add(challenge)
            await session.commit()
            challenge_id = str(challenge.id)

        response = await client.post(
            f"/api/challenges/{challenge_id}/resolve",
            json={"action": "skip"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "expired"

    @pytest.mark.asyncio
    async def test_fail_sets_failed(self, client, db_session):
        """Fail action should set status to failed."""
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            account = Account(
                id=uuid.uuid4(),
                email="fail-test@example.com",
                type=AccountType.FREE,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
            )
            session.add(account)
            await session.flush()

            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=account.id,
                type=ChallengeType.CAPTCHA,
                status=ChallengeStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add(challenge)
            await session.commit()
            challenge_id = str(challenge.id)

        response = await client.post(
            f"/api/challenges/{challenge_id}/resolve",
            json={"action": "fail"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "failed"


class TestScreenshotEndpoint:
    """Tests for GET /api/challenges/{id}/screenshot."""

    @pytest.mark.asyncio
    async def test_screenshot_serves_saved_artifact(self, client, db_session):
        """Screenshot endpoint should serve the saved file."""
        from tests.conftest import TestingSessionLocal

        # Create a real temp screenshot file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # Minimal PNG-like header
            screenshot_path = f.name

        try:
            async with TestingSessionLocal() as session:
                account = Account(
                    id=uuid.uuid4(),
                    email="screenshot-test@example.com",
                    type=AccountType.FREE,
                    status=AccountStatus.ACTIVE,
                    streams_today=0,
                    total_streams=0,
                )
                session.add(account)
                await session.flush()

                challenge = Challenge(
                    id=uuid.uuid4(),
                    account_id=account.id,
                    type=ChallengeType.CAPTCHA,
                    status=ChallengeStatus.PENDING,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                    screenshot_path=screenshot_path,
                )
                session.add(challenge)
                await session.commit()
                challenge_id = str(challenge.id)

            response = await client.get(f"/api/challenges/{challenge_id}/screenshot")
            assert response.status_code == 200
        finally:
            os.unlink(screenshot_path)

    @pytest.mark.asyncio
    async def test_screenshot_404_when_no_path(self, client, db_session):
        """Screenshot endpoint should return 404 when no screenshot_path set."""
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            account = Account(
                id=uuid.uuid4(),
                email="no-ss-test@example.com",
                type=AccountType.FREE,
                status=AccountStatus.ACTIVE,
                streams_today=0,
                total_streams=0,
            )
            session.add(account)
            await session.flush()

            challenge = Challenge(
                id=uuid.uuid4(),
                account_id=account.id,
                type=ChallengeType.CAPTCHA,
                status=ChallengeStatus.PENDING,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                screenshot_path=None,
            )
            session.add(challenge)
            await session.commit()
            challenge_id = str(challenge.id)

        response = await client.get(f"/api/challenges/{challenge_id}/screenshot")
        assert response.status_code == 404
