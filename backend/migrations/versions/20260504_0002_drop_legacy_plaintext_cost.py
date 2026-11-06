"""drop legacy plaintext cost columns and tables

Revision ID: 20260504_0002
Revises: 20260504_0001
Create Date: 2026-05-04 17:30:00

Defensive migration. Removes plaintext cost schema artifacts that
may exist in production from before the encrypted-vault model.
Idempotent: uses IF EXISTS, safe to run on fresh DB.

Decision trail: AUDIT_REPORT_2026-05-04.md ryzyko #1 + pytanie #5
(operator: option A).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260504_0002"
down_revision: Union[str, None] = "20260504_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop plaintext cost columns from sku_masters if present.
    op.execute("""
        ALTER TABLE IF EXISTS sku_masters
          DROP COLUMN IF EXISTS cost_per_unit,
          DROP COLUMN IF EXISTS cost,
          DROP COLUMN IF EXISTS purchase_cost,
          DROP COLUMN IF EXISTS buy_price;
    """)

    # 2. Drop plaintext cost history table if present.
    op.execute("DROP TABLE IF EXISTS sku_cost_history CASCADE;")

    # 3. Drop any legacy plaintext profit cache table.
    op.execute("DROP TABLE IF EXISTS sku_profit_cache CASCADE;")

    # 4. Document intent on encrypted tables.
    op.execute("""
        COMMENT ON TABLE encrypted_sku_costs IS
          'Client-side encrypted (Argon2id+AES-256-GCM). Server never sees plaintext costs.';
    """)
    op.execute("""
        COMMENT ON TABLE encrypted_sku_cost_history IS
          'Client-side encrypted historical costs. Server never sees plaintext.';
    """)
    op.execute("""
        COMMENT ON TABLE financial_vaults IS
          'Stores Argon2id parameters and AEAD verifier only. No password, no derived key.';
    """)


def downgrade() -> None:
    # Intentionally NOT reversible. Re-creating plaintext schema would
    # be a regression of the encryption guarantee.
    raise NotImplementedError(
        "Downgrade not supported: re-introducing plaintext cost schema "
        "would violate the encryption guarantee."
    )
