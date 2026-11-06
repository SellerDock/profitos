"""Approve a waitlist entry by creating a tenant and one-time activation link.

Usage:
  docker compose exec apos-backend python -m scripts.approve_waitlist \
    --email user@company.com --tenant-name 'Acme Sp. z o.o.'

The raw activation token is printed once and never stored. The database
stores only sha256(raw_token), matching the admin panel flow.
"""
import argparse
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.user import ActivationToken, User, WaitlistEntry


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or f"tenant-{secrets.token_hex(4)}"


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--operator-email")
    parser.add_argument("--base-url", default=settings.APP_BASE_URL)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        email = args.email.lower()
        entry = db.query(WaitlistEntry).filter(WaitlistEntry.email == email).first()
        if entry is None:
            raise SystemExit(f"Waitlist entry not found: {email}")
        if entry.approved_at is not None:
            raise SystemExit(f"Waitlist entry already approved: {email}")

        operator_query = db.query(User).filter(User.is_operator.is_(True), User.is_active.is_(True))
        if args.operator_email:
            operator_query = operator_query.filter(User.email == args.operator_email.lower())
        operator = operator_query.order_by(User.id.asc()).first()
        if operator is None:
            raise SystemExit("No active operator user found; create one first with scripts.create_operator")

        base_slug = _slugify(args.tenant_name)
        slug = base_slug
        suffix = 2
        while db.query(Tenant).filter(Tenant.slug == slug).first() is not None:
            slug = f"{base_slug[:58]}-{suffix}"
            suffix += 1

        tenant = Tenant(name=args.tenant_name, slug=slug, is_active=True)
        db.add(tenant)
        db.flush()

        raw_token = secrets.token_urlsafe(32)
        activation = ActivationToken(
            token_hash=_token_hash(raw_token),
            waitlist_entry_id=entry.id,
            tenant_id=tenant.id,
            email=email,
            created_by_user_id=operator.id,
            expires_at=_now() + timedelta(days=7),
        )
        db.add(activation)
        entry.approved_at = _now()
        db.commit()

        activation_url = f"{args.base_url.rstrip('/')}/activate?token={raw_token}"
        print(f"Tenant created: id={tenant.id} slug={tenant.slug}")
        print(f"Activation URL: {activation_url}")
        print("Raw token is shown once; database stores only sha256(raw_token).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
