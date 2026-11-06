import re
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DEPLOYMENT_MODE: Literal["selfhosted", "hosted"] = "selfhosted"
    BRAND_PRODUCT_NAME: str = "ProfitOS"
    BRAND_SUPPORT_EMAIL: str | None = None
    PUBLIC_SITE_URL: str | None = None
    PUBLIC_APP_URL: str | None = None
    ANALYTICS_GA_ID: str | None = None
    ANALYTICS_AHREFS_KEY: str | None = None

    @field_validator("PUBLIC_SITE_URL", "PUBLIC_APP_URL")
    @classmethod
    def validate_public_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("Public URL must start with http:// or https://")
        return value

    @field_validator("ANALYTICS_GA_ID", "ANALYTICS_AHREFS_KEY")
    @classmethod
    def validate_analytics(cls, value: str | None, info) -> str | None:
        pattern = r"G-[A-Z0-9]+" if info.field_name == "ANALYTICS_GA_ID" else r"[A-Za-z0-9_-]+"
        if value is not None and not re.fullmatch(pattern, value):
            raise ValueError("Invalid analytics identifier")
        return value

    APP_ENV: str = "development"
    DATABASE_URL: str
    SECRET_KEY: str
    ALLEGRO_REDIRECT_URI: str
    ALLEGRO_USER_AGENT: str | None = None
    ALLEGRO_CLIENT_ID: str | None = None
    ALLEGRO_CLIENT_SECRET: str | None = None
    ALLEGRO_SCOPES: str = (
        "allegro:api:profile:read "
        "allegro:api:orders:read "
        "allegro:api:sale:offers:read "
        "allegro:api:billing:read "
        "allegro:api:payments:read"
    )
    APP_BASE_URL: str
    API_BEARER_TOKEN: str | None = None
    VAULT_SERVER_DECRYPTION_ENABLED: bool = False
    BACKEND_CORS_ORIGINS: str = "http://localhost:3001,http://127.0.0.1:3001"
    crypto_version: str = "1.0.0"
    crypto_source_commit: str = "6086252a6f44e6a880fb28515df4ffe3c80fd97b"
    crypto_repo_url: str = "https://github.com/SellerDock/profitos-crypto"
    crypto_release_url: str = "https://github.com/SellerDock/profitos-crypto/releases/tag/v1.0.0"
    crypto_bundle_sha256: str = "03636dd86c983cf4af2070f8d71fa1683fdbde81b7845fbb639aebc8adef557b"
    crypto_bundle_sri: str = "sha384-chRrfymBcFWbUgbpVrmpe+l2u34xxCjNI80/UQkNyaurfEh7tp/37xuF+is7IINY"
    crypto_decrypt_html_url: str = "https://github.com/SellerDock/profitos-crypto/releases/download/v1.0.0/decrypt.html"
    crypto_decrypt_html_sha256: str = "8ba1d5fe49905b019eb9c560caa7ecd8606936466b4607003848d4a52829d1af"
    operator_email: str | None = None
    auth_cookie_secure: bool | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str | None = None
    smtp_starttls: bool = True
    waitlist_admin_email: str | None = None
    ifirma_username: str | None = None
    ifirma_invoice_key: str | None = None
    ifirma_subscriber_key: str | None = None
    ifirma_invoice_key_name: str = "faktura"
    ifirma_api_base_url: str = "https://www.ifirma.pl/iapi"
    APK_DIST_DIR: str = "/app/apk_dist"

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.BACKEND_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def session_cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.APP_BASE_URL.startswith("https://")

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password and self.smtp_from_email)

    @property
    def ifirma_enabled(self) -> bool:
        return bool(self.ifirma_username and self.ifirma_invoice_key)

    model_config = {"env_file": ".env"}


settings = Settings()


def is_hosted() -> bool:
    return settings.DEPLOYMENT_MODE == "hosted"


def is_selfhosted() -> bool:
    return settings.DEPLOYMENT_MODE == "selfhosted"
