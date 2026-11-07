"""One-time Allegro OAuth transactions bound to the initiating browser.

Revision ID: 20261107_0023
Revises: 20261107_0022
"""
from alembic import op
import sqlalchemy as sa

revision = "20261107_0023"
down_revision = "20261107_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "allegro_oauth_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nonce_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
    )
    op.create_index("ix_allegro_oauth_transactions_expires_at", "allegro_oauth_transactions", ["expires_at"])


def downgrade():
    op.drop_index("ix_allegro_oauth_transactions_expires_at", table_name="allegro_oauth_transactions")
    op.drop_table("allegro_oauth_transactions")
