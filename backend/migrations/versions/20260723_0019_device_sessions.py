"""add device_sessions table for refresh-token device sessions

Revision ID: 20260723_0019
Revises: 20260714_0018
Create Date: 2026-07-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0019"
down_revision = "20260714_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("device_label", sa.String(length=255), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("app_version", sa.String(length=128), nullable=True),
        sa.Column("ip_created", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_device_sessions_user"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT", name="fk_device_sessions_tenant"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_device_sessions_refresh_token_hash"),
    )
    op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"], unique=False)
    op.create_index("ix_device_sessions_family_id", "device_sessions", ["family_id"], unique=False)
    op.create_index("ix_device_sessions_refresh_token_hash", "device_sessions", ["refresh_token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_device_sessions_refresh_token_hash", table_name="device_sessions")
    op.drop_index("ix_device_sessions_family_id", table_name="device_sessions")
    op.drop_index("ix_device_sessions_user_id", table_name="device_sessions")
    op.drop_table("device_sessions")
