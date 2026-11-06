"""
Tests for search filter in dashboard summary (period tiles).

test_summary_with_search_filters_revenue   — two synthetic orders, only matching one appears
                                             in revenue_gross when searching by name.
test_summary_with_search_excludes_nsp      — NSP billing entry is excluded when search is active.
test_summary_no_search_unchanged           — regression: summary without search returns same value
                                             as a direct SQL sum on orders_raw for the same period.
"""
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.environ.get('POSTGRES_USER', 'apos_user')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'apos_pass')}@"
    f"{os.environ.get('POSTGRES_HOST', 'apos-db')}/"
    f"{os.environ.get('POSTGRES_DB', 'apos_db')}"
)

from app.services.dashboard_engine import DashboardEngine, get_custom_period
from tests.tenant_helpers import operator_scope


def _engine():
    return create_engine(_DB_URL)


# Use a date far in the future to avoid clashing with real data.
_TEST_DATE = "2090-01-15"
_TEST_BOUGHT_AT = datetime(2090, 1, 14, 23, 0, 0)  # UTC = 2090-01-15 00:00 Warsaw


def _unique_id() -> str:
    return str(uuid.uuid4())


class _Fixtures:
    """Context manager that inserts synthetic rows and cleans them up after the test."""

    def __init__(self, conn):
        self.conn = conn
        self.sku_ids: list[int] = []
        self.order_ids: list[str] = []
        self.billing_ids: list[int] = []
        self.offer_ids: list[str] = []
        self.account_id = self._insert_account()

    def _insert_account(self) -> int:
        self.conn.execute(
            text(
                "INSERT INTO tenants (id, name, slug, is_active)"
                " VALUES (1, 'Operator', 'operator', true)"
                " ON CONFLICT (id) DO NOTHING"
            )
        )
        row = self.conn.execute(
            text(
                "INSERT INTO accounts"
                " (tenant_id, name, allegro_client_id, allegro_client_secret, color)"
                " VALUES (1, :name, :client_id, 'secret', '#111827')"
                " RETURNING id"
            ),
            {"name": "Search Filter Test Account", "client_id": "search-filter-" + _unique_id()},
        ).fetchone()
        return int(row[0])

    def insert_sku(self, sku_key: str, name: str) -> int:
        row = self.conn.execute(
            text(
                "INSERT INTO sku_masters (tenant_id, sku_key, name, vat_rate, target_margin_pct)"
                " VALUES (1, :sku, :name, '0.23', '0.30')"
                " RETURNING id"
            ),
            {"sku": sku_key, "name": name},
        ).fetchone()
        self.sku_ids.append(row[0])
        return row[0]

    def insert_order(
        self,
        sku: str,
        amount: Decimal,
        order_id: str | None = None,
        offer_id: str | None = None,
        currency: str = "PLN",
    ) -> str:
        oid = order_id or _unique_id()
        self.conn.execute(
            text(
                "INSERT INTO orders_raw"
                " (tenant_id, line_item_id, order_id, account_id, offer_id, sku, quantity, unit_price,"
                "  currency, status, bought_at, delivery_amount)"
                " VALUES (1, :lid, :oid, :account_id, :offer, :sku, 1, :price,"
                "         :cur, 'READY_FOR_PROCESSING', :bat, 0)"
            ),
            {
                "lid": _unique_id(),
                "oid": oid,
                "account_id": self.account_id,
                "offer": offer_id,
                "sku": sku,
                "price": str(amount),
                "cur": currency,
                "bat": _TEST_BOUGHT_AT,
            },
        )
        self.order_ids.append(oid)
        return oid

    def insert_offer(self, sku: str, offer_id: str, name: str, ean: str | None = None) -> None:
        self.conn.execute(
            text(
                "INSERT INTO offers_cache"
                " (tenant_id, offer_id, account_id, sku, name, price, currency, ean, synced_at)"
                " VALUES (1, :offer, :account_id, :sku, :name, 100, 'PLN', :ean, :synced_at)"
            ),
            {
                "offer": offer_id,
                "account_id": self.account_id,
                "sku": sku,
                "name": name,
                "ean": ean,
                "synced_at": _TEST_BOUGHT_AT,
            },
        )
        self.offer_ids.append(offer_id)

    def insert_billing(
        self,
        type_: str,
        amount: Decimal,
        order_id: str | None = None,
        offer_id: str | None = None,
        currency: str = "PLN",
    ) -> int:
        row = self.conn.execute(
            text(
                "INSERT INTO billing_raw"
                " (tenant_id, entry_id, account_id, offer_id, type, amount, currency,"
                "  occurred_at, order_id)"
                " VALUES (1, :eid, :account_id, :offer, :type, :amt, :cur, :oat, :oid)"
                " RETURNING id"
            ),
            {
                "eid": _unique_id(),
                "account_id": self.account_id,
                "offer": offer_id,
                "type": type_,
                "amt": str(amount),
                "cur": currency,
                "oat": _TEST_BOUGHT_AT,
                "oid": order_id,
            },
        ).fetchone()
        self.billing_ids.append(row[0])
        return row[0]

    def cleanup(self):
        if self.billing_ids:
            self.conn.execute(
                text(f"DELETE FROM billing_raw WHERE id = ANY(ARRAY{self.billing_ids}::int[])")
            )
        if self.offer_ids:
            self.conn.execute(
                text(
                    "DELETE FROM offers_cache WHERE offer_id = ANY(ARRAY["
                    + ",".join(f"'{o}'" for o in self.offer_ids)
                    + "])"
                )
            )
        if self.order_ids:
            self.conn.execute(
                text(
                    "DELETE FROM orders_raw WHERE order_id = ANY(ARRAY["
                    + ",".join(f"'{o}'" for o in self.order_ids)
                    + "])"
                )
            )
        if self.sku_ids:
            self.conn.execute(
                text(f"DELETE FROM sku_masters WHERE id = ANY(ARRAY{self.sku_ids}::int[])")
            )
        self.conn.execute(text("DELETE FROM accounts WHERE id = :account_id"), {"account_id": self.account_id})


def test_summary_with_search_filters_revenue():
    """
    Two orders: one for 'GlicynianTestMatch' (100 PLN) and one for 'OtherProductTest' (200 PLN).
    Searching for 'GlicynianTestMatch' must return revenue_gross == 100, not 300.
    """
    eng = _engine()
    with eng.connect() as conn:
        fx = _Fixtures(conn)
        sku_match = "TEST-SEARCH-MATCH-" + _unique_id()[:8]
        sku_other = "TEST-SEARCH-OTHER-" + _unique_id()[:8]
        try:
            fx.insert_sku(sku_match, "GlicynianTestMatch Produkt")
            fx.insert_sku(sku_other, "OtherProductTest Zupełnie Inny")
            fx.insert_order(sku_match, Decimal("100.00"))
            fx.insert_order(sku_other, Decimal("200.00"))
            conn.commit()

            with Session(_engine()) as session:
                engine_svc = DashboardEngine(operator_scope(session))
                period = get_custom_period(_TEST_DATE, _TEST_DATE)

                result_search = engine_svc.summary(period, search="GlicynianTestMatch")
                result_all = engine_svc.summary(period)

        finally:
            fx.cleanup()
            conn.commit()

    rev_search = Decimal(result_search.revenue_gross)
    rev_all = Decimal(result_all.revenue_gross)

    assert rev_search == Decimal("100.00"), (
        f"Expected revenue_gross=100.00 with search='GlicynianTestMatch', got {rev_search}"
    )
    assert rev_all >= Decimal("300.00"), (
        f"Expected revenue_gross >= 300.00 without search, got {rev_all}"
    )
    assert rev_search < rev_all, "Searched revenue must be less than total revenue"

    assert result_search.orders_count == 1, (
        f"Expected 1 order with search, got {result_search.orders_count}"
    )


def test_summary_with_search_filters_by_sku_key():
    """Searching for a canonical SKU key must filter dashboard summary revenue."""
    eng = _engine()
    with eng.connect() as conn:
        fx = _Fixtures(conn)
        sku_match = "TEST-SEARCH-SKU-" + _unique_id()[:8]
        sku_other = "TEST-SEARCH-SKU-OTHER-" + _unique_id()[:8]
        try:
            fx.insert_sku(sku_match, "Sku Search Match Product")
            fx.insert_sku(sku_other, "Sku Search Other Product")
            fx.insert_order(sku_match, Decimal("100.00"))
            fx.insert_order(sku_other, Decimal("200.00"))
            conn.commit()

            with Session(_engine()) as session:
                engine_svc = DashboardEngine(operator_scope(session))
                period = get_custom_period(_TEST_DATE, _TEST_DATE)
                result = engine_svc.summary(period, search=sku_match)

        finally:
            fx.cleanup()
            conn.commit()

    assert Decimal(result.revenue_gross) == Decimal("100.00")
    assert result.orders_count == 1


def test_products_with_search_filters_by_offer_ean_and_offer_id():
    """Product search must match offer metadata, not only SKU master names."""
    eng = _engine()
    with eng.connect() as conn:
        fx = _Fixtures(conn)
        sku_match = "TEST-SEARCH-EAN-" + _unique_id()[:8]
        sku_other = "TEST-SEARCH-EAN-OTHER-" + _unique_id()[:8]
        offer_id = "test-search-offer-" + _unique_id()[:8]
        ean = "5901234567890"
        try:
            fx.insert_sku(sku_match, "Offer Metadata Match Product")
            fx.insert_sku(sku_other, "Offer Metadata Other Product")
            fx.insert_offer(sku_match, offer_id, "Offer Metadata Search Name", ean)
            fx.insert_order(sku_match, Decimal("100.00"), offer_id=offer_id)
            fx.insert_order(sku_other, Decimal("200.00"), offer_id="other-offer")
            conn.commit()

            with Session(_engine()) as session:
                engine_svc = DashboardEngine(operator_scope(session))
                period = get_custom_period(_TEST_DATE, _TEST_DATE)
                by_ean = {row.sku_key for row in engine_svc.products(period, search=ean)}
                by_offer_id = {row.sku_key for row in engine_svc.products(period, search=offer_id)}

        finally:
            fx.cleanup()
            conn.commit()

    assert by_ean == {sku_match}
    assert by_offer_id == {sku_match}


def test_summary_with_search_filters_by_offer_ean():
    """EAN lookup must filter dashboard tile revenue and order count."""
    eng = _engine()
    with eng.connect() as conn:
        fx = _Fixtures(conn)
        sku_match = "TEST-SUMMARY-EAN-" + _unique_id()[:8]
        sku_other = "TEST-SUMMARY-EAN-OTHER-" + _unique_id()[:8]
        offer_id = "test-summary-ean-offer-" + _unique_id()[:8]
        ean = "5901234567890"
        try:
            fx.insert_sku(sku_match, "Summary EAN Match Product")
            fx.insert_sku(sku_other, "Summary EAN Other Product")
            fx.insert_offer(sku_match, offer_id, "Summary EAN Offer", ean)
            fx.insert_order(sku_match, Decimal("100.00"), offer_id=offer_id)
            fx.insert_order(sku_other, Decimal("200.00"), offer_id="other-offer")
            conn.commit()

            with Session(_engine()) as session:
                engine_svc = DashboardEngine(operator_scope(session))
                period = get_custom_period(_TEST_DATE, _TEST_DATE)
                result = engine_svc.summary(period, search=ean)

        finally:
            fx.cleanup()
            conn.commit()

    assert Decimal(result.revenue_gross) == Decimal("100.00")
    assert result.orders_count == 1


def test_ean_search_reuses_resolved_skus_for_multiple_dashboard_periods(monkeypatch):
    """EAN works for tile/chart-style repeated summaries without re-resolving metadata."""
    eng = _engine()
    with eng.connect() as conn:
        fx = _Fixtures(conn)
        sku_match = "TEST-CACHED-EAN-" + _unique_id()[:8]
        sku_other = "TEST-CACHED-EAN-OTHER-" + _unique_id()[:8]
        ean = "733739033086"
        try:
            fx.insert_sku(sku_match, "Cached EAN Match Product")
            fx.insert_sku(sku_other, "Cached EAN Other Product")
            fx.insert_offer(sku_match, "cached-ean-offer-" + _unique_id()[:8], "Cached EAN Offer", ean)
            fx.insert_order(sku_match, Decimal("100.00"))
            fx.insert_order(sku_other, Decimal("200.00"))
            conn.commit()

            with Session(_engine()) as session:
                engine_svc = DashboardEngine(operator_scope(session))
                period = get_custom_period(_TEST_DATE, _TEST_DATE)
                fallback_calls = 0
                original_fallback = engine_svc._resolve_search_skus_from_orders

                def spy_fallback(search: str, account_id: int | None):
                    nonlocal fallback_calls
                    fallback_calls += 1
                    return original_fallback(search, account_id)

                monkeypatch.setattr(engine_svc, "_resolve_search_skus_from_orders", spy_fallback)

                # summary/all and summary/daily reuse one DashboardEngine across
                # periods. Two calls model that request pattern.
                first = engine_svc.summary(period, search=ean)
                second = engine_svc.summary(period, search=ean)
                product_skus = {row.sku_key for row in engine_svc.products(period, search=ean)}

                assert engine_svc._search_skus_cache == {(ean, None): (sku_match,)}
                assert fallback_calls == 0, "EAN in offers_cache must not scan orders_raw"
        finally:
            fx.cleanup()
            conn.commit()

    assert Decimal(first.revenue_gross) == Decimal("100.00")
    assert Decimal(second.revenue_gross) == Decimal("100.00")
    assert product_skus == {sku_match}


def test_summary_with_search_excludes_nsp():
    """
    One matching order (100 PLN) + one NSP billing entry (-15 PLN, account-level).
    When searching, ads_cost must be 0 (NSP excluded as account-level, not attributable).
    """
    eng = _engine()
    with eng.connect() as conn:
        fx = _Fixtures(conn)
        sku = "TEST-SEARCH-NSP-" + _unique_id()[:8]
        try:
            fx.insert_sku(sku, "GlicynianNSPTest Produkt")
            fx.insert_order(sku, Decimal("100.00"))
            # NSP entry: account-level, no order_id, no offer_id
            fx.insert_billing("NSP", Decimal("-15.00"), order_id=None, offer_id=None)
            conn.commit()

            with Session(_engine()) as session:
                engine_svc = DashboardEngine(operator_scope(session))
                period = get_custom_period(_TEST_DATE, _TEST_DATE)
                result = engine_svc.summary(period, search="GlicynianNSPTest")

        finally:
            fx.cleanup()
            conn.commit()

    assert Decimal(result.revenue_gross) == Decimal("100.00"), (
        f"Expected revenue_gross=100.00, got {result.revenue_gross}"
    )
    assert Decimal(result.ads_cost) == Decimal("0.00"), (
        f"Expected ads_cost=0 (NSP excluded when search active), got {result.ads_cost}"
    )


def test_summary_no_search_unchanged():
    """
    Regression: summary without search must include both orders from the fixture period.
    Verifies that adding search= parameter without passing a value is backward-compatible.
    """
    eng = _engine()
    with eng.connect() as conn:
        fx = _Fixtures(conn)
        sku_a = "TEST-REGRESSION-A-" + _unique_id()[:8]
        sku_b = "TEST-REGRESSION-B-" + _unique_id()[:8]
        try:
            fx.insert_sku(sku_a, "RegressionProductA Zestaw")
            fx.insert_sku(sku_b, "RegressionProductB Opakowanie")
            fx.insert_order(sku_a, Decimal("50.00"))
            fx.insert_order(sku_b, Decimal("75.00"))
            conn.commit()

            with Session(_engine()) as session:
                engine_svc = DashboardEngine(operator_scope(session))
                period = get_custom_period(_TEST_DATE, _TEST_DATE)
                result = engine_svc.summary(period)

        finally:
            fx.cleanup()
            conn.commit()

    rev = Decimal(result.revenue_gross)
    assert rev >= Decimal("125.00"), (
        f"Expected revenue_gross >= 125.00 without search (both orders), got {rev}"
    )
