from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from app.config import settings


def _ensure_async_url(url: str) -> str:
    """Ensure the database URL uses the asyncpg driver."""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    parts = urlsplit(url)
    if parts.scheme != "postgresql+asyncpg":
        return url

    query_params = parse_qsl(parts.query, keep_blank_values=True)
    has_ssl_param = any(key == "ssl" for key, _ in query_params)
    normalized_query_params = []
    changed = False

    for key, value in query_params:
        if key == "sslmode":
            changed = True
            if not has_ssl_param:
                normalized_query_params.append(("ssl", value))
            continue
        normalized_query_params.append((key, value))

    if changed:
        return urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(normalized_query_params),
            parts.fragment,
        ))

    return url


engine = create_async_engine(
    _ensure_async_url(settings.DATABASE_URL),
    echo=settings.LOG_LEVEL == "DEBUG",
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
