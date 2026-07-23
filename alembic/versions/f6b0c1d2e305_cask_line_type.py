"""cask line_type on batches + cask formtype enum values

Revision ID: f6b0c1d2e305
Revises: e5a9b2c3d104
Create Date: 2026-07-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6b0c1d2e305"
down_revision: Union[str, None] = "e5a9b2c3d104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    linetype = postgresql.ENUM("BOTTLING", "CASK", name="linetype", create_type=False)
    linetype.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "batches",
        sa.Column(
            "line_type",
            linetype,
            nullable=False,
            server_default="BOTTLING",
        ),
    )

    # PostgreSQL: new enum values must be committed before use in some versions;
    # use autocommit block for ADD VALUE.
    ctx = op.get_context()
    new_form_types = [
        "CASK_FINAL_PALLET_COUNT",
        "CASK_LINE_CHECK",
        "CASK_PRODUCTION_WASTE",
        "CASK_TANK_DIP",
    ]
    for value in new_form_types:
        with ctx.autocommit_block():
            op.execute(f"ALTER TYPE formtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    op.drop_column("batches", "line_type")
    op.execute("DROP TYPE IF EXISTS linetype")
    # Cannot easily remove PG enum values for formtype
