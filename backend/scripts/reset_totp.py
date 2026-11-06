"""Reset a user's TOTP enrollment and revoke existing sessions."""
import argparse

from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.user import User


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    email = args.email.lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise SystemExit(f"User not found: {email}")
        user.totp_secret = None
        user.totp_enrolled_at = None
        db.execute(text("UPDATE user_sessions SET revoked_at = now() WHERE user_id = :uid"), {"uid": user.id})
        db.commit()
    finally:
        db.close()
    print(f"User {email} may now log in and re-enroll TOTP.")


if __name__ == "__main__":
    main()
