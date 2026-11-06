"""Initial configuration and deployment-mode database checks."""
import re
import unicodedata

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import is_selfhosted
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User

# Stable PostgreSQL transaction-scoped lock reserved for instance bootstrap.
BOOTSTRAP_ADVISORY_LOCK = 2026050401


class BootstrapError(Exception):
    """The instance cannot be initialized with the supplied data."""


def bootstrap_instance(db: Session, *, company_name: str, email: str, password: str) -> User:
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": BOOTSTRAP_ADVISORY_LOCK})
    if db.scalar(select(User.id).limit(1)) is not None:
        raise BootstrapError("Instalacja jest już skonfigurowana")
    if db.scalar(select(func.count()).select_from(Tenant)) > 1:
        raise BootstrapError("Instalacja zawiera więcej niż jedną firmę")

    company_name = company_name.strip()
    email = email.strip().lower()
    if not company_name:
        raise BootstrapError("Nazwa firmy nie może być pusta")
    try:
        # Same rules as pydantic EmailStr used by the login endpoint, so the
        # created administrator can always log in.
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise BootstrapError(f"Niepoprawny adres e-mail: {exc}") from exc
    if len(password) < 12:
        raise BootstrapError("Hasło musi mieć co najmniej 12 znaków")

    normalized = unicodedata.normalize("NFKD", company_name.lower().replace("ł", "l"))
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:64].rstrip("-") or "firma"
    tenant = db.get(Tenant, 1)
    if tenant is None:
        tenant = Tenant(id=1, name=company_name, slug=slug, is_active=True)
        db.add(tenant)
    else:
        tenant.name = company_name
        tenant.slug = slug
        tenant.is_active = True
    user = User(email=email, password_hash=hash_password(password), tenant_id=1,
                is_operator=True, is_active=True, totp_secret=None)
    db.add(user)
    db.commit()
    return user


def assert_single_tenant(db: Session) -> None:
    if is_selfhosted() and db.scalar(select(func.count()).select_from(Tenant)) > 1:
        raise RuntimeError(
            "Instalacja self-hosted obsługuje jedną firmę; baza wygląda na bazę hostingu. "
            "Ustaw DEPLOYMENT_MODE=hosted."
        )
