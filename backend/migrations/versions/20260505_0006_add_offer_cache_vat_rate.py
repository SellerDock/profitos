"""add offer cache vat rate

Revision ID: 20260505_0006
Revises: 20260504_0005
Create Date: 2026-05-05T12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0006"
down_revision = "20260504_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("offers_cache", sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column("offers_cache", "vat_rate")
