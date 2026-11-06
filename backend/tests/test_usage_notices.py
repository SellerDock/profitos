from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app import scheduler
from app.core.config import settings
from app.models.billing_profile import TenantSubscription, TenantUsageNotice
from app.models.tenant import Tenant
from app.models.user import User
from tests.finance_fixtures import add_order, finance_data


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    clock = [date(2026, 11, 6)]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.combine(clock[0], datetime.min.time(), tzinfo=tz or timezone.utc)

    monkeypatch.setattr(scheduler, 'datetime', FrozenDateTime)
    for name in ('send_usage_over_limit_email', 'send_upgrade_suggestion_email',
                 'send_renewal_reminder_email', 'send_subscription_expired_email'):
        monkeypatch.setattr(scheduler, name, Mock(return_value=True))
    return clock


@contextmanager
def account(db):
    with finance_data(db) as (scope, account):
        tenant = db.get(Tenant, scope.tenant_id)
        tenant.billing_scheme = 'pool_v2'
        tenant.free_pool_orders = 0
        tenant.created_at = datetime(2026, 1, 1)
        db.add(User(tenant_id=tenant.id, email=f'{uuid4().hex}@example.test', password_hash='', is_active=True))
        db.commit()
        try:
            yield tenant.id, scope, account
        finally:
            db.rollback()
            for model in (TenantUsageNotice, TenantSubscription, User):
                db.execute(delete(model).where(model.tenant_id == scope.tenant_id))
            db.commit()


def notices(db, tenant_id):
    db.expire_all()
    return {(n.kind, n.period_key) for n in db.query(TenantUsageNotice).filter_by(tenant_id=tenant_id).all()}


def subscription(db, tenant_id, end):
    db.add(TenantSubscription(tenant_id=tenant_id, tier_code='year_1000', price_pln=99,
                              status='active', terms_version='v1',
                              period_start=end - timedelta(days=365), period_end=end))
    db.commit()


def test_over_limit_once_and_retry_failed(hosted, db_session):
    with account(db_session) as (tenant_id, scope, shop):
        for _ in range(201):
            add_order(scope, shop, price=1, bought_at=datetime(2026, 11, 1))
        db_session.commit()
        scheduler.send_usage_over_limit_email.return_value = False
        scheduler.daily_usage_notice_job()
        assert not notices(db_session, tenant_id)
        scheduler.send_usage_over_limit_email.return_value = True
        scheduler.daily_usage_notice_job()
        scheduler.daily_usage_notice_job()
        assert scheduler.send_usage_over_limit_email.call_count == 2
        assert notices(db_session, tenant_id) == {('over_limit', '2026-11')}
        assert scheduler.send_usage_over_limit_email.call_args.kwargs['tier'].code == 'year_1000'


def test_upgrade_replaces_over_limit(hosted, db_session, monkeypatch):
    with account(db_session) as (tenant_id, _, __):
        state = {'pool_active': False, 'upgrade_suggested': True, 'over_limit': True,
                 'month': '2026-11', 'month_orders': 300, 'monthly_limit': 200,
                 'suggested_tier_code': 'year_1000'}
        monkeypatch.setattr(scheduler, 'usage_state', lambda *args: state)
        scheduler.daily_usage_notice_job()
        scheduler.daily_usage_notice_job()
        assert scheduler.send_upgrade_suggestion_email.call_count == 1
        scheduler.send_usage_over_limit_email.assert_not_called()
        assert notices(db_session, tenant_id) == {('over_limit', '2026-11'), ('upgrade_suggestion', '2026-11')}


def test_renewal_and_expiration(hosted, db_session):
    with account(db_session) as (tenant_id, _, __):
        end = hosted[0] + timedelta(days=30)
        subscription(db_session, tenant_id, end)
        scheduler.daily_usage_notice_job()
        scheduler.daily_usage_notice_job()
        hosted[0] = end - timedelta(days=7)
        scheduler.daily_usage_notice_job()
        scheduler.daily_usage_notice_job()
        assert scheduler.send_renewal_reminder_email.call_count == 2
        assert notices(db_session, tenant_id) == {('renewal_30d', end.isoformat()), ('renewal_7d', end.isoformat())}
        hosted[0] = end + timedelta(days=1)
        scheduler.send_subscription_expired_email.return_value = False
        scheduler.daily_usage_notice_job()
        db_session.expire_all()
        assert db_session.query(TenantSubscription).filter_by(tenant_id=tenant_id).one().status == 'expired'
        scheduler.send_subscription_expired_email.return_value = True
        scheduler.daily_usage_notice_job()
        scheduler.daily_usage_notice_job()
        assert scheduler.send_subscription_expired_email.call_count == 2
        assert ('expired', end.isoformat()) in notices(db_session, tenant_id)


def test_skips_legacy_selfhosted_and_active_pool(hosted, db_session, monkeypatch):
    with account(db_session) as (tenant_id, _, __):
        tenant = db_session.get(Tenant, tenant_id)
        tenant.billing_scheme = 'legacy_trial'
        db_session.commit()
        scheduler.daily_usage_notice_job()
        tenant.billing_scheme = 'pool_v2'
        tenant.free_pool_orders = 100
        db_session.commit()
        scheduler.daily_usage_notice_job()
        monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'selfhosted')
        tenant.free_pool_orders = 0
        db_session.commit()
        scheduler.daily_usage_notice_job()
        assert not notices(db_session, tenant_id)
        for name in ('send_usage_over_limit_email', 'send_upgrade_suggestion_email',
                     'send_renewal_reminder_email', 'send_subscription_expired_email'):
            getattr(scheduler, name).assert_not_called()


def test_one_tenant_failure_does_not_stop_others(hosted, db_session, monkeypatch):
    with account(db_session) as (first, _, __), account(db_session) as (second, _, __):
        actual = scheduler.usage_state

        def state(db, tenant, today):
            if tenant.id == first:
                raise ValueError('test error')
            result = actual(db, tenant, today)
            if tenant.id == second:
                result.update(over_limit=True, month_orders=201)
            return result

        monkeypatch.setattr(scheduler, 'usage_state', state)
        scheduler.daily_usage_notice_job()
        assert notices(db_session, first) == set()
        assert ('over_limit', '2026-11') in notices(db_session, second)


def test_no_expiry_mail_after_upgrade_or_for_old_expiry(hosted, db_session):
    with account(db_session) as (tenant_id, _, __):
        today = hosted[0]
        db_session.add(TenantSubscription(tenant_id=tenant_id, tier_code='year_1000', price_pln=99, status='expired',
                                          terms_version='v1', period_start=today - timedelta(days=100), period_end=today - timedelta(days=1)))
        db_session.add(TenantSubscription(tenant_id=tenant_id, tier_code='year_5000', price_pln=299, status='active',
                                          terms_version='v1', period_start=today, period_end=today + timedelta(days=364)))
        db_session.commit()
        scheduler.daily_usage_notice_job()
        scheduler.send_subscription_expired_email.assert_not_called()
        db_session.execute(delete(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id))
        db_session.add(TenantSubscription(tenant_id=tenant_id, tier_code='year_1000', price_pln=99, status='expired',
                                          terms_version='v1', period_start=today - timedelta(days=400), period_end=today - timedelta(days=30)))
        db_session.commit()
        scheduler.daily_usage_notice_job()
        scheduler.send_subscription_expired_email.assert_not_called()
