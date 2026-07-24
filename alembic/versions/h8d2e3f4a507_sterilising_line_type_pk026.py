"""sterilising line_type + system for bottling FOR PK 026

Revision ID: h8d2e3f4a507
Revises: g7c1d2e3f406
Create Date: 2026-07-24

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "h8d2e3f4a507"
down_revision: Union[str, None] = "g7c1d2e3f406"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    linetype = postgresql.ENUM("BOTTLING", "CASK", name="linetype", create_type=False)

    op.add_column(
        "sterilising_checks",
        sa.Column(
            "line_type",
            linetype,
            nullable=False,
            server_default="CASK",
        ),
    )
    op.add_column(
        "sterilising_checks",
        sa.Column("system_id", sa.String(length=20), nullable=True),
    )
    # Existing CA 005 rows stay cask; qc_sign_off remains required for cask only in app layer.
    op.create_index(
        "ix_sterilising_checks_line_type",
        "sterilising_checks",
        ["line_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_sterilising_checks_line_type", table_name="sterilising_checks")
    op.drop_column("sterilising_checks", "system_id")
    op.drop_column("sterilising_checks", "line_type")
