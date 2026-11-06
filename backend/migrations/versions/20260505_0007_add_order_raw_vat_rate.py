"""add order raw vat rate

Revision ID: 20260505_0007
Revises: 20260505_0006
Create Date: 2026-05-05T12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0007"
down_revision = "20260505_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders_raw", sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column("orders_raw", "vat_rate")
