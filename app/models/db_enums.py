from enum import Enum as PyEnum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_class: type[PyEnum], name: str) -> SAEnum:
    """Map Python enums to PostgreSQL enum member names (UPPERCASE)."""
    return SAEnum(
        enum_class,
        name=name,
        values_callable=lambda members: [m.name for m in members],
    )