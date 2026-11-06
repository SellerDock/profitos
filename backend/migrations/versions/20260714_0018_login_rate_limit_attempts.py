"""Add durable login/waitlist rate limiter attempts table.

Revision ID: 20260714_0018
Revises: 20260512_0017
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0018"
down_revision = "20260512_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_rate_limit_attempts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("bucket_key", sa.String(length=600), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_rate_limit_attempts_bucket_key_created_at",
        "login_rate_limit_attempts",
        ["bucket_key", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_login_rate_limit_attempts_created_at",
        "login_rate_limit_attempts",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_login_rate_limit_attempts_created_at", table_name="login_rate_limit_attempts")
    op.drop_index("ix_login_rate_limit_attempts_bucket_key_created_at", table_name="login_rate_limit_attempts")
    op.drop_table("login_rate_limit_attempts")
