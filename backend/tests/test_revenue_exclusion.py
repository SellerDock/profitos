"""Fully refunded sales are excluded from dashboard totals."""
from decimal import Decimal

import pytest

from app.services.dashboard_engine import DashboardEngine, PnLSummary, get_custom_period
from tests.finance_fixtures import add_order, add_payment_refund, finance_scope


@pytest.fixture
def sales_summary(finance_scope):
    scope, account = finance_scope
    add_order(scope, account, price=Decimal("49.90"), quantity=2)
    add_order(scope, account, price=Decimal("19.99"))
    refunded = add_order(scope, account, price=Decimal("99.99"))
    add_payment_refund(scope, account, refunded, amount=Decimal("99.99"))
    return DashboardEngine(scope).summary(get_custom_period("2026-04-12", "2026-04-12"), account_id=account.id)


def test_fully_refunded_excluded_from_revenue(sales_summary):
    """Revenue is 2 × 49.90 + 19.99; the 99.99 payment refund removes that order."""
    assert Decimal(sales_summary.revenue_gross) == 2 * Decimal("49.90") + Decimal("19.99")


def test_units_excluded_for_fully_refunded(sales_summary):
    """Two units plus one unit remain; the refunded order's unit is excluded."""
    assert sales_summary.units_sold == 2 + 1


def test_orders_count_excluded_for_fully_refunded(sales_summary):
    """Two of the three orders remain after the full payment refund."""
    assert sales_summary.orders_count == 2


def test_no_double_count_via_refund_cost():
    """PnLSummary has no separate refund_cost field."""
    summary = PnLSummary(period_label="test", date_from="", date_to="")
    assert not hasattr(summary, "refund_cost")
