"""CRUD API for SKU multiplier patterns + reapply endpoint."""
import re
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import text

from app.core.tenant import TenantScope, get_scope
from app.schemas.strict import StrictMutationModel
from app.models.sku import SkuAlias, SkuMultiplierPattern
from app.models.raw_data import OfferCache
from app.services.sku_mapping_service import apply_multiplier, load_patterns

router = APIRouter(prefix="/sku-mapping", tags=["sku-mapping"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ── Schemas ────────────────────────────────────────────────────────────────────

class PatternRead(BaseModel):
    id: int
    pattern_regex: str
    multiplier: Decimal
    description: str | None
    priority: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatternCreate(StrictMutationModel):
    pattern_regex: str
    multiplier: Decimal
    description: str | None = None
    priority: int = 100
    enabled: bool = True

    @field_validator("pattern_regex")
    @classmethod
    def regex_must_compile(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regex: {exc}") from exc
        return v

    @field_validator("multiplier")
    @classmethod
    def multiplier_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("multiplier must be > 0")
        return v


class PatternUpdate(StrictMutationModel):
    pattern_regex: str | None = None
    multiplier: Decimal | None = None
    description: str | None = None
    priority: int | None = None
    enabled: bool | None = None

    @field_validator("pattern_regex")
    @classmethod
    def regex_must_compile(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"Invalid regex: {exc}") from exc
        return v

    @field_validator("multiplier")
    @classmethod
    def multiplier_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("multiplier must be > 0")
        return v


class TestRequest(StrictMutationModel):
    pattern_regex: str
    sample_offer_names: list[str]


class TestResultItem(BaseModel):
    offer_name: str
    matched: bool
    captured_group: str | None


class ReapplyResult(BaseModel):
    updated_count: int
    unchanged_count: int


class UnmatchedOffer(BaseModel):
    offer_id: str
    name: str
    sku: str | None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/patterns", response_model=list[PatternRead])
def list_patterns(scope: TenantScope = Depends(get_scope)):
    return (
        scope.db.query(SkuMultiplierPattern)
        .filter(SkuMultiplierPattern.tenant_id == scope.tenant_id)
        .order_by(SkuMultiplierPattern.priority.asc())
        .all()
    )


@router.post("/patterns", response_model=PatternRead, status_code=201)
def create_pattern(data: PatternCreate, scope: TenantScope = Depends(get_scope)):
    db = scope.db
    existing = (
        db.query(SkuMultiplierPattern)
        .filter(SkuMultiplierPattern.tenant_id == scope.tenant_id, SkuMultiplierPattern.pattern_regex == data.pattern_regex)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Pattern with this regex already exists")
    pattern = SkuMultiplierPattern(tenant_id=scope.tenant_id, **data.model_dump())
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern


@router.patch("/patterns/{pattern_id}", response_model=PatternRead)
def update_pattern(pattern_id: int, data: PatternUpdate, scope: TenantScope = Depends(get_scope)):
    db = scope.db
    pattern = db.get(SkuMultiplierPattern, pattern_id)
    scope.assert_owns(pattern)
    if data.pattern_regex is not None:
        existing = db.query(SkuMultiplierPattern).filter(
            SkuMultiplierPattern.tenant_id == scope.tenant_id,
            SkuMultiplierPattern.pattern_regex == data.pattern_regex,
            SkuMultiplierPattern.id != pattern_id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Pattern with this regex already exists")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(pattern, field, value)
    pattern.updated_at = _now()
    db.commit()
    db.refresh(pattern)
    return pattern


@router.delete("/patterns/{pattern_id}", status_code=204)
def delete_pattern(pattern_id: int, scope: TenantScope = Depends(get_scope)):
    db = scope.db
    pattern = db.get(SkuMultiplierPattern, pattern_id)
    scope.assert_owns(pattern)
    db.delete(pattern)
    db.commit()


@router.post("/test", response_model=list[TestResultItem])
def test_pattern(data: TestRequest):
    try:
        compiled = re.compile(data.pattern_regex)
    except re.error as exc:
        raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}")

    results: list[TestResultItem] = []
    for name in data.sample_offer_names:
        m = compiled.match(name)
        if m:
            try:
                captured = m.group(1)
            except IndexError:
                captured = None
            results.append(TestResultItem(offer_name=name, matched=True, captured_group=captured))
        else:
            results.append(TestResultItem(offer_name=name, matched=False, captured_group=None))
    return results


@router.post("/reapply", response_model=ReapplyResult)
def reapply_patterns(scope: TenantScope = Depends(get_scope)):
    """Re-run all enabled patterns against every SkuAlias and update multipliers."""
    patterns = load_patterns(scope.db, scope.tenant_id)
    aliases = scope.db.query(SkuAlias).filter(SkuAlias.tenant_id == scope.tenant_id).all()

    updated = unchanged = 0
    for alias in aliases:
        _, new_mult = apply_multiplier(alias.raw_name, patterns)
        if alias.multiplier != new_mult:
            alias.multiplier = new_mult
            updated += 1
        else:
            unchanged += 1

    scope.db.commit()
    return ReapplyResult(updated_count=updated, unchanged_count=unchanged)


@router.get("/unmatched-offers", response_model=list[UnmatchedOffer])
def unmatched_offers(scope: TenantScope = Depends(get_scope), limit: int = 5):
    """Return offers from offers_cache that don't match any enabled pattern — for UI suggestions."""
    patterns = load_patterns(scope.db, scope.tenant_id)
    offers = (
        scope.db.query(OfferCache)
        .filter(OfferCache.tenant_id == scope.tenant_id, OfferCache.name.isnot(None))
        .limit(500)
        .all()
    )

    unmatched: list[UnmatchedOffer] = []
    seen_names: set[str] = set()
    for offer in offers:
        name = offer.name or ""
        if name in seen_names:
            continue
        _, mult = apply_multiplier(name, patterns)
        if mult == Decimal("1.0"):
            seen_names.add(name)
            unmatched.append(UnmatchedOffer(
                offer_id=offer.offer_id,
                name=name,
                sku=offer.sku,
            ))
            if len(unmatched) >= limit:
                break

    return unmatched
