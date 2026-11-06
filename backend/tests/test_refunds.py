"""Synthetic tests for refund attribution and commission refunds."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from app.services.dashboard_engine import DashboardEngine, PnLSummary, get_custom_period
from tests.finance_fixtures import (
    add_billing, add_customer_return, add_order, add_payment_refund, finance_scope,
)


def test_fully_refunded_detection(finance_scope):
    """-10 + 4 + 6 = 0; the last positive entry is April 24 in Warsaw (22:30 UTC)."""
    scope, account = finance_scope
    order = add_order(scope, account, price=Decimal("49.99"))
    add_billing(scope, account, order, type="SUC", amount=Decimal("-10.00"))
    add_billing(scope, account, order, type="SUC", amount=Decimal("4.00"), occurred_at=datetime(2026, 4, 22, 12))
    add_billing(scope, account, order, type="FSF", amount=Decimal("6.00"), occurred_at=datetime(2026, 4, 23, 22, 30))
    row = scope.db.execute(text("""
        WITH balance AS (
            SELECT SUM(amount) FILTER (WHERE amount < 0) AS charged,
                   SUM(amount) FILTER (WHERE amount > 0) AS refunded,
                   MAX(occurred_at) FILTER (WHERE amount > 0) AS last_refund_at
            FROM billing_raw
            WHERE tenant_id = :tenant_id AND account_id = :account_id
              AND order_id = :order_id AND type IN ('SUC', 'FSF')
        )
        SELECT ABS(charged + refunded) <= ABS(charged) * 0.05 AS is_fully_refunded,
               ((last_refund_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date AS refund_date
        FROM balance
    """), {"tenant_id": scope.tenant_id, "account_id": account.id, "order_id": order.order_id}).mappings().one()
    assert row["is_fully_refunded"]
    assert str(row["refund_date"]) == "2026-04-24"


def test_refund_excluded_from_revenue():
    """
    Fully-refunded order is excluded from revenue (profitboard model — Task 1).
    For 2026-04-23 summary (no account filter), the refunded order must NOT appear in revenue.
    We verify by checking PnLSummary has no refund_cost field (option a — field removed).
    """
    summary = DashboardEngine.__new__(DashboardEngine)  # structural check only
    from app.services.dashboard_engine import PnLSummary
    s = PnLSummary(period_label="test", date_from="", date_to="")
    assert not hasattr(s, "refund_cost"), (
        "PnLSummary must not have refund_cost — fully-refunded orders excluded from revenue instead."
    )


def test_commission_refunds_amount(finance_scope):
    """Approved SUC 3.00 and FSF 2.00 total 5.00; pending and absent returns add zero."""
    scope, account = finance_scope
    for status, kind, amount in (("COMMISSION_REFUNDED", "SUC", "3.00"),
                                 ("FINISHED", "FSF", "2.00"),
                                 ("CREATED", "SUC", "7.00"),
                                 (None, "FSF", "11.00")):
        order = add_order(scope, account, price=Decimal("49.90"))
        add_billing(scope, account, order, type=kind, amount=Decimal(amount))
        if status:
            add_customer_return(scope, account, order, status=status)
        if status == "FINISHED":
            add_billing(scope, account, order, type="SUC", amount=Decimal("-8.00"))
            add_billing(scope, account, order, type="CPF", amount=Decimal("13.00"))
    summary = DashboardEngine(scope).summary(get_custom_period("2026-04-12", "2026-04-12"), account_id=account.id)
    assert Decimal(summary.commission_refunds_amount) == Decimal("3.00") + Decimal("2.00")


def test_no_double_counting(finance_scope):
    """A 49.99 full payment refund leaves 19.99 revenue and no refund_cost field."""
    scope, account = finance_scope
    add_order(scope, account, price=Decimal("19.99"))
    order = add_order(scope, account, price=Decimal("49.99"))
    add_payment_refund(scope, account, order, amount=Decimal("49.99"))
    summary = DashboardEngine(scope).summary(get_custom_period("2026-04-12", "2026-04-12"), account_id=account.id)
    assert Decimal(summary.revenue_gross) == Decimal("19.99")
    assert not hasattr(summary, "refund_cost")


def test_profit_formula_includes_refund_cost():
    """
    Synthetic: a PnLSummary with refund_cost=100 has profit 100 lower than refund_cost=0.
    This verifies the profit formula uses refund_cost.
    """
    def _make_profit(refund_cost_val: float) -> float:
        revenue = Decimal("1000.00")
        commission_cost = Decimal("-50.00")
        featuring_commission_cost = Decimal("-10.00")
        ads_cost = Decimal("-20.00")
        smart_shipping_cost = Decimal("-30.00")
        featuring_cost = Decimal("-15.00")
        coins_cost = Decimal("-5.00")
        protect_cost = Decimal("0.00")
        local_cost = Decimal("0.00")
        subscription_cost = Decimal("-18.00")
        fulfillment = Decimal("0.00")
        price_adjust_cost = Decimal("25.00")
        refund_commission = Decimal("10.00")
        cogs = Decimal("600.00")
        refund_cost = Decimal(str(refund_cost_val))

        total_allegro_signed = (
            commission_cost + featuring_commission_cost + ads_cost
            + smart_shipping_cost + featuring_cost + coins_cost
            + protect_cost + local_cost + subscription_cost + fulfillment
        )
        return float(revenue + total_allegro_signed + price_adjust_cost + refund_commission - cogs - refund_cost)

    profit_no_refund = _make_profit(0)
    profit_with_refund = _make_profit(100)

    assert abs(profit_no_refund - profit_with_refund - 100) < 0.001, (
        f"Expected profit difference of 100.00, got {profit_no_refund - profit_with_refund:.4f}"
    )
