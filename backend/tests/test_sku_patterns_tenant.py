from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.sku import SkuAlias, SkuMultiplierPattern
from app.services.sku_mapping_service import apply_multiplier, load_patterns
from tests.test_tenant_isolation_endpoints import two_tenants  # noqa: F401


@pytest.fixture
def pattern_context(two_tenants):
    regex = f"^.*tenant-pattern-{uuid4().hex} (.*)$"
    try:
        yield two_tenants, regex
    finally:
        two_tenants.db.rollback()
        two_tenants.db.query(SkuMultiplierPattern).filter_by(pattern_regex=regex).delete()
        two_tenants.db.commit()


def test_patterns_are_isolated_and_foreign_mutations_return_404(pattern_context):
    ctx, regex = pattern_context
    headers = {"X-Requested-With": "XMLHttpRequest"}
    created = ctx.client_t1.post("/api/v1/sku-mapping/patterns", json={"pattern_regex": regex, "multiplier": 3}, headers=headers)
    assert created.status_code == 201, created.text
    pattern_id = created.json()["id"]
    listing = ctx.client_t2.get("/api/v1/sku-mapping/patterns")
    assert listing.status_code == 200
    assert pattern_id not in {row["id"] for row in listing.json()}
    assert ctx.client_t2.patch(f"/api/v1/sku-mapping/patterns/{pattern_id}", json={"description": "changed"}, headers=headers).status_code == 404
    assert ctx.client_t2.delete(f"/api/v1/sku-mapping/patterns/{pattern_id}", headers=headers).status_code == 404
    ctx.db.expire_all()
    pattern = ctx.db.get(SkuMultiplierPattern, pattern_id)
    assert pattern is not None and pattern.description is None and pattern.multiplier == Decimal("3")

    duplicate = ctx.client_t2.post("/api/v1/sku-mapping/patterns", json={"pattern_regex": regex, "multiplier": 4}, headers=headers)
    assert duplicate.status_code == 201, duplicate.text
    assert ctx.client_t1.post("/api/v1/sku-mapping/patterns", json={"pattern_regex": regex, "multiplier": 5}, headers=headers).status_code == 409
    assert pattern_id in {p.id for p in load_patterns(ctx.db, pattern.tenant_id)}
    tenant_b = ctx.db.get(SkuAlias, ctx.t2_alias_id).tenant_id
    assert pattern_id not in {p.id for p in load_patterns(ctx.db, tenant_b)}
    assert duplicate.json()["id"] in {p.id for p in load_patterns(ctx.db, tenant_b)}


def test_reapply_does_not_use_another_tenants_patterns(pattern_context):
    ctx, regex = pattern_context
    headers = {"X-Requested-With": "XMLHttpRequest"}
    created = ctx.client_t1.post("/api/v1/sku-mapping/patterns", json={"pattern_regex": regex, "multiplier": 7}, headers=headers)
    assert created.status_code == 201, created.text
    alias = ctx.db.get(SkuAlias, ctx.t2_alias_id)
    alias.raw_name += " " + regex.removeprefix("^.*").removesuffix(" (.*)$") + " product"
    alias.multiplier = Decimal("1")
    ctx.db.commit()
    pattern = ctx.db.get(SkuMultiplierPattern, created.json()["id"])
    assert apply_multiplier(alias.raw_name, [pattern])[1] == Decimal("7")
    response = ctx.client_t2.post("/api/v1/sku-mapping/reapply", headers=headers)
    assert response.status_code == 200, response.text
    ctx.db.expire_all()
    assert ctx.db.get(SkuAlias, ctx.t2_alias_id).multiplier == Decimal("1")
