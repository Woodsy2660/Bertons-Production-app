"""feedback_reports table for in-app bug/suggestion reporting

Revision ID: e5a9b2c3d104
Revises: d4e8f1a2b903
Create Date: 2026-07-21

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5a9b2c3d104"
down_revision: Union[str, None] = "d4e8f1a2b903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    feedbackreporttype = postgresql.ENUM(
        "BUG",
        "DATA_CHANGE",
        "SUGGESTION",
        name="feedbackreporttype",
        create_type=False,
    )
    feedbackstatus = postgresql.ENUM(
        "NEW",
        "REVIEWED",
        "RESOLVED",
        name="feedbackstatus",
        create_type=False,
    )
    feedbackreporttype.create(op.get_bind(), checkfirst=True)
    feedbackstatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("report_type", feedbackreporttype, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("submitted_role", sa.String(length=20), nullable=False),
        sa.Column("source_path", sa.String(length=500), nullable=False),
        sa.Column("page_context", sa.String(length=300), nullable=True),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            feedbackstatus,
            nullable=False,
            server_default="NEW",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batches.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_reports_submitted_at",
        "feedback_reports",
        ["submitted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_reports_submitted_at", table_name="feedback_reports")
    op.drop_table("feedback_reports")
    op.execute("DROP TYPE IF EXISTS feedbackstatus")
    op.execute("DROP TYPE IF EXISTS feedbackreporttype")
