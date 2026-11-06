import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.core.security import verify_password
from app.models.tenant import Tenant
from app.models.user import User
from app.services.bootstrap import BootstrapError, assert_single_tenant, bootstrap_instance


@pytest.fixture
def bootstrap_db():
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection) as db:
            # All deletes and the service's commit remain inside the outer transaction.
            for table in ("user_sessions", "device_sessions", "activation_tokens",
                          "tenant_paid_plan_acceptances", "users"):
                db.execute(text(f"DELETE FROM {table}"))
            try:
                yield db
            finally:
                db.close()
                transaction.rollback()


def test_bootstrap_creates_operator_and_locks(bootstrap_db):
    statements = []
    connection = bootstrap_db.connection()

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(connection, "before_cursor_execute", capture)
    try:
        user = bootstrap_instance(bootstrap_db, company_name="  Żółta Firma  ",
                                  email="ADMIN@EXAMPLE.COM", password="very-long-password")
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    tenant = bootstrap_db.get(Tenant, 1)
    assert (tenant.name, tenant.slug, tenant.is_active) == ("Żółta Firma", "zolta-firma", True)
    assert (user.email, user.tenant_id, user.is_operator, user.is_active, user.totp_secret) == (
        "admin@example.com", 1, True, True, None
    )
    assert verify_password(user.password_hash, "very-long-password")
    assert any("pg_advisory_xact_lock" in statement for statement in statements)


def test_second_bootstrap_fails(bootstrap_db):
    bootstrap_instance(bootstrap_db, company_name="Firma", email="a@example.com", password="long-password")
    with pytest.raises(BootstrapError, match="Instalacja jest już skonfigurowana"):
        bootstrap_instance(bootstrap_db, company_name="Inna", email="b@example.com", password="long-password")
    assert bootstrap_db.scalar(select(User.email)) == "a@example.com"


@pytest.mark.parametrize("company,email,password", [
    ("Firma", "a@example.com", "short"),
    ("Firma", "invalid", "long-password"),
    ("Firma", "admin@firma.invalid", "long-password"),
    ("Firma", "admin@localhost", "long-password"),
    ("Firma", "a b@example.com", "long-password"),
    ("  ", "a@example.com", "long-password"),
])
def test_invalid_bootstrap(bootstrap_db, company, email, password):
    with pytest.raises(BootstrapError):
        bootstrap_instance(bootstrap_db, company_name=company, email=email, password=password)
    assert bootstrap_db.scalar(select(User.id).limit(1)) is None


def test_bootstrap_rejects_multiple_tenants(bootstrap_db):
    bootstrap_db.add(Tenant(name="Druga", slug="bootstrap-druga", is_active=True))
    bootstrap_db.flush()
    with pytest.raises(BootstrapError, match="więcej niż jedną"):
        bootstrap_instance(bootstrap_db, company_name="Firma", email="a@example.com", password="long-password")


def test_single_tenant_selfhosted(bootstrap_db, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "selfhosted")
    assert_single_tenant(bootstrap_db)


@pytest.mark.parametrize("mode,raises", [("selfhosted", True), ("hosted", False)])
def test_multiple_tenants_guard(bootstrap_db, monkeypatch, mode, raises):
    bootstrap_db.add(Tenant(name="Druga", slug="bootstrap-druga", is_active=True))
    bootstrap_db.flush()
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", mode)
    if raises:
        with pytest.raises(RuntimeError, match="DEPLOYMENT_MODE=hosted"):
            assert_single_tenant(bootstrap_db)
    else:
        assert_single_tenant(bootstrap_db)


def test_bootstrap_email_accepted_by_login_model(bootstrap_db):
    from app.api.auth import LoginRequest

    user = bootstrap_instance(bootstrap_db, company_name="Firma", email=" Admin@Example.COM ",
                              password="very-long-password")
    LoginRequest(email=user.email, password="very-long-password")
