from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings, settings
from app.models.tenant import Tenant
from app.services.billing_state import imports_allowed


def test_deployment_mode_default_and_validation():
    field = Settings.model_fields["DEPLOYMENT_MODE"]
    assert field.default == "selfhosted"
    with pytest.raises(ValidationError):
        TypeAdapter(field.annotation).validate_python("invalid")


def test_imports_allowed_by_deployment_mode(monkeypatch):
    tenant = Tenant(id=1, is_active=True, created_at=datetime.now() - timedelta(days=60))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "selfhosted")
    assert imports_allowed(db, tenant) is True
    tenant.is_active = False
    assert imports_allowed(db, tenant) is False
    tenant.is_active = True
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "hosted")
    assert imports_allowed(db, tenant) is False


@pytest.mark.parametrize("method,path", [
    ("post", "/api/v1/auth/waitlist"),
    ("get", "/api/v1/auth/activate/token"),
    ("post", "/api/v1/auth/activate"),
    ("get", "/api/v1/admin/revenue"),
    ("get", "/api/v1/admin/tenants"),
    ("get", "/api/v1/admin/waitlist"),
    ("post", "/api/v1/admin/waitlist/1/approve"),
    ("post", "/api/v1/admin/waitlist/1/reject"),
    ("post", "/api/v1/admin/tenants/1/deactivate"),
    ("post", "/api/v1/admin/tenants/1/reactivate"),
    ("delete", "/api/v1/admin/tenants/1"),
    ("get", "/api/v1/billing/profile"),
    ("put", "/api/v1/billing/profile"),
    ("get", "/api/v1/billing/vat-lookup/1234567890"),
    ("post", "/api/v1/billing/paid-plan/accept"),
])
def test_hosted_routes_hidden_in_selfhosted(monkeypatch, authed_client, method, path):
    """Authenticated request reaches routing, so the 404 comes from require_hosted."""
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "selfhosted")
    response = getattr(authed_client, method)(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_selfhosted_subscription_and_health(monkeypatch, authed_client, seeded_db):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "selfhosted")
    assert authed_client.get("/api/v1/admin/system-health").status_code != 404
    response = authed_client.get("/api/v1/billing/subscription")
    assert response.status_code == 200
    data = response.json()
    assert data["deployment_mode"] == "selfhosted"
    assert data["imports_paused"] is False
    assert data["trial_started_at"] is None
    assert data["trial_ends_at"] is None
    assert data["current_tier"] is None
    assert data["pricing"] == []


def test_allegro_fee_labels_available_in_both_modes(monkeypatch, authed_client):
    """/billing/types holds Allegro fee labels used by the dashboard, not SaaS pricing."""
    for mode in ("selfhosted", "hosted"):
        monkeypatch.setattr(settings, "DEPLOYMENT_MODE", mode)
        assert authed_client.get("/api/v1/billing/types").status_code == 200


@pytest.mark.parametrize("mode", ["selfhosted", "hosted"])
def test_public_deployment_config(monkeypatch, app_client, mode):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", mode)
    for field in ("BRAND_SUPPORT_EMAIL", "PUBLIC_SITE_URL", "PUBLIC_APP_URL", "ANALYTICS_GA_ID", "ANALYTICS_AHREFS_KEY"):
        monkeypatch.setattr(settings, field, None)
    monkeypatch.setattr(settings, "BRAND_PRODUCT_NAME", "ProfitOS")
    response = app_client.get("/api/v1/public/config")
    assert response.status_code == 200
    assert response.json() == {
        "deployment_mode": mode,
        "brand": {"product_name": "ProfitOS", "support_email": None, "public_site_url": None, "app_url": None},
        "analytics": {"ga_id": None, "ahrefs_key": None},
    }


def test_public_config_values(monkeypatch, app_client):
    values = {"BRAND_PRODUCT_NAME": "Example", "BRAND_SUPPORT_EMAIL": "help@example.com",
              "PUBLIC_SITE_URL": "https://example.com", "PUBLIC_APP_URL": "https://app.example.com",
              "ANALYTICS_GA_ID": "G-ABC123", "ANALYTICS_AHREFS_KEY": "key_123"}
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    response = app_client.get("/api/v1/public/config")
    assert response.status_code == 200
    assert response.json()["brand"] == {"product_name": "Example", "support_email": "help@example.com",
                                        "public_site_url": "https://example.com", "app_url": "https://app.example.com"}
    assert response.json()["analytics"] == {"ga_id": "G-ABC123", "ahrefs_key": "key_123"}


@pytest.mark.parametrize("field,value", [("PUBLIC_SITE_URL", "ftp://example.com"),
    ("PUBLIC_APP_URL", "example.com"), ("ANALYTICS_GA_ID", "G-bad"),
    ("ANALYTICS_AHREFS_KEY", "bad key")])
def test_public_config_validation(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="sqlite://", SECRET_KEY="secret",
                 ALLEGRO_REDIRECT_URI="http://localhost", APP_BASE_URL="http://localhost", **{field: value})
