"""standalone sterilising / pre-start checks (FOR CA 005)

Revision ID: g7c1d2e3f406
Revises: f6b0c1d2e305
Create Date: 2026-07-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "g7c1d2e3f406"
down_revision: Union[str, None] = "f6b0c1d2e305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sterilising_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("operator_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("check_time", sa.Time(), nullable=True),
        sa.Column("filters_integrity_tested", sa.String(length=1), nullable=True),
        sa.Column(
            "filter_readings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("lenticular_temp_c", sa.String(length=20), nullable=True),
        sa.Column("lenticular_duration_mins", sa.String(length=20), nullable=True),
        sa.Column("line_temp_c", sa.String(length=20), nullable=True),
        sa.Column("line_duration_mins", sa.String(length=20), nullable=True),
        sa.Column("filler_clean", sa.String(length=1), nullable=True),
        sa.Column("carton_erector_clean", sa.String(length=1), nullable=True),
        sa.Column("qc_sign_off", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("created_by_role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_sterilising_checks_check_date",
        "sterilising_checks",
        ["check_date"],
    )

    op.create_table(
        "run_sterilising_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sterilising_check_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sterilising_checks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attached_by_role", sa.String(length=20), nullable=False),
        sa.Column(
            "attached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "batch_id",
            "sterilising_check_id",
            name="uq_run_sterilising_check_batch_check",
        ),
    )
    op.create_index(
        "ix_run_sterilising_checks_batch_id",
        "run_sterilising_checks",
        ["batch_id"],
    )
    op.create_index(
        "ix_run_sterilising_checks_sterilising_check_id",
        "run_sterilising_checks",
        ["sterilising_check_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_sterilising_checks_sterilising_check_id", table_name="run_sterilising_checks")
    op.drop_index("ix_run_sterilising_checks_batch_id", table_name="run_sterilising_checks")
    op.drop_table("run_sterilising_checks")
    op.drop_index("ix_sterilising_checks_check_date", table_name="sterilising_checks")
    op.drop_table("sterilising_checks")
