"""trim leading/trailing whitespace from sku column in orders_raw and offers_cache

Revision ID: 20260726_0020
Revises: 20260723_0019
Create Date: 2026-07-26
"""

from alembic import op


revision = "20260726_0020"
down_revision = "20260723_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalise raw Allegro SKU values that were stored with leading/trailing
    # whitespace before _normalize_sku() was introduced in import_service.py.
    # sku_import already calls .strip() when creating SkuMaster rows, so
    # untrimmed values in orders_raw / offers_cache would cause a mismatch
    # when filtering by account in list_products().
    #
    # offers_cache: the unique constraint is on (account_id, offer_id) and does
    # NOT include the sku column, so btrim(sku) cannot cause a uniqueness
    # conflict here.
    op.execute(
        "UPDATE orders_raw SET sku = btrim(sku) WHERE sku IS NOT NULL AND sku <> btrim(sku)"
    )
    op.execute(
        "UPDATE offers_cache SET sku = btrim(sku) WHERE sku IS NOT NULL AND sku <> btrim(sku)"
    )


def downgrade() -> None:
    # Trailing/leading whitespace cannot be restored — original raw values were
    # not preserved. This is intentional: the whitespace was never meaningful.
    pass
