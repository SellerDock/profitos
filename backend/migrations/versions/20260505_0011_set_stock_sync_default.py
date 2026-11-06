"""set stock sync from allegro default

Revision ID: 20260505_0011
Revises: 20260505_0010
Create Date: 2026-05-07T09:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0011"
down_revision = "20260505_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("stock_levels", "sync_from_allegro", server_default=sa.true())


def downgrade() -> None:
    op.alter_column("stock_levels", "sync_from_allegro", server_default=None)
