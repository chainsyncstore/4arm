"""Alerting Service - Telegram + DB alerting."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.alert import Alert, AlertChannel, AlertSeverity
from app.models.stream_log import StreamLog, StreamResult
from app.models.account import Account, AccountStatus
from app.models.instance import Instance, InstanceStatus
from app.models.song import Song, SongStatus
from app.models.proxy import Proxy, ProxyStatus
from app.config import settings

logger = logging.getLogger(__name__)


class AlertingService:
    """Send alerts via Telegram and/or store in DB."""

    def __init__(self, db_session_maker, ws_manager=None):
        self.db_session_maker = db_session_maker
        self.ws_manager = ws_manager
        self.telegram_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', '')
        self._cooldown: dict[str, datetime] = {}

    async def send_alert(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        db: Optional[AsyncSession] = None
    ) -> None:
        """Send alert via multiple channels:
        1. Check cooldown (same title within 5 min → skip)
        2. Store in DB (always)
        3. Send to Telegram (if configured)
        4. Broadcast to WebSocket (if ws_manager available)
        """
        # Check cooldown
        now = datetime.now(timezone.utc)
        cooldown_key = f"{severity.value}:{title}"
        cooldown_minutes = 5

        if cooldown_key in self._cooldown:
            last_sent = self._cooldown[cooldown_key]
            if now - last_sent < timedelta(minutes=cooldown_minutes):
                logger.debug(f"Alert '{title}' skipped due to cooldown")
                return

        self._cooldown[cooldown_key] = now

        # Clean old cooldown entries (older than 1 hour)
        cutoff = now - timedelta(hours=1)
        self._cooldown = {
            k: v for k, v in self._cooldown.items()
            if v > cutoff
        }

        session_created = False
        if db is None:
            async with self.db_session_maker() as db:
                session_created = True
                await self._do_send_alert(db, severity, title, message)
        else:
            await self._do_send_alert(db, severity, title, message)

    async def _do_send_alert(
        self,
        db: AsyncSession,
        severity: AlertSeverity,
        title: str,
        message: str
    ) -> None:
        # Store in DB
        alert = Alert(
            severity=severity,
            channel=AlertChannel.DATABASE,
            title=title,
            message=message
        )
        db.add(alert)
        await db.commit()

        logger.info(f"Alert [{severity.value}] {title}: {message}")

        # Send to Telegram if configured
        if self.telegram_token and self.telegram_chat_id:
            telegram_text = f"🚨 *{severity.value.upper()}*: {title}\n\n{message}"
            await self._send_telegram(telegram_text)

        # Broadcast to WebSocket
        if self.ws_manager:
            await self.ws_manager.broadcast_alert(
                severity.value,
                f"{title}: {message}"
            )

    async def _send_telegram(self, text: str) -> bool:
        """Send via Telegram Bot API. Return False if not configured or fails."""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug("Telegram not configured, skipping")
            return False

        try:
            import httpx
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    logger.debug("Telegram alert sent successfully")
                    return True
                else:
                    logger.warning(f"Telegram API error: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def daily_digest(self, db: AsyncSession) -> str:
        """Generate daily stats summary:
        - Total streams today (success/fail/skipped)
        - Active instances / accounts
        - Songs completed today
        - Accounts banned / in cooldown
        - Top 5 songs by streams today
        - Rate limiter blocks summary

        Return formatted text.
        """
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Streams today
        streams_result = await db.execute(
            select(
                func.count(StreamLog.id).filter(StreamLog.result == StreamResult.SUCCESS),
                func.count(StreamLog.id).filter(StreamLog.result == StreamResult.FAIL),
                func.count(StreamLog.id).filter(StreamLog.result == StreamResult.SHUFFLE_MISS)
            )
            .where(StreamLog.started_at >= today_start)
        )
        success_count, fail_count, shuffle_count = streams_result.one()
        success_count = success_count or 0
        fail_count = fail_count or 0
        shuffle_count = shuffle_count or 0

        # Active instances
        instances_result = await db.execute(
            select(func.count(Instance.id))
            .where(Instance.status == InstanceStatus.RUNNING)
        )
        active_instances = instances_result.scalar() or 0

        # Active accounts
        accounts_result = await db.execute(
            select(func.count(Account.id))
            .where(Account.status == AccountStatus.ACTIVE)
        )
        active_accounts = accounts_result.scalar() or 0

        # Accounts in cooldown
        cooldown_result = await db.execute(
            select(func.count(Account.id))
            .where(
                and_(
                    Account.status == AccountStatus.COOLDOWN,
                    Account.cooldown_until > datetime.now(timezone.utc)
                )
            )
        )
        cooldown_count = cooldown_result.scalar() or 0

        # Banned accounts
        banned_result = await db.execute(
            select(func.count(Account.id))
            .where(Account.status == AccountStatus.BANNED)
        )
        banned_count = banned_result.scalar() or 0

        # Warming accounts
        warming_result = await db.execute(
            select(func.count(Account.id))
            .where(Account.status == AccountStatus.WARMING)
        )
        warming_count = warming_result.scalar() or 0

        # Songs completed today
        songs_completed_result = await db.execute(
            select(func.count(Song.id))
            .where(
                and_(
                    Song.status == SongStatus.COMPLETED,
                    Song.updated_at >= today_start
                )
            )
        )
        songs_completed = songs_completed_result.scalar() or 0

        # Top 5 songs by streams today
        top_songs_result = await db.execute(
            select(Song.title, Song.spotify_uri, Song.streams_today)
            .where(Song.streams_today > 0)
            .order_by(Song.streams_today.desc())
            .limit(5)
        )
        top_songs = top_songs_result.all()

        # Unhealthy proxies
        unhealthy_proxies_result = await db.execute(
            select(func.count(Proxy.id))
            .where(Proxy.status == ProxyStatus.UNHEALTHY)
        )
        unhealthy_proxies = unhealthy_proxies_result.scalar() or 0

        # Format the digest
        lines = [
            "📊 *4ARM Daily Digest*",
            f"📅 {today_start.strftime('%Y-%m-%d')}",
            "",
            "*Streaming Activity:*",
            f"  ✅ Successful: {success_count}",
            f"  ❌ Failed: {fail_count}",
            f"  🔀 Shuffle misses: {shuffle_count}",
            f"  📈 Total: {success_count + fail_count + shuffle_count}",
            "",
            "*Resources:*",
            f"  🖥️ Active instances: {active_instances}",
            f"  👤 Active accounts: {active_accounts}",
            f"  😴 In cooldown: {cooldown_count}",
            f"  🔄 Warming: {warming_count}",
            f"  🚫 Banned: {banned_count}",
            "",
            "*Songs:*",
            f"  🎵 Completed today: {songs_completed}",
        ]

        if top_songs:
            lines.append("  📊 Top songs today:")
            for i, (title, uri, streams) in enumerate(top_songs, 1):
                name = title or uri.split(":")[-1] if ":" in (uri or "") else (uri or "Unknown")
                lines.append(f"    {i}. {name}: {streams} streams")

        lines.extend([
            "",
            "*Infrastructure:*",
            f"  🔌 Unhealthy proxies: {unhealthy_proxies}"
        ])

        return "\n".join(lines)

    async def send_daily_digest(self, db: AsyncSession) -> None:
        """Generate and send the daily digest as an alert."""
        digest = await self.daily_digest(db)

        await self.send_alert(
            severity=AlertSeverity.INFO,
            title="Daily Digest",
            message=digest,
            db=db
        )
