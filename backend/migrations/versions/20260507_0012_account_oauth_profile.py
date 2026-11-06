"""account oauth profile

Revision ID: 20260507_0012
Revises: 20260505_0011
Create Date: 2026-05-07T12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260507_0012"
down_revision = "20260505_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("allegro_user_id", sa.String(length=64), nullable=True))
    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS uq_accounts_allegro_client_id")
    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_allegro_client_id_key")
    op.create_index("ix_accounts_tenant_allegro_user_id", "accounts", ["tenant_id", "allegro_user_id"])
    op.create_unique_constraint(
        "uq_accounts_tenant_allegro_user_id",
        "accounts",
        ["tenant_id", "allegro_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_accounts_tenant_allegro_user_id", "accounts", type_="unique")
    op.drop_index("ix_accounts_tenant_allegro_user_id", table_name="accounts")
    op.drop_column("accounts", "allegro_user_id")
    op.create_unique_constraint("uq_accounts_allegro_client_id", "accounts", ["allegro_client_id"])
