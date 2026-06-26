"""FastAPI dependencies for role-based access."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.auth.session import Role, get_role_from_session

PUBLIC_PATHS = frozenset({"/login", "/health", "/static"})


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return path.startswith("/static/")


async def get_current_role(request: Request) -> Role | None:
    return get_role_from_session(request.session)


async def require_auth(
    role: Annotated[Role | None, Depends(get_current_role)],
) -> Role:
    if role is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return role


async def require_manager(
    role: Annotated[Role, Depends(require_auth)],
) -> Role:
    if role != "manager":
        raise HTTPException(status_code=403, detail="Manager access required")
    return role


async def require_operator_or_manager(
    role: Annotated[Role, Depends(require_auth)],
) -> Role:
    return role