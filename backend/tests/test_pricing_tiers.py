from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.admin import _estimate_subscription_amount_net
from app.api.billing import _tier_for_orders


@pytest.mark.parametrize(
    ("orders", "code"),
    [
        (199, "free_200"), (200, "free_200"), (201, "year_1000"),
        (1000, "year_1000"), (1001, "year_5000"),
        (5000, "year_5000"), (5001, "year_25000"),
        (25000, "year_25000"), (25001, "custom"),
    ],
)
def test_pricing_tier_boundaries(orders, code):
    tier = _tier_for_orders(orders)
    assert tier.code == code
    assert tier.is_custom is (code == "custom")


def test_annual_price_monthly_estimate_and_custom():
    tenant = SimpleNamespace(is_active=True, created_at=datetime(2026, 1, 1))
    assert _estimate_subscription_amount_net(tenant, 201, date(2026, 3, 1)) == (Decimal("8.25"), 31, 31)
    assert _estimate_subscription_amount_net(tenant, 25001, date(2026, 3, 1)) == (Decimal("0.00"), 31, 31)


def test_annual_price_prorated_after_trial():
    tenant = SimpleNamespace(is_active=True, created_at=datetime(2026, 2, 15))
    assert _estimate_subscription_amount_net(tenant, 201, date(2026, 3, 1)) == (Decimal("3.99"), 15, 31)
