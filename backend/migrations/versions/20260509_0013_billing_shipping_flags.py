"""Add Allegro Smart shipping flags to billing entries.

Revision ID: 20260509_0013
Revises: 20260507_0012
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260509_0013"
down_revision = "20260507_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_raw", sa.Column("shipping_is_smart", sa.Boolean(), nullable=True))
    op.add_column("billing_raw", sa.Column("shipping_order_is_smart", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("billing_raw", "shipping_order_is_smart")
    op.drop_column("billing_raw", "shipping_is_smart")
