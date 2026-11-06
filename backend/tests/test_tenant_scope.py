import pytest
from fastapi import HTTPException

from app.core.tenant import TenantScope
from app.models.account import Account
from app.models.tenant import Tenant
from app.models.user import User


@pytest.mark.contract
def test_tenantscope_resolves_tenant_id(db_session):
    user = User(
        id=42,
        email="u@t",
        password_hash="hash",
        tenant_id=7,
        is_operator=False,
        is_active=True,
    )
    scope = TenantScope(db_session, user)
    assert scope.tenant_id == 7


@pytest.mark.contract
def test_tenantscope_legacy_bearer_maps_to_tenant_1(db_session):
    synthetic = User(
        id=0,
        email="legacy@bearer",
        password_hash="",
        tenant_id=None,
        is_operator=True,
        is_active=True,
    )
    scope = TenantScope(db_session, synthetic)
    assert scope.tenant_id == 1


@pytest.mark.contract
def test_assert_owns_raises_404_on_foreign_tenant(db_session):
    if db_session.get(Tenant, 2) is None:
        db_session.add(Tenant(id=2, name="Other", slug="other", is_active=True))
        db_session.flush()
    acc = Account(
        tenant_id=2,
        name="other",
        allegro_client_id="tenant-scope-other",
        allegro_client_secret="secret",
    )
    db_session.add(acc)
    db_session.commit()

    user = User(
        id=1,
        email="me",
        password_hash="hash",
        tenant_id=1,
        is_operator=True,
        is_active=True,
    )
    scope = TenantScope(db_session, user)

    with pytest.raises(HTTPException) as exc:
        scope.assert_owns(db_session.get(Account, acc.id))
    assert exc.value.status_code == 404

    db_session.delete(acc)
    other = db_session.get(Tenant, 2)
    if other:
        db_session.delete(other)
    db_session.commit()


@pytest.mark.contract
def test_assert_owns_passes_for_own_tenant(db_session):
    acc = Account(
        tenant_id=1,
        name="mine",
        allegro_client_id="tenant-scope-mine",
        allegro_client_secret="secret",
    )
    db_session.add(acc)
    db_session.commit()

    user = User(
        id=2,
        email="me",
        password_hash="hash",
        tenant_id=1,
        is_operator=True,
        is_active=True,
    )
    scope = TenantScope(db_session, user)
    scope.assert_owns(db_session.get(Account, acc.id))

    db_session.delete(acc)
    db_session.commit()
