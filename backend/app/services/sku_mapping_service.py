"""Service for regex-based SKU multiplier pattern matching."""
import re
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.sku import SkuMultiplierPattern


def load_patterns(db: Session, tenant_id: int) -> list[SkuMultiplierPattern]:
    """Load enabled patterns sorted by priority ascending (lower = checked first)."""
    return (
        db.query(SkuMultiplierPattern)
        .filter(SkuMultiplierPattern.tenant_id == tenant_id, SkuMultiplierPattern.enabled.is_(True))
        .order_by(SkuMultiplierPattern.priority.asc())
        .all()
    )


def apply_multiplier(
    offer_name: str,
    patterns: list[SkuMultiplierPattern],
) -> tuple[str, Decimal]:
    """Return (base_name, multiplier) for the first matching pattern.

    Iterates patterns in priority order. On match, capture group 1 becomes the
    base_name (stripped). Falls back to (offer_name, Decimal("1.0")) when nothing matches.
    """
    for pattern in patterns:
        try:
            m = re.match(pattern.pattern_regex, offer_name)
        except re.error:
            continue
        if m:
            try:
                base_name = m.group(1).strip()
            except IndexError:
                base_name = offer_name
            return base_name, pattern.multiplier
    builtin = re.match(r"^\s*(\d+)\s*x\s+(.+?)\s*$", offer_name, re.IGNORECASE)
    if builtin:
        return builtin.group(2).strip(), Decimal(builtin.group(1))
    return offer_name, Decimal("1.0")
