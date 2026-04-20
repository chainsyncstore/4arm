from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+asyncpg://4arm:4arm_dev_password@localhost:5432/4arm"
    REDIS_URL: str = "redis://localhost:6379/0"
    MOCK_DOCKER: bool = True
    MOCK_ADB: bool = True
    SECRET_KEY: str = "change-me-in-production"
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    LOG_LEVEL: str = "DEBUG"

    # Phase 7: Scaling & Monitoring
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    CLUSTER_ENABLED: bool = False

    # Phase 8: Auto-registration
    TEMPMAIL_ENABLED: bool = True
    REGISTRATION_MOCK: bool = True  # If True, skip real ADB steps during registration

    # Phase 8: Proxy provider
    PROXY_PROVIDER: str = "webshare"  # "webshare" or "manual" (manual = legacy behavior)
    WEBSHARE_API_KEY: str = ""
    PROXY_COUNTRY: str = ""  # Default country code (e.g., "US"), empty = any
    PROXY_AUTO_PROVISION: bool = True  # Auto-provision on account creation

    # Challenge artifacts
    CHALLENGE_ARTIFACTS_DIR: str = "data/challenges"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [x.strip() for x in v.split(",")]
        return v


settings = Settings()
