"""Automated Spotify account registration using temp mail + ADB."""

import asyncio
import logging
import random
import re
import string
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType, AccountStatus
from app.schemas.account import AccountCreate
from app.services.tempmail_service import TempMailService
from app.services.adb_service import ADBService
from app.services.automation.spotify_controller import SpotifyController
from app.models.alert import AlertSeverity
from app.config import settings

logger = logging.getLogger(__name__)


class RegistrationService:
    """End-to-end Spotify account registration."""

    def __init__(
        self,
        tempmail: TempMailService,
        adb: ADBService,
        spotify: SpotifyController,
        db_session_maker,
        alerting=None,
        proxy_provider=None  # Will be wired in Prompt 4
    ):
        self.tempmail = tempmail
        self.adb = adb
        self.spotify = spotify
        self.db_session_maker = db_session_maker
        self.alerting = alerting
        self.proxy_provider = proxy_provider
        self.mock_mode = settings.REGISTRATION_MOCK

    def _random_password(self, length: int = 14) -> str:
        """Generate a random Spotify-compatible password."""
        chars = string.ascii_letters + string.digits
        return ''.join(random.choices(chars, k=length))

    def _random_display_name(self) -> str:
        """Generate a plausible display name."""
        first_names = [
            "Alex", "Jordan", "Sam", "Chris", "Morgan", "Taylor", "Casey",
            "Riley", "Quinn", "Avery", "Jamie", "Drew", "Skyler", "Dakota"
        ]
        last_initials = list(string.ascii_uppercase)
        return f"{random.choice(first_names)} {random.choice(last_initials)}."

    def _random_dob(self) -> dict:
        """Generate random date of birth (age 18-35)."""
        now = datetime.now(timezone.utc)
        year = random.randint(now.year - 35, now.year - 18)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        return {"year": year, "month": month, "day": day}

    def _extract_message_body(self, message: dict) -> str:
        body = message.get("text", "")
        if body:
            return body

        html_body = message.get("html", "")
        if isinstance(html_body, list):
            return "\n".join(part for part in html_body if isinstance(part, str))
        if isinstance(html_body, str):
            return html_body
        return ""

    def _parse_bounds(self, bounds: str) -> Optional[tuple[int, int]]:
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
        if not match:
            return None
        x1, y1, x2, y2 = map(int, match.groups())
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def _find_node_center(self, xml: str, patterns: list[str]) -> Optional[tuple[int, int]]:
        if not xml:
            return None

        normalized_patterns = [pattern.lower() for pattern in patterns]
        for node_match in re.finditer(r"<node\b([^>]*)/?>", xml):
            attrs = node_match.group(1)
            text_match = re.search(r'text="([^"]*)"', attrs)
            desc_match = re.search(r'content-desc="([^"]*)"', attrs)
            resource_match = re.search(r'resource-id="([^"]*)"', attrs)
            candidate_text = " ".join(filter(None, [
                text_match.group(1) if text_match else "",
                desc_match.group(1) if desc_match else "",
                resource_match.group(1) if resource_match else "",
            ])).lower()

            if not any(pattern in candidate_text for pattern in normalized_patterns):
                continue

            bounds_match = re.search(r'bounds="(\[[^\"]+\]\[[^\"]+\])"', attrs)
            if not bounds_match:
                continue

            center = self._parse_bounds(bounds_match.group(1))
            if center:
                return center

        return None

    async def _tap_target(
        self,
        device_id: str,
        patterns: list[str],
        fallbacks: list[tuple[int, int]],
        use_fallbacks: bool = True,
    ) -> bool:
        xml = await self.adb.get_screen_xml(device_id)
        center = self._find_node_center(xml, patterns)
        candidates: list[tuple[int, int]] = []
        if center:
            candidates.append(center)
        if use_fallbacks:
            candidates.extend(fallbacks)

        for x, y in candidates:
            if await self.adb.tap(device_id, x, y):
                await asyncio.sleep(1)
                return True

        return False

    async def _fill_text_field(
        self,
        device_id: str,
        value: str,
        patterns: list[str],
        fallbacks: list[tuple[int, int]],
        field_name: str,
    ) -> None:
        focused = await self._tap_target(device_id, patterns, fallbacks)
        if not focused:
            raise RuntimeError(f"Could not focus {field_name} field")

        await self.adb.send_keyevent(device_id, 123)
        for _ in range(24):
            await self.adb.send_keyevent(device_id, 67)

        if not await self.adb.input_text(device_id, value):
            raise RuntimeError(f"Failed to input {field_name}")
        await asyncio.sleep(1)

    async def _fill_dob(self, device_id: str, dob: dict) -> None:
        day = str(dob["day"])
        month = f"{dob['month']:02d}"
        year = str(dob["year"])

        day_focused = await self._tap_target(device_id, ["day"], [(220, 1040), (220, 1140)])
        if day_focused:
            if not await self.adb.input_text(device_id, day):
                raise RuntimeError("Failed to input day of birth")

            month_focused = await self._tap_target(device_id, ["month"], [(540, 1040), (540, 1140)])
            if not month_focused or not await self.adb.input_text(device_id, month):
                raise RuntimeError("Failed to input month of birth")

            year_focused = await self._tap_target(device_id, ["year"], [(860, 1040), (860, 1140)])
            if not year_focused or not await self.adb.input_text(device_id, year):
                raise RuntimeError("Failed to input year of birth")
            await asyncio.sleep(1)
            return

        await self._fill_text_field(
            device_id,
            f"{month}{day}{year}",
            ["date of birth", "birthday", "dob"],
            [(540, 1100)],
            "date of birth",
        )

    async def _complete_signup_flow(
        self,
        device_id: str,
        email: str,
        password: str,
        display_name: str,
        dob: dict,
    ) -> None:
        if not await self.spotify.launch_spotify(device_id):
            raise RuntimeError("Failed to launch Spotify")

        await asyncio.sleep(3)

        opened_signup = await self._tap_target(
            device_id,
            ["sign up free", "sign up", "create account", "create free account"],
            [(540, 1700), (540, 1560)],
        )
        if not opened_signup:
            raise RuntimeError("Failed to open Spotify sign-up flow")

        await self._tap_target(
            device_id,
            ["continue with email", "use email", "sign up with email"],
            [(540, 1440)],
            use_fallbacks=False,
        )

        await self._fill_text_field(
            device_id,
            email,
            ["email address", "email"],
            [(540, 760), (540, 860)],
            "email",
        )

        if not await self._tap_target(device_id, ["next", "continue"], [(540, 1700)]):
            raise RuntimeError("Failed to continue after email entry")

        await self._fill_text_field(
            device_id,
            password,
            ["create a password", "password"],
            [(540, 900), (540, 1000)],
            "password",
        )

        if not await self._tap_target(device_id, ["next", "continue"], [(540, 1700)]):
            raise RuntimeError("Failed to continue after password entry")

        await self._fill_dob(device_id, dob)

        if not await self._tap_target(device_id, ["next", "continue"], [(540, 1700)]):
            raise RuntimeError("Failed to continue after date of birth entry")

        await self._tap_target(
            device_id,
            ["prefer not to say", "other", "male", "female"],
            [(540, 1340)],
            use_fallbacks=False,
        )

        await self._fill_text_field(
            device_id,
            display_name,
            ["what should we call you", "display name", "name"],
            [(540, 980), (540, 1120)],
            "display name",
        )

        await self._tap_target(
            device_id,
            ["i agree", "terms", "privacy policy"],
            [(120, 1540)],
            use_fallbacks=False,
        )

        submitted = await self._tap_target(
            device_id,
            ["create account", "sign up", "done"],
            [(540, 1740)],
        )
        if not submitted:
            raise RuntimeError("Failed to submit Spotify sign-up form")

        await asyncio.sleep(5)

    async def _complete_email_verification(
        self,
        device_id: str,
        otp: Optional[str],
        link: Optional[str],
    ) -> None:
        if otp:
            await self._tap_target(
                device_id,
                ["verification code", "enter code", "code"],
                [(540, 980)],
            )
            if not await self.adb.input_text(device_id, otp):
                raise RuntimeError("Failed to input Spotify verification code")

            confirmed = await self._tap_target(
                device_id,
                ["verify", "confirm", "continue", "done"],
                [(540, 1700)],
            )
            if not confirmed:
                await self.adb.send_keyevent(device_id, 66)
            await asyncio.sleep(4)
        elif link:
            if not await self.adb.launch_url(device_id, link):
                raise RuntimeError("Failed to open Spotify verification link")
            await asyncio.sleep(6)
        else:
            raise RuntimeError("No OTP or verification link found in email")

        if not await self.spotify.launch_spotify(device_id):
            raise RuntimeError("Failed to return to Spotify after verification")
        await asyncio.sleep(3)

    async def register_account(
        self,
        db: AsyncSession,
        instance_id: Optional[UUID] = None,
        device_id: Optional[str] = None
    ) -> Account:
        """Full automated registration flow.

        Steps:
        1. Create temp mailbox via mail.tm
        2. Generate Spotify password + display name
        3. (Real mode) Drive Spotify signup via ADB on target instance
        4. Wait for verification email
        5. Extract OTP or verification link
        6. (Real mode) Complete verification via ADB
        7. Create Account record in DB (type=FREE, status=NEW)
        8. Extract and persist session blob
        9. Return Account

        In mock mode: skips ADB steps, simulates the flow with delays.
        """
        logger.info("Starting automated account registration...")

        # Step 1: Create temp mailbox
        try:
            mailbox = await self.tempmail.create_mailbox()
        except Exception as e:
            logger.error(f"Failed to create temp mailbox: {e}")
            raise RuntimeError(f"Temp mail creation failed: {e}")

        email = mailbox["address"]
        mail_token = mailbox["token"]
        spotify_password = self._random_password()
        display_name = self._random_display_name()
        dob = self._random_dob()

        logger.info(f"Temp mailbox created: {email}")

        if self.mock_mode:
            # Simulate registration with delays
            logger.info(f"MOCK: Registering {email} on Spotify (simulated)")
            await asyncio.sleep(random.uniform(2, 5))
            logger.info(f"MOCK: Registration form submitted for {email}")
            await asyncio.sleep(random.uniform(1, 3))
            logger.info(f"MOCK: Verification completed for {email}")
        else:
            # Real ADB-driven registration
            if not device_id:
                raise RuntimeError("device_id required for real registration")

            await self._complete_signup_flow(
                device_id=device_id,
                email=email,
                password=spotify_password,
                display_name=display_name,
                dob=dob,
            )

            # Wait for verification email
            logger.info(f"Waiting for Spotify verification email at {email}...")
            message = await self.tempmail.wait_for_message(
                token=mail_token,
                from_contains="spotify",
                timeout_sec=120
            )

            if not message:
                raise RuntimeError(f"No verification email received for {email} within timeout")

            body = self._extract_message_body(message)

            otp = self.tempmail.extract_otp(body)
            link = self.tempmail.extract_verification_link(body)

            if otp or link:
                logger.info(f"Verification artifact extracted for {email}")

            await self._complete_email_verification(device_id, otp=otp, link=link)

        session_path = None
        if not self.mock_mode and device_id:
            try:
                session_path = await self.adb.extract_session(device_id)
            except Exception as e:
                raise RuntimeError(f"Session extraction failed for {email}: {e}") from e

            if not session_path:
                raise RuntimeError(f"Session extraction failed for {email}")

        # Step 7: Create Account in DB only after successful registration
        account = Account(
            email=email,
            password_plain=spotify_password,
            display_name=display_name,
            type=AccountType.FREE,
            status=AccountStatus.NEW,
            session_blob_path=session_path,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)

        if session_path:
            logger.info(f"Session extracted for {email}: {session_path}")

        logger.info(f"Account registered: {email} (id={account.id})")

        # Alert success
        if self.alerting:
            await self.alerting.send_alert(
                severity=AlertSeverity.INFO,
                title="Account registered",
                message=f"Auto-registered: {email}",
                db=db
            )

        return account

    async def register_batch(
        self,
        db: AsyncSession,
        count: int,
        instance_ids: Optional[list[UUID]] = None
    ) -> dict:
        """Register multiple accounts with delays between each.

        Respects settings: daily_account_creation_cap, creation_delay_min_sec,
        creation_delay_max_sec.

        In real mode, requires instance_ids to be provided for device context.

        Returns: {"registered": int, "failed": int, "accounts": [account_ids]}
        """
        from app.models.setting import Setting
        from app.models.instance import Instance
        from sqlalchemy import select

        # Read settings
        async def get_setting(key: str, default: int) -> int:
            result = await db.execute(select(Setting).where(Setting.key == key))
            setting = result.scalar_one_or_none()
            return int(setting.value) if setting else default

        daily_cap = await get_setting("daily_account_creation_cap", 20)
        delay_min = await get_setting("creation_delay_min_sec", 30)
        delay_max = await get_setting("creation_delay_max_sec", 120)

        # Respect cap
        actual_count = min(count, daily_cap)
        if actual_count < count:
            logger.warning(
                f"Requested {count} registrations but daily cap is {daily_cap}, "
                f"creating {actual_count}"
            )

        # In real mode, validate we have instance context
        instances = []
        if not self.mock_mode:
            if not instance_ids:
                raise RuntimeError("instance_ids required for real-mode batch registration")

            # Fetch instances and build device_id mapping
            for inst_id in instance_ids[:actual_count]:
                result = await db.execute(
                    select(Instance).where(Instance.id == inst_id)
                )
                instance = result.scalar_one_or_none()
                if not instance:
                    raise RuntimeError(f"Instance {inst_id} not found")
                if not instance.adb_port:
                    raise RuntimeError(f"Instance {inst_id} has no adb_port configured")
                instances.append(instance)

            if len(instances) < actual_count:
                # Cycle through available instances if fewer than requested count
                while len(instances) < actual_count:
                    instances.extend(instances[:actual_count - len(instances)])

        registered = 0
        failed = 0
        account_ids = []

        for i in range(actual_count):
            try:
                logger.info(f"Registering account {i + 1}/{actual_count}...")

                # Prepare device context for real mode
                instance = None
                device_id = None
                if not self.mock_mode and instances:
                    instance = instances[i % len(instances)]
                    device_id = f"localhost:{instance.adb_port}"

                account = await self.register_account(
                    db,
                    instance_id=instance.id if instance else None,
                    device_id=device_id
                )

                # Auto-provision proxy if provider available (wired in Prompt 4)
                if self.proxy_provider:
                    try:
                        proxy = await self.proxy_provider.provision_proxy()
                        account.proxy_id = proxy.id
                        await db.commit()
                        logger.info(f"Proxy provisioned for {account.email}: {proxy.id}")
                    except Exception as e:
                        logger.warning(f"Failed to provision proxy for {account.email}: {e}")

                registered += 1
                account_ids.append(str(account.id))

            except Exception as e:
                logger.error(f"Registration {i + 1}/{actual_count} failed: {e}")
                failed += 1

            # Delay between registrations (except last)
            if i < actual_count - 1:
                delay = random.randint(delay_min, delay_max)
                logger.info(f"Waiting {delay}s before next registration...")
                await asyncio.sleep(delay)

        return {
            "registered": registered,
            "failed": failed,
            "accounts": account_ids,
            "capped_at": actual_count if actual_count < count else None
        }
