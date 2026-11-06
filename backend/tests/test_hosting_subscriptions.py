import httpx
from datetime import date, timedelta

import pytest

from app.core.config import settings
from app.core.legal import TERMS_VERSION
from app.models.account import Account
from app.models.billing_profile import TenantBillingProfile, TenantPaidPlanAcceptance, TenantSubscription
from app.services.subscription_invoice import build_subscription_invoice_payload
from app.services.usage import usage_state
from tests.test_tenant_isolation_endpoints import two_tenants


def test_invoice_payload():
    sub = TenantSubscription(tier_code='year_5000', price_pln=299)
    profile = TenantBillingProfile(company_name='Firma', nip='123-456-78-90', street='Ulica 1',
        postal_code='00-001', city='Warszawa', invoice_email='a@example.com')
    payload = build_subscription_invoice_payload(sub, profile, date(2026, 11, 6))
    assert payload['Kontrahent']['NIP'] == '1234567890'
    assert payload['TerminPlatnosci'] == '2026-11-13'
    assert payload['Pozycje'][0]['CenaJednostkowa'] == 299.0
    assert 'pakiet roczny do 5000 zamówień miesięcznie, 12 miesięcy' in payload['Pozycje'][0]['NazwaPelna']


def test_subscription_workflow(two_tenants, monkeypatch):
    from app.api import admin, billing
    from app.models.tenant import Tenant

    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    sent = []
    monkeypatch.setattr(billing, 'send_subscription_request_admin_email', lambda **kw: sent.append(kw))
    db = two_tenants.db
    tenant_id = db.get(Account, two_tenants.t2_account_id).tenant_id
    tenant = db.get(Tenant, tenant_id)
    tenant.billing_scheme = 'pool_v2'
    tenant.free_pool_orders = 0
    from app.models.user import User
    # The shared fixture makes both users operators; tenant 2 must be a plain customer here.
    db.query(User).filter(User.tenant_id == tenant_id).update({User.is_operator: False})
    db.commit()
    customer, operator = two_tenants.client_t2, two_tenants.client_t1
    request = lambda tier='year_1000', version=TERMS_VERSION: customer.post('/api/v1/billing/subscription/request', json={'tier_code': tier, 'terms_version': version})
    try:
        assert customer.get('/api/v1/admin/subscriptions').status_code == 403
        assert request('custom').status_code == 422
        assert request(version='old').status_code == 409
        assert request().json()['detail'] == 'billing_profile_incomplete'
        db.add(TenantBillingProfile(tenant_id=tenant_id, company_name='Firma', nip='1234567890', street='Ulica 1', postal_code='00-001', city='Warszawa', invoice_email='a@example.com'))
        db.commit()
        response = request()
        assert response.status_code == 200
        sub_id = response.json()['id']
        assert len(sent) == 1
        assert request().json()['detail'] == 'subscription_pending'
        class ErrorClient:
            def create_domestic_invoice(self, payload):
                return {'response': {'Kod': 1, 'Informacja': 'Błąd faktury'}}
        monkeypatch.setattr(admin, 'IFirmaClient', ErrorClient)
        url = f'/api/v1/admin/subscriptions/{sub_id}/invoice'
        assert operator.post(url).status_code == 502
        db.expire_all()
        assert db.get(TenantSubscription, sub_id).status == 'pending_invoice'
        class TimeoutClient:
            def create_domestic_invoice(self, payload):
                raise httpx.ReadTimeout('timeout')
        monkeypatch.setattr(admin, 'IFirmaClient', TimeoutClient)
        response = operator.post(url)
        assert response.status_code == 502 and 'wpisz jej numer ręcznie' in response.json()['detail']
        db.expire_all()
        assert db.get(TenantSubscription, sub_id).status == 'pending_invoice'
        class Client:
            def create_domestic_invoice(self, payload):
                return {'response': {'Kod': 0, 'Identyfikator': 123}}
            def list_invoices(self, date_from):
                return {'response': {'Kod': 0, 'Wynik': [{'FakturaId': 7, 'PelnyNumer': 'FV 1/2026'}, {'FakturaId': 123, 'PelnyNumer': 'FV 2/2026'}]}}
        monkeypatch.setattr(admin, 'IFirmaClient', Client)
        response = operator.post(url)
        assert response.status_code == 200 and response.json()['invoice_number'] == 'FV 2/2026'
        assert operator.post(url).status_code == 409
        today = date.today()
        assert operator.post(f'/api/v1/admin/subscriptions/{sub_id}/mark-paid', json={'paid_on': today.isoformat()}).status_code == 200
        db.expire_all()
        assert usage_state(db, db.get(Tenant, tenant_id), today)['monthly_limit'] == 1000
        assert request().json()['detail'] == 'subscription_active'
        upgrade = request('year_5000').json()['id']
        assert operator.post(f'/api/v1/admin/subscriptions/{upgrade}/manual-invoice', json={'invoice_number': 'FV/1'}).status_code == 200
        assert operator.post(f'/api/v1/admin/subscriptions/{upgrade}/mark-paid', json={'paid_on': today.isoformat()}).status_code == 200
        db.expire_all()
        assert db.get(TenantSubscription, sub_id).status == 'expired'
        assert db.get(TenantSubscription, sub_id).period_end == today - timedelta(days=1)
        assert usage_state(db, db.get(Tenant, tenant_id), today)['monthly_limit'] == 5000
        assert db.query(TenantPaidPlanAcceptance).filter_by(tenant_id=tenant_id, terms_version=TERMS_VERSION).count() == 1
    finally:
        db.rollback()
        db.query(User).filter(User.tenant_id == tenant_id).update({User.is_operator: True})
        db.query(TenantSubscription).filter_by(tenant_id=tenant_id).delete()
        db.query(TenantPaidPlanAcceptance).filter_by(tenant_id=tenant_id).delete()
        db.query(TenantBillingProfile).filter_by(tenant_id=tenant_id).delete()
        db.commit()


def test_renewal_starts_after_current_plan(two_tenants, monkeypatch):
    from app.api import billing
    from app.models.tenant import Tenant
    from app.models.user import User

    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    monkeypatch.setattr(billing, 'send_subscription_request_admin_email', lambda **kw: None)
    db = two_tenants.db
    tenant_id = db.get(Account, two_tenants.t2_account_id).tenant_id
    db.get(Tenant, tenant_id).billing_scheme = 'pool_v2'
    db.query(User).filter(User.tenant_id == tenant_id).update({User.is_operator: False})
    today = date.today()
    current = TenantSubscription(tenant_id=tenant_id, tier_code='year_1000', price_pln=99, status='active',
                                 terms_version='v1', period_start=today - timedelta(days=300), period_end=today + timedelta(days=60))
    db.add(current)
    db.add(TenantBillingProfile(tenant_id=tenant_id, company_name='Firma', nip='1234567890', street='Ulica 1',
                                postal_code='00-001', city='Warszawa', invoice_email='a@example.com'))
    db.commit()
    customer, operator = two_tenants.client_t2, two_tenants.client_t1
    request = lambda: customer.post('/api/v1/billing/subscription/request', json={'tier_code': 'year_1000', 'terms_version': TERMS_VERSION})
    try:
        assert request().json()['detail'] == 'subscription_active'
        current.period_end = today + timedelta(days=20)
        db.commit()
        renewal = request().json()['id']
        assert operator.post(f'/api/v1/admin/subscriptions/{renewal}/manual-invoice', json={'invoice_number': 'FV/2'}).status_code == 200
        assert operator.post(f'/api/v1/admin/subscriptions/{renewal}/mark-paid', json={'paid_on': today.isoformat()}).status_code == 200
        db.expire_all()
        new = db.get(TenantSubscription, renewal)
        assert db.get(TenantSubscription, current.id).status == 'active'
        assert new.period_start == today + timedelta(days=21)
        assert usage_state(db, db.get(Tenant, tenant_id), today)['active_subscription']['tier_code'] == 'year_1000'
        assert request().json()['detail'] == 'subscription_renewed'
    finally:
        db.rollback()
        db.query(User).filter(User.tenant_id == tenant_id).update({User.is_operator: True})
        db.query(TenantSubscription).filter_by(tenant_id=tenant_id).delete()
        db.query(TenantPaidPlanAcceptance).filter_by(tenant_id=tenant_id).delete()
        db.query(TenantBillingProfile).filter_by(tenant_id=tenant_id).delete()
        db.commit()
