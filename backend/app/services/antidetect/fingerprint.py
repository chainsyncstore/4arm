"""FingerprintManager — generates and applies per-instance device identities."""

import logging
import random
import uuid as _uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.fingerprint import DeviceFingerprint
from app.services.adb_service import ADBService

logger = logging.getLogger(__name__)


class FingerprintManager:
    """Generates and applies per-instance device fingerprints."""

    DEVICE_MODELS = [
        {
            "model": "SM-G998B", "brand": "samsung", "manufacturer": "samsung",
            "device": "o1s", "product": "o1sxeea",
            "fingerprint": "samsung/o1sxeea/o1s:12/SP1A.210812.016/G998BXXU5CVJA:user/release-keys",
            "densities": [420, 560],
        },
        {
            "model": "SM-S908B", "brand": "samsung", "manufacturer": "samsung",
            "device": "b0s", "product": "b0sxeea",
            "fingerprint": "samsung/b0sxeea/b0s:13/TP1A.220624.014/S908BXXU3CWA1:user/release-keys",
            "densities": [420, 560],
        },
        {
            "model": "SM-A536B", "brand": "samsung", "manufacturer": "samsung",
            "device": "a53x", "product": "a53xeea",
            "fingerprint": "samsung/a53xeea/a53x:13/TP1A.220624.014/A536BXXU5CWD1:user/release-keys",
            "densities": [420],
        },
        {
            "model": "Pixel 7", "brand": "google", "manufacturer": "Google",
            "device": "panther", "product": "panther",
            "fingerprint": "google/panther/panther:13/TQ3A.230705.001/10216780:user/release-keys",
            "densities": [420],
        },
        {
            "model": "Pixel 6a", "brand": "google", "manufacturer": "Google",
            "device": "bluejay", "product": "bluejay",
            "fingerprint": "google/bluejay/bluejay:13/TQ3A.230705.001/10216780:user/release-keys",
            "densities": [420],
        },
        {
            "model": "Pixel 8 Pro", "brand": "google", "manufacturer": "Google",
            "device": "husky", "product": "husky",
            "fingerprint": "google/husky/husky:14/UD1A.230803.041/10808477:user/release-keys",
            "densities": [420, 560],
        },
        {
            "model": "22101316G", "brand": "Xiaomi", "manufacturer": "Xiaomi",
            "device": "marble", "product": "marble_global",
            "fingerprint": "Xiaomi/marble_global/marble:13/TKQ1.221114.001/V14.0.6.0.TMRMIXM:user/release-keys",
            "densities": [420],
        },
        {
            "model": "2201117TG", "brand": "Xiaomi", "manufacturer": "Xiaomi",
            "device": "vili", "product": "vili_global",
            "fingerprint": "Xiaomi/vili_global/vili:13/RKQ1.211001.001/V14.0.4.0.TKDMIXM:user/release-keys",
            "densities": [420, 480],
        },
        {
            "model": "CPH2451", "brand": "OPPO", "manufacturer": "OPPO",
            "device": "OP5913L1", "product": "OP5913L1",
            "fingerprint": "OPPO/CPH2451/OP5913L1:13/TP1A.220905.001/R.10e7a2e-1:user/release-keys",
            "densities": [420],
        },
        {
            "model": "CPH2271", "brand": "OPPO", "manufacturer": "OPPO",
            "device": "OP4F2F", "product": "OP4F2F",
            "fingerprint": "OPPO/CPH2271/OP4F2F:13/TP1A.220905.001/R.127f930-1:user/release-keys",
            "densities": [480],
        },
        {
            "model": "LE2125", "brand": "OnePlus", "manufacturer": "OnePlus",
            "device": "OnePlus9Pro", "product": "OnePlus9Pro",
            "fingerprint": "OnePlus/OnePlus9Pro/OnePlus9Pro:13/TP1A.220905.001/R.1234567-1:user/release-keys",
            "densities": [420, 560],
        },
        {
            "model": "NE2215", "brand": "OnePlus", "manufacturer": "OnePlus",
            "device": "OnePlus10Pro", "product": "OnePlus10Pro",
            "fingerprint": "OnePlus/OnePlus10Pro/OnePlus10Pro:13/TP1A.220905.001/R.7654321-1:user/release-keys",
            "densities": [420, 560],
        },
        {
            "model": "V2217A", "brand": "vivo", "manufacturer": "vivo",
            "device": "V2217A", "product": "V2217A",
            "fingerprint": "vivo/V2217A/V2217A:13/TP1A.220624.014/compiler0912194801:user/release-keys",
            "densities": [480],
        },
        {
            "model": "M2101K6G", "brand": "Redmi", "manufacturer": "Xiaomi",
            "device": "alioth", "product": "alioth_global",
            "fingerprint": "Redmi/alioth_global/alioth:13/RKQ1.210614.002/V14.0.3.0.TKHMIXM:user/release-keys",
            "densities": [420],
        },
        {
            "model": "moto g82 5G", "brand": "motorola", "manufacturer": "motorola",
            "device": "rhodei", "product": "rhodei_g",
            "fingerprint": "motorola/rhodei_g/rhodei:13/T1SRS33.72-20-10-3/c4a51:user/release-keys",
            "densities": [420],
        },
    ]

    LOCALE_WEIGHTS = [
        ("en_US", 40), ("en_GB", 15), ("de_DE", 10), ("fr_FR", 10),
        ("es_ES", 8), ("pt_BR", 7), ("nl_NL", 3), ("it_IT", 3),
        ("sv_SE", 2), ("ja_JP", 2),
    ]

    TIMEZONE_MAP = {
        "en_US": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"],
        "en_GB": ["Europe/London"],
        "de_DE": ["Europe/Berlin"],
        "fr_FR": ["Europe/Paris"],
        "es_ES": ["Europe/Madrid"],
        "pt_BR": ["America/Sao_Paulo"],
        "nl_NL": ["Europe/Amsterdam"],
        "it_IT": ["Europe/Rome"],
        "sv_SE": ["Europe/Stockholm"],
        "ja_JP": ["Asia/Tokyo"],
    }

    def __init__(self, adb: ADBService | None = None):
        self.adb = adb or ADBService()
        self.mock_mode = settings.MOCK_ADB

    async def generate_fingerprint(self) -> dict:
        """Generate a unique device profile with randomised identifiers."""
        device = random.choice(self.DEVICE_MODELS)

        locales, weights = zip(*self.LOCALE_WEIGHTS)
        locale = random.choices(locales, weights=weights, k=1)[0]

        tz_options = self.TIMEZONE_MAP.get(locale, ["UTC"])
        timezone = random.choice(tz_options)

        density = random.choice(device.get("densities", [420]))

        return {
            "android_id": _uuid.uuid4().hex[:16],
            "device_model": device["model"],
            "device_brand": device["brand"],
            "device_manufacturer": device["manufacturer"],
            "build_fingerprint": device["fingerprint"],
            "gsfid": str(random.randint(10**18, 10**19 - 1)),
            "screen_density": density,
            "locale": locale,
            "timezone": timezone,
            "advertising_id": str(_uuid.uuid4()),
        }

    async def apply_fingerprint(self, device_id: str, fingerprint: dict) -> bool:
        """Apply fingerprint to a Redroid instance via ADB."""
        if self.mock_mode:
            logger.info(
                f"MOCK: apply_fingerprint device={device_id} "
                f"model={fingerprint['device_model']} brand={fingerprint['device_brand']} "
                f"android_id={fingerprint['android_id']} locale={fingerprint['locale']}"
            )
            return True

        try:
            await self.adb.input_text(
                device_id,
                f"settings put secure android_id {fingerprint['android_id']}"
            )
            await self.adb.input_text(
                device_id,
                f"setprop ro.product.model {fingerprint['device_model']}"
            )
            await self.adb.input_text(
                device_id,
                f"setprop ro.product.brand {fingerprint['device_brand']}"
            )
            await self.adb.input_text(
                device_id,
                f"setprop ro.product.manufacturer {fingerprint['device_manufacturer']}"
            )
            await self.adb.input_text(
                device_id,
                f"settings put secure advertising_id {fingerprint['advertising_id']}"
            )
            logger.info(f"Applied fingerprint to device {device_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply fingerprint to {device_id}: {e}")
            return False

    async def store_fingerprint(
        self, instance_id: _uuid.UUID, fingerprint: dict, db: AsyncSession
    ) -> None:
        """Persist fingerprint to the device_fingerprints table."""
        existing = await self.get_fingerprint(instance_id, db)
        if existing:
            for key, value in fingerprint.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            logger.info(f"Updated existing fingerprint for instance {instance_id}")
        else:
            fp = DeviceFingerprint(
                instance_id=instance_id,
                **fingerprint,
            )
            db.add(fp)
            logger.info(f"Stored new fingerprint for instance {instance_id}")

        await db.flush()

    async def get_fingerprint(
        self, instance_id: _uuid.UUID, db: AsyncSession
    ) -> Optional[DeviceFingerprint]:
        """Retrieve stored fingerprint for an instance."""
        result = await db.execute(
            select(DeviceFingerprint).where(
                DeviceFingerprint.instance_id == instance_id
            )
        )
        return result.scalar_one_or_none()
