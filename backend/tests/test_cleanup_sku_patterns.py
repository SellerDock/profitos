from app.models.sku import SkuMultiplierPattern
from app.models.tenant import Tenant
from app.services.cleanup import _hard_delete_tenant_data


def test_tenant_cleanup_deletes_sku_patterns(db_session):
    tenant = Tenant(name="Cleanup patterns", slug="cleanup-patterns-test", is_active=True)
    db_session.add(tenant)
    db_session.flush()
    tenant_id = tenant.id
    pattern = SkuMultiplierPattern(tenant_id=tenant_id, pattern_regex="cleanup-test", multiplier=2)
    db_session.add(pattern)
    db_session.flush()
    pattern_id = pattern.id
    _hard_delete_tenant_data(db_session, tenant_id)
    db_session.expire_all()
    assert db_session.get(Tenant, tenant_id) is None
    assert db_session.get(SkuMultiplierPattern, pattern_id) is None
    db_session.rollback()
