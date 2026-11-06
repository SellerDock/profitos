"""Configure a self-hosted instance from the server terminal."""
import argparse
import getpass
import sys

from app.core.config import is_hosted
from app.core.database import SessionLocal
from app.services.bootstrap import BootstrapError, bootstrap_instance


def main() -> int:
    parser = argparse.ArgumentParser(description="Konfiguracja instalacji self-hosted")
    parser.add_argument("--company", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password")
    args = parser.parse_args()

    if is_hosted():
        print("W trybie hosted użyj scripts.create_operator.", file=sys.stderr)
        return 1
    password = args.password
    if password is None:
        password = getpass.getpass("Hasło: ")
        if password != getpass.getpass("Powtórz hasło: "):
            print("Hasła nie są identyczne.", file=sys.stderr)
            return 1
    try:
        with SessionLocal() as db:
            bootstrap_instance(db, company_name=args.company, email=args.email, password=password)
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Konto utworzone. Przy pierwszym logowaniu skonfiguruj TOTP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
