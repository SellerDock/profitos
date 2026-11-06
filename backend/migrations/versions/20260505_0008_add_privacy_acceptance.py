"""add privacy acceptance timestamps

Revision ID: 20260505_0008
Revises: 20260505_0007
Create Date: 2026-05-05T13:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260505_0008"
down_revision = "20260505_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("waitlist_entries", sa.Column("privacy_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("privacy_accepted_at", sa.DateTime(), nullable=True))
    op.alter_column("activation_tokens", "created_by_user_id", existing_type=sa.Integer(), nullable=True)
    op.execute("UPDATE waitlist_entries SET privacy_accepted_at = created_at WHERE privacy_accepted_at IS NULL")
    op.execute("UPDATE users SET privacy_accepted_at = created_at WHERE privacy_accepted_at IS NULL")


def downgrade() -> None:
    op.execute("UPDATE activation_tokens SET created_by_user_id = 1 WHERE created_by_user_id IS NULL")
    op.alter_column("activation_tokens", "created_by_user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("users", "privacy_accepted_at")
    op.drop_column("waitlist_entries", "privacy_accepted_at")
