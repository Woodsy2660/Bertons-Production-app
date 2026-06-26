"""Signed cookie session helpers."""

from __future__ import annotations

from typing import Literal

SESSION_ROLE_KEY = "role"

Role = Literal["manager", "operator"]


def get_role_from_session(session: dict) -> Role | None:
    role = session.get(SESSION_ROLE_KEY)
    if role in ("manager", "operator"):
        return role
    return None


def set_role_in_session(session: dict, role: Role) -> None:
    session[SESSION_ROLE_KEY] = role


def clear_session(session: dict) -> None:
    session.clear()