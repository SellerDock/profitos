"""Order-date attribution on isolated, synthetic finance data."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.services.dashboard_engine import DashboardEngine, get_custom_period
from tests.finance_fixtures import add_billing, add_order, add_payment_refund, finance_scope


def summary(scope, account, start, end=None):
    return DashboardEngine(scope).summary(get_custom_period(start, end or start), account_id=account.id)


def test_smart_shipping_attributed_to_order_date(finance_scope):
    """A 7.25 Smart fee booked three days later appears only on the purchase day."""
    scope, account = finance_scope
    order = add_order(scope, account, price=Decimal("100"))
    add_billing(scope, account, order, type="HB4", amount=Decimal("-7.25"),
                occurred_at=datetime(2026, 4, 15, 10))
    assert Decimal(summary(scope, account, "2026-04-12").smart_shipping_cost) == Decimal("7.25")
    assert Decimal(summary(scope, account, "2026-04-15").smart_shipping_cost) == 0


def test_proportional_split(finance_scope):
    """Smart 4.30 plus buyer-paid 2.10 + 3.20 preserves all 9.60 of shipping fees."""
    scope, account = finance_scope
    smart = add_order(scope, account, price=Decimal("100"))
    paid = add_order(scope, account, price=Decimal("100"), delivery_amount=Decimal("10"))
    later = datetime(2026, 4, 15, 10)
    add_billing(scope, account, smart, type="ORB", amount=Decimal("-4.30"), occurred_at=later)
    add_billing(scope, account, paid, type="HB4", amount=Decimal("-2.10"), occurred_at=later)
    add_billing(scope, account, paid, type="HLB", amount=Decimal("-3.20"), occurred_at=later)
    result = summary(scope, account, "2026-04-12")
    assert Decimal(result.smart_shipping_cost) == Decimal("4.30")
    assert Decimal(result.shipping_passthrough_cost) == Decimal("2.10") + Decimal("3.20")
    assert Decimal(result.smart_shipping_cost) + Decimal(result.shipping_passthrough_cost) == (
        Decimal("4.30") + Decimal("2.10") + Decimal("3.20")
    )


def test_sum_invariance(finance_scope):
    """Daily and whole-period costs both equal 2 + 3 + 4 + 5 + 6 + 7 - 1 = 26."""
    scope, account = finance_scope
    first = add_order(scope, account, price=Decimal("100"))
    second = add_order(scope, account, price=Decimal("100"), bought_at=datetime(2026, 4, 13, 10),
                       delivery_amount=Decimal("10"))
    later = datetime(2026, 4, 16, 10)
    for order, code, amount in [
        (first, "HB4", "-2"), (second, "HLB", "-3"), (first, "HB1", "-4"),
        (second, "CPF", "-5"), (first, "SUC", "-6"), (second, "FSF", "-7"),
        (first, "PS1", "1"),
    ]:
        add_billing(scope, account, order, type=code, amount=Decimal(amount), occurred_at=later)

    def total(result):
        return (Decimal(result.smart_shipping_cost) + Decimal(result.shipping_passthrough_cost)
                + Decimal(result.foreign_shipping_cost) + Decimal(result.coins_cost)
                + Decimal(result.commission_cost) + Decimal(result.featuring_commission_cost)
                - Decimal(result.price_adjust_cost))

    first_day = total(summary(scope, account, "2026-04-12"))
    second_day = total(summary(scope, account, "2026-04-13"))
    billing_day = total(summary(scope, account, "2026-04-16"))
    whole = total(summary(scope, account, "2026-04-12", "2026-04-16"))
    assert first_day == Decimal("2") + Decimal("4") + Decimal("6") - Decimal("1")
    assert second_day == Decimal("3") + Decimal("5") + Decimal("7")
    assert billing_day == 0
    assert whole == first_day + second_day + billing_day == Decimal("26")


def test_non_pln_orders_excluded(finance_scope):
    """Revenue is 2 × 50 PLN; CZK/EUR orders and a fully refunded 30 PLN sale are excluded."""
    scope, account = finance_scope
    add_order(scope, account, price=Decimal("50"), quantity=2)
    add_order(scope, account, price=Decimal("344"), currency="CZK")
    add_order(scope, account, price=Decimal("17"), quantity=2, currency="EUR")
    refunded = add_order(scope, account, price=Decimal("30"))
    add_payment_refund(scope, account, refunded, amount=Decimal("30"))
    assert Decimal(summary(scope, account, "2026-04-12").revenue_gross) == 2 * Decimal("50")


def test_billing_for_non_pln_orders_excluded(finance_scope):
    """Only PLN order fees remain: SUC 6, FSF 3, Smart 2 and foreign shipping 1."""
    scope, account = finance_scope
    pln = add_order(scope, account, price=Decimal("100"))
    czk = add_order(scope, account, price=Decimal("100"), currency="CZK")
    eur = add_order(scope, account, price=Decimal("100"), currency="EUR")
    for code, amount in [("SUC", "-6"), ("FSF", "-3"), ("HB4", "-2"), ("HB1", "-1")]:
        add_billing(scope, account, pln, type=code, amount=Decimal(amount), occurred_at=datetime(2026, 4, 14, 10))
        for foreign in (czk, eur):
            add_billing(scope, account, foreign, type=code, amount=Decimal("-50"), occurred_at=datetime(2026, 4, 14, 10))
    # A foreign-currency billing row is excluded even when its order is PLN.
    add_billing(scope, account, pln, type="SUC", amount=Decimal("-90"), currency="EUR")
    result = summary(scope, account, "2026-04-12")
    assert Decimal(result.commission_cost) == Decimal("6")
    assert Decimal(result.featuring_commission_cost) == Decimal("3")
    assert Decimal(result.smart_shipping_cost) == Decimal("2")
    assert Decimal(result.foreign_shipping_cost) == Decimal("1")


def test_non_pln_billing_does_not_pollute_other_days(finance_scope):
    """A two-line PLN order contributes SUC 10 - 3 = 7 once; EUR fees and FSF are separate."""
    scope, account = finance_scope
    order = add_order(scope, account, price=Decimal("100"))
    line = add_order(scope, account, price=Decimal("20"))
    line.order_id = order.order_id
    scope.db.flush()
    foreign = add_order(scope, account, price=Decimal("100"), currency="EUR",
                        bought_at=datetime(2026, 4, 13, 10))
    later = datetime(2026, 4, 15, 10)
    add_billing(scope, account, order, type="SUC", amount=Decimal("-10"), occurred_at=later)
    add_billing(scope, account, order, type="SUC", amount=Decimal("3"), occurred_at=later)
    add_billing(scope, account, order, type="FSF", amount=Decimal("-4"), occurred_at=later)
    add_billing(scope, account, foreign, type="SUC", amount=Decimal("-80"), occurred_at=later)
    result = summary(scope, account, "2026-04-12")
    assert Decimal(result.commission_cost) == Decimal("10") - Decimal("3")
    assert Decimal(result.featuring_commission_cost) == Decimal("4")
    assert Decimal(summary(scope, account, "2026-04-13").commission_cost) == 0
    assert Decimal(summary(scope, account, "2026-04-15").commission_cost) == 0


@pytest.mark.parametrize("code,field,amount", [
    ("SUC", "commission_cost", "-2"), ("FSF", "featuring_commission_cost", "-2"),
    ("HB4", "smart_shipping_cost", "-2"), ("HB1", "foreign_shipping_cost", "-2"),
    ("CPF", "coins_cost", "-2"), ("RCP", "coins_cost", "-2"),
    ("BRG", "campaign_commission_cost", "-2"), ("CB2", "campaign_bonus", "2"),
    ("PS1", "price_adjust_cost", "2"), ("PSA", "price_adjust_cost", "2"),
])
def test_fee_types_follow_order_date(finance_scope, code, field, amount):
    """Each isolated fee contributes its magnitude 2 on the order day and zero on billing day."""
    scope, account = finance_scope
    order = add_order(scope, account, price=Decimal("100"))
    add_billing(scope, account, order, type=code, amount=Decimal(amount), occurred_at=datetime(2026, 4, 13, 10))
    assert Decimal(getattr(summary(scope, account, "2026-04-12"), field)) == Decimal("2")
    assert Decimal(getattr(summary(scope, account, "2026-04-13"), field)) == 0


def test_warsaw_midnight(finance_scope):
    """21:30 UTC costs 4 on April 12; 22:30 UTC costs 7 on April 13 in Warsaw."""
    scope, account = finance_scope
    before = add_order(scope, account, price=Decimal("100"), bought_at=datetime(2026, 4, 12, 21, 30))
    after = add_order(scope, account, price=Decimal("100"), bought_at=datetime(2026, 4, 12, 22, 30))
    for order, amount in [(before, "-4"), (after, "-7")]:
        add_billing(scope, account, order, type="SUC", amount=Decimal(amount), occurred_at=datetime(2026, 4, 15, 10))
    assert Decimal(summary(scope, account, "2026-04-12").commission_cost) == Decimal("4")
    assert Decimal(summary(scope, account, "2026-04-13").commission_cost) == Decimal("7")
    assert Decimal(summary(scope, account, "2026-04-15").commission_cost) == 0


@pytest.mark.parametrize("code,field", [("FEA", "featuring_cost"), ("NSP", "ads_cost")])
def test_account_fees_follow_billing_date(finance_scope, code, field):
    """An unlinked 8 PLN account fee appears on its billing day, not the order day."""
    scope, account = finance_scope
    add_order(scope, account, price=Decimal("100"))
    add_billing(scope, account, None, type=code, amount=Decimal("-8"), occurred_at=datetime(2026, 4, 15, 10))
    assert Decimal(getattr(summary(scope, account, "2026-04-12"), field)) == 0
    assert Decimal(getattr(summary(scope, account, "2026-04-15"), field)) == Decimal("8")
