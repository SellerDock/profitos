"""Buyer-paid and Smart shipping fees use isolated synthetic finance data."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.services.dashboard_engine import DashboardEngine, PnLSummary, get_custom_period
from tests.finance_fixtures import add_billing, add_order, finance_scope


PERIOD = get_custom_period("2026-04-12", "2026-04-12")


def summary(scope, account):
    return DashboardEngine(scope).summary(PERIOD, account_id=account.id)


@pytest.mark.parametrize("code", ["HB4", "HLB", "ORB"])
@pytest.mark.parametrize(
    "flags",
    [{}, {"shipping_is_smart": False}, {"shipping_order_is_smart": False}],
    ids=["delivery-fallback", "fee-flag", "order-flag"],
)
def test_smart_shipping_excludes_buyer_paid(finance_scope, code, flags):
    """A 7.25 fee on a buyer-paid order belongs entirely to passthrough, not Smart."""
    scope, account = finance_scope
    order = add_order(scope, account, price=Decimal("100.00"), delivery_amount=Decimal("10.49"))
    add_billing(scope, account, order, type=code, amount=Decimal("-7.25"), **flags)

    result = summary(scope, account)
    assert Decimal(result.shipping_passthrough_cost) == Decimal("7.25")
    assert Decimal(result.smart_shipping_cost) == Decimal("0")


@pytest.mark.parametrize("code", ["HB4", "HLB", "ORB"])
@pytest.mark.parametrize(
    "delivery,flags",
    [
        ("0", {}),
        ("10.49", {"shipping_is_smart": True}),
        ("10.49", {"shipping_order_is_smart": True}),
    ],
    ids=["delivery-fallback", "fee-flag", "order-flag"],
)
def test_smart_shipping_includes_smart_orders(finance_scope, code, delivery, flags):
    """A 6.40 fee on a Smart order belongs entirely to Smart, not passthrough."""
    scope, account = finance_scope
    order = add_order(scope, account, price=Decimal("100.00"), delivery_amount=Decimal(delivery))
    add_billing(scope, account, order, type=code, amount=Decimal("-6.40"), **flags)

    result = summary(scope, account)
    assert Decimal(result.smart_shipping_cost) == Decimal("6.40")
    assert Decimal(result.shipping_passthrough_cost) == Decimal("0")


def test_shipping_total_for_pln_orders_on_day(finance_scope):
    """The day's PLN fees total 2.10 + 3.20 + 4.30; EUR and another day are excluded."""
    scope, account = finance_scope
    paid = add_order(scope, account, price=Decimal("100"), delivery_amount=Decimal("10"))
    smart = add_order(scope, account, price=Decimal("100"))
    add_billing(scope, account, paid, type="HB4", amount=Decimal("-2.10"))
    add_billing(scope, account, paid, type="HLB", amount=Decimal("-3.20"))
    add_billing(scope, account, smart, type="ORB", amount=Decimal("-4.30"))
    eur = add_order(scope, account, price=Decimal("100"), currency="EUR")
    add_billing(scope, account, eur, type="HB4", amount=Decimal("-50"), currency="EUR")
    other_day = add_order(scope, account, price=Decimal("100"), bought_at=datetime(2026, 4, 13, 10))
    add_billing(scope, account, other_day, type="HLB", amount=Decimal("-60"))

    result = summary(scope, account)
    assert Decimal(result.shipping_passthrough_cost) == Decimal("2.10") + Decimal("3.20")
    assert Decimal(result.smart_shipping_cost) == Decimal("4.30")
    assert Decimal(result.smart_shipping_cost) + Decimal(result.shipping_passthrough_cost) == (
        Decimal("2.10") + Decimal("3.20") + Decimal("4.30")
    )


def test_passthrough_excluded_from_profit(finance_scope):
    """Adding a 7.25 passthrough fee leaves revenue and profit's Allegro costs unchanged."""
    scope, account = finance_scope
    order = add_order(scope, account, price=Decimal("100.00"), delivery_amount=Decimal("10.49"))
    before = summary(scope, account)
    add_billing(scope, account, order, type="HB4", amount=Decimal("-7.25"))
    after = summary(scope, account)

    assert Decimal(before.shipping_passthrough_cost) == Decimal("0")
    assert Decimal(after.shipping_passthrough_cost) == Decimal("7.25")
    assert after.revenue_net == before.revenue_net
    assert after.total_allegro == before.total_allegro
    assert after.total_allegro_net == before.total_allegro_net
    # Profit is calculated client-side; the backend supplies no profit value.
    assert before.profit_net is None and after.profit_net is None


def test_pnl_summary_passthrough_field():
    """PnLSummary retains the informational passthrough field and an independent profit field."""
    result = PnLSummary(period_label="test", date_from="", date_to="",
                        shipping_passthrough_cost="100.00", profit_net="287.00")
    assert Decimal(result.shipping_passthrough_cost) == Decimal("100.00")
    assert Decimal(result.profit_net) == Decimal("287.00")
