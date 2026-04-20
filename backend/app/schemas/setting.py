from typing import Dict, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class SettingBase(BaseModel):
    key: str
    value: str
    description: Optional[str] = None


class SettingResponse(SettingBase):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime


class SettingsResponse(BaseModel):
    settings: Dict[str, str]


class SettingsUpdate(BaseModel):
    settings: Dict[str, str]
