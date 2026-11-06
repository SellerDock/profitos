"""Create the initial operator account for hosted deployments.

Self-hosted installations use scripts.setup instead.

Usage:
  docker compose exec apos-backend python -m scripts.create_operator \
    --email admin@example.com --password '...'

Operator MUSI ustawić TOTP przy pierwszym loginie.
"""
import argparse
import getpass

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    db = SessionLocal()
    try:
        tenant = db.get(Tenant, 1)
        if tenant is None:
            tenant = Tenant(id=1, name="Operator", slug="operator", is_active=True)
            db.add(tenant)
            db.flush()
        existing = db.query(User).filter(User.email == args.email.lower()).first()
        if existing:
            raise SystemExit(f"User already exists: {args.email.lower()}")
        user = User(
            email=args.email.lower(),
            password_hash=hash_password(password),
            tenant_id=1,
            is_operator=True,
            is_active=True,
            totp_secret=None,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()
    print("Operator created. Enroll TOTP at /login on first sign-in.")


if __name__ == "__main__":
    main()
