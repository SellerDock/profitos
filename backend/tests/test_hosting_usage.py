from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.tenant import get_scope
from app.core.config import settings
from app.models.billing_profile import TenantSubscription
from app.models.tenant import Tenant
from app.services import usage
from app.services.billing_state import imports_allowed
from tests.finance_fixtures import add_order, finance_data


def test_pool_counts_unique_orders_since_creation_and_isolates_tenants(db_session):
    with finance_data(db_session) as (scope, account), finance_data(db_session) as (other, other_account):
        tenant = db_session.get(Tenant, scope.tenant_id)
        tenant.created_at = datetime(2026, 1, 10, 12)
        tenant.free_pool_orders = 2
        add_order(scope, account, price=1, bought_at=datetime(2026, 1, 10, 11))
        order = add_order(scope, account, price=1, bought_at=datetime(2026, 1, 10, 12))
        second_line = add_order(scope, account, price=1, bought_at=datetime(2026, 1, 10, 13))
        second_line.order_id = order.order_id
        add_order(other, other_account, price=1, bought_at=datetime(2026, 1, 10, 12))
        db_session.flush()
        assert usage.pool_used(db_session, tenant) == 1
        assert usage.pool_remaining(db_session, tenant) == 1
        assert usage.orders_in_range(db_session, tenant.id, date(2026, 1, 10), date(2026, 1, 11)) == 2


def test_usage_limits_and_subscription(db_session):
    with finance_data(db_session) as (scope, account):
        tenant = db_session.get(Tenant, scope.tenant_id)
        tenant.created_at = datetime(2026, 1, 1)
        tenant.free_pool_orders = 0
        for _ in range(201):
            add_order(scope, account, price=1, bought_at=datetime(2026, 3, 1))
        state = usage.usage_state(db_session, tenant, date(2026, 3, 15))
        assert state['monthly_limit'] == 200 and state['over_limit']
        sub = TenantSubscription(tenant_id=tenant.id, tier_code='year_1000', price_pln=99,
                                 status='active', terms_version='v1', period_start=date(2026, 3, 15), period_end=date(2027, 3, 15))
        db_session.add(sub)
        db_session.flush()
        state = usage.usage_state(db_session, tenant, date(2026, 3, 15))
        assert state['monthly_limit'] == 1000 and not state['over_limit']
        assert state['active_subscription']['period_start'] == '2026-03-15'
        db_session.delete(sub)
        db_session.flush()


def test_upgrade_suggestion_uses_two_complete_months(monkeypatch):
    tenant = SimpleNamespace(id=1, free_pool_orders=0, billing_scheme='pool_v2')
    monkeypatch.setattr(usage, 'pool_used', lambda *_: 0)
    monkeypatch.setattr(usage, 'active_subscription', lambda *_: None)
    counts = {date(2026, 1, 1): 201, date(2026, 2, 1): 1001, date(2026, 3, 1): 0}
    monkeypatch.setattr(usage, 'orders_in_range', lambda db, tenant_id, start, end: counts[start])
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    state = usage.usage_state(db, tenant, date(2026, 3, 15))
    assert state['upgrade_suggested'] and state['suggested_tier_code'] == 'year_5000'
    counts[date(2026, 1, 1)] = 200
    assert not usage.usage_state(db, tenant, date(2026, 3, 15))['upgrade_suggested']


def test_imports_for_billing_schemes(monkeypatch):
    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    tenant = Tenant(id=1, is_active=True, billing_scheme='pool_v2', created_at=datetime.now() - timedelta(days=60))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert imports_allowed(db, tenant)
    tenant.billing_scheme = 'legacy_trial'
    assert not imports_allowed(db, tenant)
    tenant.is_active = False
    assert not imports_allowed(db, tenant)


@pytest.mark.parametrize('scheme', ['legacy_trial', 'pool_v2', None])
def test_subscription_response(monkeypatch, authed_client, scheme):
    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'selfhosted' if scheme is None else 'hosted')
    tenant = Tenant(id=1, is_active=True, billing_scheme=scheme, created_at=datetime(2026, 1, 1))
    db = MagicMock()
    db.get.return_value = tenant
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    monkeypatch.setattr('app.api.billing._orders_count', lambda *args: 0)
    monkeypatch.setattr('app.api.billing.usage_state', lambda *args: {'scheme': scheme})
    authed_client.app.dependency_overrides[get_scope] = lambda: SimpleNamespace(db=db, tenant_id=1)
    try:
        response = authed_client.get('/api/v1/billing/subscription')
    finally:
        authed_client.app.dependency_overrides.pop(get_scope, None)
    assert response.status_code == 200
    result = response.json()
    assert result['billing_scheme'] == scheme
    assert result['usage'] == ({'scheme': scheme} if scheme else None)
    if scheme == 'pool_v2' or scheme is None:
        assert result['trial_started_at'] is None and result['trial_ends_at'] is None
        assert result['trial_active'] is None and result['imports_paused'] is False
    else:
        assert result['trial_started_at'] == '2026-01-01'
        assert result['trial_ends_at'] == '2026-01-31'


def test_trial_end_email_skips_pool_tenants(monkeypatch, db_session):
    from app import scheduler
    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    checked = []
    monkeypatch.setattr(scheduler, 'trial_ends_at', lambda tenant, today: checked.append(tenant.id) or today)
    with finance_data(db_session) as (scope, _account):
        tenant = db_session.get(Tenant, scope.tenant_id)
        tenant.created_at = datetime.now() - timedelta(days=60)
        tenant.billing_scheme = 'pool_v2'
        db_session.commit()
        scheduler.daily_trial_end_email_job()
        assert tenant.id not in checked
        tenant.billing_scheme = 'legacy_trial'
        db_session.commit()
        scheduler.daily_trial_end_email_job()
        assert tenant.id in checked
