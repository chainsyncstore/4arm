from app.schemas.instance import InstanceCreate, InstanceResponse, InstanceUpdate, PaginatedInstanceResponse
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate, AccountImport
from app.schemas.proxy import ProxyCreate, ProxyResponse, ProxyUpdate, ProxyTestResult
from app.schemas.song import SongCreate, SongResponse, SongUpdate, SongETA, PaginatedSongResponse
from app.schemas.stream_log import StreamLogCreate, StreamLogResponse, StreamLogSummary, PaginatedStreamLogResponse
from app.schemas.setting import SettingsResponse, SettingsUpdate
from app.schemas.challenge import ChallengeResponse, ChallengeResolveRequest

__all__ = [
    # Instance schemas
    "InstanceCreate",
    "InstanceResponse",
    "InstanceUpdate",
    "PaginatedInstanceResponse",
    # Account schemas
    "AccountCreate",
    "AccountResponse",
    "AccountUpdate",
    "AccountImport",
    # Proxy schemas
    "ProxyCreate",
    "ProxyResponse",
    "ProxyUpdate",
    "ProxyTestResult",
    # Song schemas
    "SongCreate",
    "SongResponse",
    "SongUpdate",
    "SongETA",
    "PaginatedSongResponse",
    # Stream log schemas
    "StreamLogCreate",
    "StreamLogResponse",
    "StreamLogSummary",
    "PaginatedStreamLogResponse",
    # Settings schemas
    "SettingsResponse",
    "SettingsUpdate",
    # Challenge schemas
    "ChallengeResponse",
    "ChallengeResolveRequest",
]
