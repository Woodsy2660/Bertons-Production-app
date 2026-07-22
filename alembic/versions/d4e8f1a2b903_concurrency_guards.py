"""Concurrency guards: unique reading sequences and one current compilation.

Revision ID: d4e8f1a2b903
Revises: c8f2a1d94e07
Create Date: 2026-07-14

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8f1a2b903"
down_revision: Union[str, None] = "c8f2a1d94e07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate any existing reading sequences before unique constraint
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY form_instance_id
                       ORDER BY sequence, created_at, id
                   ) AS rn
            FROM readings
        )
        UPDATE readings AS r
        SET sequence = ranked.rn
        FROM ranked
        WHERE r.id = ranked.id
          AND r.sequence IS DISTINCT FROM ranked.rn
        """
    )

    # Ensure at most one is_current=true per batch
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY batch_id
                       ORDER BY compiled_at DESC NULLS LAST, id
                   ) AS rn
            FROM compilations
            WHERE is_current = true
        )
        UPDATE compilations AS c
        SET is_current = false
        FROM ranked
        WHERE c.id = ranked.id
          AND ranked.rn > 1
        """
    )

    op.create_unique_constraint(
        "uq_readings_form_instance_sequence",
        "readings",
        ["form_instance_id", "sequence"],
    )
    op.create_index(
        "uq_compilations_one_current_per_batch",
        "compilations",
        ["batch_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_compilations_one_current_per_batch",
        table_name="compilations",
    )
    op.drop_constraint(
        "uq_readings_form_instance_sequence",
        "readings",
        type_="unique",
    )
