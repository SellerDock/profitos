"""Reset an operator password and revoke existing sessions."""
import argparse
import getpass

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.device_session import revoke_user_sessions
from app.core.security import hash_password
from app.models.user import User


def reset(db: Session, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.failed_login_attempts = 0
    user.locked_until = None
    revoke_user_sessions(db, user.id, reason="reset_password")
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    password = getpass.getpass("New password: ")
    repeat = getpass.getpass("Repeat password: ")
    if password != repeat:
        raise SystemExit("Passwords do not match")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email.lower()).first()
        if not user:
            raise SystemExit(f"User not found: {args.email.lower()}")
        reset(db, user, password)
    finally:
        db.close()
    print("Password reset and existing sessions revoked.")


if __name__ == "__main__":
    main()
