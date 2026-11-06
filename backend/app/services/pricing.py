from typing import Literal

from pydantic import BaseModel


class PricingTier(BaseModel):
    code: str
    label: str
    max_orders: int | None
    price_pln: int
    billing_period: Literal["year", "free"]
    is_custom: bool = False


PRICING_TIERS = [
    PricingTier(code="free_200", label="Do 200 zamówień", max_orders=200, price_pln=0, billing_period="free"),
    PricingTier(code="year_1000", label="Do 1000 zamówień", max_orders=1000, price_pln=99, billing_period="year"),
    PricingTier(code="year_5000", label="Do 5000 zamówień", max_orders=5000, price_pln=299, billing_period="year"),
    PricingTier(code="year_25000", label="Do 25 000 zamówień", max_orders=25000, price_pln=499, billing_period="year"),
    PricingTier(code="custom", label="Powyżej 25 000 zamówień", max_orders=None, price_pln=0, billing_period="year", is_custom=True),
]


