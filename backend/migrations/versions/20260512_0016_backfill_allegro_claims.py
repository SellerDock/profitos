"""Backfill Allegro account claims from existing accounts.

Revision ID: 20260512_0016
Revises: 20260512_0015
Create Date: 2026-05-12
"""

from alembic import op


revision = "20260512_0016"
down_revision = "20260512_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO allegro_account_claims (
            allegro_user_id,
            tenant_id,
            account_id,
            account_name,
            first_connected_at,
            last_connected_at
        )
        SELECT
            a.allegro_user_id,
            a.tenant_id,
            a.id,
            a.name,
            COALESCE(a.created_at, now()),
            now()
        FROM accounts a
        WHERE a.allegro_user_id IS NOT NULL
          AND a.allegro_user_id <> ''
        ON CONFLICT (allegro_user_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM allegro_account_claims c
        USING accounts a
        WHERE c.allegro_user_id = a.allegro_user_id
          AND c.account_id = a.id
    """)
