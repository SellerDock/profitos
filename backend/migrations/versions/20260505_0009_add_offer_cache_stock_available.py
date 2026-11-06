"""add offer cache stock available

Revision ID: 20260505_0009
Revises: 20260505_0008
Create Date: 2026-05-05T14:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0009"
down_revision = "20260505_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("offers_cache", sa.Column("stock_available", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("offers_cache", "stock_available")
