"""Temporary email service using mail.tm API for disposable mailboxes."""

import asyncio
import logging
import random
import string
import re
from typing import Optional
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


class TempMailService:
    """Wraps mail.tm REST API for disposable email management."""

    BASE_URL = "https://api.mail.tm"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_available_domains(self) -> list[str]:
        """Fetch available email domains from mail.tm.
        GET https://api.mail.tm/domains
        Returns list of domain strings like ['mail.tm', 'inbox.fr', ...]
        """
        client = await self._get_client()
        resp = await client.get(f"{self.BASE_URL}/domains")
        resp.raise_for_status()
        data = resp.json()
        # API returns {"hydra:member": [{"domain": "...", ...}, ...]}
        members = data.get("hydra:member", [])
        return [m["domain"] for m in members if m.get("isActive", True)]

    def _random_local_part(self, length: int = 10) -> str:
        """Generate random local part for email: lowercase + digits."""
        chars = string.ascii_lowercase + string.digits
        return ''.join(random.choices(chars, k=length))

    async def create_mailbox(self, address: str = None, password: str = None) -> dict:
        """Create a disposable mailbox.

        If address is None, generates random address using an available domain.
        If password is None, generates random 12-char password.

        Returns: {
            "id": str,          # mail.tm account ID
            "address": str,     # full email address
            "password": str,    # mailbox password
            "token": str        # JWT for reading messages
        }
        """
        client = await self._get_client()

        # Get a domain if no address given
        if not address:
            domains = await self.get_available_domains()
            if not domains:
                raise RuntimeError("No mail.tm domains available")
            domain = random.choice(domains)
            local = self._random_local_part()
            address = f"{local}@{domain}"

        if not password:
            password = ''.join(random.choices(
                string.ascii_letters + string.digits, k=12
            ))

        # Create account
        create_resp = await client.post(
            f"{self.BASE_URL}/accounts",
            json={"address": address, "password": password}
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create mailbox: {create_resp.status_code} {create_resp.text}"
            )
        account_data = create_resp.json()

        # Get auth token
        token_resp = await client.post(
            f"{self.BASE_URL}/token",
            json={"address": address, "password": password}
        )
        if token_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to get mail token: {token_resp.status_code} {token_resp.text}"
            )
        token = token_resp.json().get("token", "")

        logger.info(f"Created temp mailbox: {address}")

        return {
            "id": account_data.get("id", ""),
            "address": address,
            "password": password,
            "token": token
        }

    async def get_messages(self, token: str) -> list[dict]:
        """List messages in inbox.
        GET https://api.mail.tm/messages with Bearer token
        """
        client = await self._get_client()
        resp = await client.get(
            f"{self.BASE_URL}/messages",
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("hydra:member", [])

    async def get_message(self, token: str, message_id: str) -> dict:
        """Get full message content.
        GET https://api.mail.tm/messages/{id}
        """
        client = await self._get_client()
        resp = await client.get(
            f"{self.BASE_URL}/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        resp.raise_for_status()
        return resp.json()

    def extract_otp(self, message_body: str) -> Optional[str]:
        """Extract 6-digit OTP from message text/HTML."""
        match = re.search(r'\b(\d{6})\b', message_body)
        return match.group(1) if match else None

    def extract_verification_link(self, message_body: str) -> Optional[str]:
        """Extract Spotify verification/confirmation link from message."""
        patterns = [
            r'https?://[^\s"<>]*spotify[^\s"<>]*confirm[^\s"<>]*',
            r'https?://[^\s"<>]*spotify[^\s"<>]*verify[^\s"<>]*',
            r'https?://[^\s"<>]*spotify[^\s"<>]*activate[^\s"<>]*',
        ]
        for pattern in patterns:
            match = re.search(pattern, message_body, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    async def wait_for_message(
        self,
        token: str,
        from_contains: str = "spotify",
        timeout_sec: int = 120,
        poll_interval_sec: int = 5
    ) -> Optional[dict]:
        """Poll inbox until a message from a matching sender arrives or timeout.

        Args:
            token: Bearer token for mailbox
            from_contains: substring to match in sender address (case-insensitive)
            timeout_sec: max seconds to wait
            poll_interval_sec: seconds between polls

        Returns: Full message dict or None if timeout
        """
        deadline = asyncio.get_event_loop().time() + timeout_sec

        while asyncio.get_event_loop().time() < deadline:
            try:
                messages = await self.get_messages(token)
                for msg in messages:
                    sender = msg.get("from", {}).get("address", "")
                    if from_contains.lower() in sender.lower():
                        # Fetch full message
                        full = await self.get_message(token, msg["id"])
                        return full
            except Exception as e:
                logger.warning(f"Error polling mailbox: {e}")

            await asyncio.sleep(poll_interval_sec)

        logger.warning(f"Timed out waiting for message from '{from_contains}'")
        return None
