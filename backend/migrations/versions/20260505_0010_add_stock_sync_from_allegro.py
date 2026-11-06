"""add stock sync from allegro flag

Revision ID: 20260505_0010
Revises: 20260505_0009
Create Date: 2026-05-07T09:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0010"
down_revision = "20260505_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_levels",
        sa.Column("sync_from_allegro", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("stock_levels", "sync_from_allegro", server_default=None)


def downgrade() -> None:
    op.drop_column("stock_levels", "sync_from_allegro")
