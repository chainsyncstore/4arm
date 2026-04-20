"""Centralized challenge handling for automation paths."""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.challenge import Challenge, ChallengeType, ChallengeStatus
from app.models.instance import Instance
from app.services.adb_service import ADBService
from app.services.alerting import AlertingService, AlertSeverity
from app.config import settings

if TYPE_CHECKING:
    from app.ws.dashboard import DashboardWebSocketManager

logger = logging.getLogger(__name__)


def _normalize_challenge_type(raw: str) -> ChallengeType:
    """Safely normalize an arbitrary string into a ChallengeType enum."""
    try:
        return ChallengeType(raw)
    except ValueError:
        return ChallengeType.UNKNOWN


async def handle_detected_challenge(
    *,
    db: AsyncSession,
    adb: ADBService,
    device_id: str,
    account: Account,
    instance: Optional[Instance],
    challenge_type: str,
    ws_manager: "DashboardWebSocketManager | None" = None,
) -> Challenge:
    """Create a challenge row, capture screenshot, send alert, and broadcast.

    The AlertingService.send_alert(db=db) call commits the session, which
    immediately persists the challenge row so it acts as the scheduler lock.
    """
    challenge = Challenge(
        account_id=account.id,
        instance_id=instance.id if instance else None,
        type=_normalize_challenge_type(challenge_type),
        status=ChallengeStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(challenge)
    await db.flush()  # get challenge.id before screenshot

    # Capture screenshot
    screenshot_path: Optional[str] = None
    try:
        artifacts_dir = settings.CHALLENGE_ARTIFACTS_DIR
        os.makedirs(artifacts_dir, exist_ok=True)
        output_path = os.path.join(artifacts_dir, f"{challenge.id}.png")
        screenshot_path = await adb.take_screenshot(device_id, output_path)
        if screenshot_path:
            challenge.screenshot_path = screenshot_path
    except Exception as e:
        logger.warning(f"Failed to capture challenge screenshot: {e}")

    # Send alert — this commits the DB session
    try:
        alerting_service = AlertingService(
            db_session_maker=lambda: db,
            ws_manager=ws_manager,
        )
        instance_name = instance.name if instance else "N/A"
        await alerting_service.send_alert(
            severity=AlertSeverity.WARNING,
            title=f"Challenge Detected: {challenge_type}",
            message=(
                f"Account: {account.email}\n"
                f"Instance: {instance_name}\n"
                f"Type: {challenge_type}\n"
                f"Challenge ID: {challenge.id}"
            ),
            db=db,
        )
    except Exception as e:
        logger.warning(f"Failed to send challenge alert: {e}")
        # Ensure the challenge row is persisted even if alerting fails
        try:
            await db.commit()
        except Exception:
            pass

    # Broadcast via WebSocket
    if ws_manager:
        try:
            await ws_manager.broadcast({
                "type": "challenge_detected",
                "payload": {
                    "challenge_id": str(challenge.id),
                    "account_id": str(account.id),
                    "account_email": account.email,
                    "instance_name": instance.name if instance else None,
                    "challenge_type": challenge_type,
                },
            })
        except Exception:
            pass

    return challenge
