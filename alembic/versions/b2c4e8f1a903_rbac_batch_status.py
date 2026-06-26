"""RBAC batch status enum update

Revision ID: b2c4e8f1a903
Revises: 791a084d54ca
Create Date: 2026-06-25

"""
from typing import Sequence, Union

from alembic import op

revision: str = "b2c4e8f1a903"
down_revision: Union[str, Sequence[str], None] = "791a084d54ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires new enum values to be committed before they can be used.
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute("ALTER TYPE batchstatus ADD VALUE IF NOT EXISTS 'AWAITING_REVIEW'")
    with ctx.autocommit_block():
        op.execute("ALTER TYPE batchstatus ADD VALUE IF NOT EXISTS 'COMPLETE'")

    op.execute("UPDATE batches SET status = 'COMPLETE' WHERE status = 'COMPILED'")
    op.execute(
        "UPDATE batches SET status = 'IN_PROGRESS' WHERE status IN ('DRAFT', 'READY')"
    )


def downgrade() -> None:
    op.execute("UPDATE batches SET status = 'IN_PROGRESS' WHERE status = 'AWAITING_REVIEW'")
    op.execute("UPDATE batches SET status = 'COMPILED' WHERE status = 'COMPLETE'")
    op.execute("UPDATE batches SET status = 'IN_PROGRESS' WHERE status = 'REOPENED'")