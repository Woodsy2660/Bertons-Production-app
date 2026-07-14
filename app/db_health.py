"""Database connectivity helpers."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.database import engine


def is_db_connection_error(exc: BaseException) -> bool:
    """Return True when an exception indicates the database is unreachable."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (OperationalError, InterfaceError)):
            return True
        if isinstance(current, OSError):
            message = str(current).lower()
            if "connect call failed" in message or "connection refused" in message:
                return True
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
        current = current.__cause__ or current.__context__
    return False


async def check_db_connection() -> bool:
    """Ping the database; used by /ready and startup diagnostics."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False