"""CPF/RCP totals and the billing schema limitation."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from app.services.dashboard_engine import DashboardEngine, get_custom_period
from tests.finance_fixtures import add_billing, add_order, finance_scope


def test_cpf_total_invariant(finance_scope):
    """PLN CPF and RCP cost 2.50 + 1.25 = 3.75; a CZK order's 9.00 is excluded."""
    scope, account = finance_scope
    pln = add_order(scope, account, price=Decimal("49.90"))
    czk = add_order(scope, account, price=Decimal("100.00"), currency="CZK")
    # Billing dates differ from the purchase date: costs follow the order date.
    later = datetime(2026, 4, 15, 10)
    add_billing(scope, account, pln, type="CPF", amount=Decimal("-2.50"), occurred_at=later)
    add_billing(scope, account, pln, type="RCP", amount=Decimal("-1.25"), occurred_at=later)
    add_billing(scope, account, czk, type="CPF", amount=Decimal("-9.00"))
    summary = DashboardEngine(scope).summary(get_custom_period("2026-04-12", "2026-04-12"), account_id=account.id)
    assert Decimal(summary.coins_cost) == Decimal("2.50") + Decimal("1.25")


def test_cpf_api_has_no_description_field(db_session):
    """billing_raw has no description column to distinguish kinds of CPF fees."""
    result = db_session.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'billing_raw' AND column_name = 'description'"
    )).fetchall()
    assert not result
