"""Two shared credentials — one manager, one operator."""

from __future__ import annotations

from app.auth.session import Role
from app.config import Settings


def verify_credentials(
    username: str,
    password: str,
    settings: Settings,
) -> Role | None:
    username = username.strip()
    password = password.strip()
    if not username or not password:
        return None

    if username == settings.manager_username and password == settings.manager_password:
        return "manager"
    if username == settings.operator_username and password == settings.operator_password:
        return "operator"
    return None