"""Reset an operator password and revoke existing sessions."""
import argparse
import getpass

from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User


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
        user.password_hash = hash_password(password)
        user.failed_login_attempts = 0
        user.locked_until = None
        db.execute(text("UPDATE user_sessions SET revoked_at = now() WHERE user_id = :uid"), {"uid": user.id})
        db.commit()
    finally:
        db.close()
    print("Password reset and existing sessions revoked.")


if __name__ == "__main__":
    main()
