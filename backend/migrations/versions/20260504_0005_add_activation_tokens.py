"""add activation tokens

Revision ID: 20260504_0005
Revises: 20260504_0004
Create Date: 2026-05-04T18:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260504_0005"
down_revision = "20260504_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activation_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("waitlist_entry_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_activation_tokens_created_by"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_activation_tokens_tenant"),
        sa.ForeignKeyConstraint(["waitlist_entry_id"], ["waitlist_entries.id"], name="fk_activation_tokens_waitlist"),
        sa.UniqueConstraint("token_hash", name="uq_activation_tokens_token_hash"),
    )
    op.create_index("ix_activation_tokens_token_hash", "activation_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_activation_tokens_token_hash", table_name="activation_tokens")
    op.drop_table("activation_tokens")
