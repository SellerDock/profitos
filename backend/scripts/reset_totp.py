"""Reset a user's TOTP enrollment and revoke existing sessions."""
import argparse

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.device_session import revoke_user_sessions
from app.models.user import User


def reset(db: Session, user: User) -> None:
    user.totp_secret = None
    user.totp_enrolled_at = None
    revoke_user_sessions(db, user.id, reason="reset_totp")
    db.commit()


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
        reset(db, user)
    finally:
        db.close()
    print(f"User {email} may now log in and re-enroll TOTP.")


if __name__ == "__main__":
    main()
