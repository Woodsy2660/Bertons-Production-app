from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def _engine_connect_args(url: str) -> dict:
    """Supabase transaction pooler (port 6543) requires disabling prepared statements."""
    if "supabase" in url and ":6543" in url:
        return {"statement_cache_size": 0}
    return {}


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    # Concurrent tablet writers hold short-lived locks; size for floor load.
    pool_size=20,
    max_overflow=10,
    connect_args=_engine_connect_args(settings.database_url),
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
