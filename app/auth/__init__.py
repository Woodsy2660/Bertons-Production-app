"""Shared-role authentication (manager | operator). Swap this module for per-user auth later."""

from app.auth.dependencies import (
    Role,
    get_current_role,
    require_auth,
    require_manager,
    require_operator_or_manager,
)
from app.auth.session import SESSION_ROLE_KEY

__all__ = [
    "Role",
    "SESSION_ROLE_KEY",
    "get_current_role",
    "require_auth",
    "require_manager",
    "require_operator_or_manager",
]