import secrets
import base64

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from starlette.requests import Request

from app.core.config import settings

PUBLIC_API_PATHS = (
    "/api/v1/public/config",
    "/api/v1/auth/login",
    "/api/v1/auth/waitlist",
    "/api/v1/auth/totp/enroll",
    "/api/v1/auth/activate",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/device/logout",
    "/api/v1/allegro/callback",
    "/api/v1/accounts/allegro/callback",
    "/api/v1/security/crypto-proof",
    "/api/v1/app/manifest",
    "/api/v1/app/download",
)

PUBLIC_API_PREFIXES = (
    "/api/v1/allegro/auth/",
    "/api/v1/auth/activate/",
)


def is_public_path(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    path = request.url.path.rstrip("/")
    if path == "/health":
        return True
    if any(path == public.rstrip("/") for public in PUBLIC_API_PATHS):
        return True
    return any(request.url.path.startswith(prefix) for prefix in PUBLIC_API_PREFIXES)


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def is_valid_api_token(token: str | None) -> bool:
    configured_token = settings.API_BEARER_TOKEN
    if not configured_token or not token:
        return False
    return secrets.compare_digest(token, configured_token)


_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hash_str: str, password: str) -> bool:
    try:
        _hasher.verify(hash_str, password)
        return True
    except (VerifyMismatchError, InvalidHash):
        return False


def needs_rehash(hash_str: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hash_str)
    except InvalidHash:
        return True


def new_session_token() -> str:
    raw = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
