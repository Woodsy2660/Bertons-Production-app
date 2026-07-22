"""Extraction storage and pallet tag prints

Revision ID: c8f2a1d94e07
Revises: b2c4e8f1a903
Create Date: 2026-07-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8f2a1d94e07"
down_revision: Union[str, Sequence[str], None] = "b2c4e8f1a903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("batch_headers", sa.Column("stock_alias", sa.String(length=100), nullable=True))
    op.add_column("batch_headers", sa.Column("vessel_batch", sa.String(length=100), nullable=True))
    op.add_column("batch_headers", sa.Column("cartons_per_pallet", sa.Integer(), nullable=True))
    op.add_column("batch_headers", sa.Column("cartons_per_layer", sa.Integer(), nullable=True))
    op.add_column("batch_headers", sa.Column("pallet_layers", sa.String(length=100), nullable=True))
    op.add_column("batch_headers", sa.Column("pallet_type", sa.String(length=100), nullable=True))
    op.add_column("batch_headers", sa.Column("front_label_height", sa.String(length=50), nullable=True))
    op.add_column("batch_headers", sa.Column("back_label_height", sa.String(length=50), nullable=True))
    op.add_column("batch_headers", sa.Column("other_label_height", sa.String(length=50), nullable=True))
    op.add_column("batch_headers", sa.Column("label_barcode", sa.String(length=100), nullable=True))
    op.add_column("batch_headers", sa.Column("carton_print_line1", sa.String(length=255), nullable=True))
    op.add_column("batch_headers", sa.Column("carton_print_line2", sa.String(length=255), nullable=True))
    op.add_column("batch_headers", sa.Column("carton_print_line3", sa.String(length=255), nullable=True))
    op.add_column("batch_headers", sa.Column("bottle_code", sa.String(length=50), nullable=True))
    op.add_column(
        "batch_headers",
        sa.Column("work_order_extract", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "pallet_tag_prints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("pallets_calculated", sa.Integer(), nullable=True),
        sa.Column("tags_printed", sa.Integer(), nullable=False),
        sa.Column("printed_by", sa.String(length=100), nullable=False),
        sa.Column("printed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_method", sa.String(length=20), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("pallet_tag_prints")
    op.drop_column("batch_headers", "work_order_extract")
    op.drop_column("batch_headers", "bottle_code")
    op.drop_column("batch_headers", "carton_print_line3")
    op.drop_column("batch_headers", "carton_print_line2")
    op.drop_column("batch_headers", "carton_print_line1")
    op.drop_column("batch_headers", "label_barcode")
    op.drop_column("batch_headers", "other_label_height")
    op.drop_column("batch_headers", "back_label_height")
    op.drop_column("batch_headers", "front_label_height")
    op.drop_column("batch_headers", "pallet_type")
    op.drop_column("batch_headers", "pallet_layers")
    op.drop_column("batch_headers", "cartons_per_layer")
    op.drop_column("batch_headers", "cartons_per_pallet")
    op.drop_column("batch_headers", "vessel_batch")
    op.drop_column("batch_headers", "stock_alias")