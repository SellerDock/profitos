import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.accounts import router as accounts_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.ads_import import router as ads_import_router
from app.api.allegro import accounts_callback_router as allegro_accounts_callback_router
from app.api.allegro import router as allegro_router
from app.api.app_download import router as app_download_router
from app.api.app_settings import router as app_settings_router
from app.api.billing import router as billing_router
from app.api.dashboard import router as dashboard_router
from app.api.financial_vault import router as financial_vault_router
from app.api.import_ import router as import_router
from app.api.integrations import router as integrations_router
from app.api.orders import router as orders_router
from app.api.sku_mapping import router as sku_mapping_router
from app.api.products import router as products_router
from app.api.public_config import router as public_config_router
from app.api.security import router as security_router
from app.api.skus import router as skus_router
from app.api.stock import router as stock_router
from app.api.support import router as support_router
from app.core.auth_dep import get_current_user
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.log_filters import AdsCostMaskingFilter, TenantContextLogger, install_tenant_log_record_factory
from app.core.security import extract_bearer_token, is_public_path, is_valid_api_token
from app.core.tenant_context import current_tenant_id
from app.services.bootstrap import assert_single_tenant

logger = logging.getLogger("apos")
install_tenant_log_record_factory()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [tenant=%(tenant_id)s] %(name)s — %(message)s")
tenant_log_filter = TenantContextLogger()
root_logger = logging.getLogger()
root_logger.addFilter(tenant_log_filter)
for handler in root_logger.handlers:
    handler.addFilter(tenant_log_filter)
logging.getLogger("app.api.ads_import").addFilter(AdsCostMaskingFilter())
logging.getLogger("apos.ads_import").addFilter(AdsCostMaskingFilter())

_is_prod = os.getenv("APP_ENV") == "production"
app = FastAPI(
    title=f"{settings.BRAND_PRODUCT_NAME} API",
    version="0.1.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)


@app.on_event("startup")
def check_deployment_database():
    # TestClient starts the app repeatedly while session tests add tenants.
    if os.getenv("APOS_TEST_DB", "").strip().lower() in {"1", "true", "yes"}:
        return
    with SessionLocal() as db:
        assert_single_tenant(db)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def tenant_context_middleware(request, call_next):
    token = current_tenant_id.set(None)
    try:
        return await call_next(request)
    finally:
        current_tenant_id.reset(token)


@app.middleware("http")
async def require_api_auth(request, call_next):
    path = request.url.path
    if not path.startswith("/api/v1") or request.method == "OPTIONS":
        return await call_next(request)

    authorization = request.headers.get("authorization")
    has_bearer = bool(extract_bearer_token(authorization))
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        xrw = request.headers.get("x-requested-with")
        csrf_exempt = path.startswith("/api/v1/allegro/callback")
        if xrw != "XMLHttpRequest" and not has_bearer and not csrf_exempt:
            return JSONResponse(
                {"detail": "CSRF protection: missing X-Requested-With header"},
                status_code=403,
            )

    if is_public_path(request):
        return await call_next(request)

    token = extract_bearer_token(authorization)
    if is_valid_api_token(token):
        return await call_next(request)

    if request.cookies.get("apos_session"):
        return await call_next(request)

    return JSONResponse(
        {"detail": "Authentication required"},
        status_code=401,
        headers={"WWW-Authenticate": "Cookie, Bearer"},
    )


protected = [Depends(get_current_user)]

app.include_router(public_config_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(app_download_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1", dependencies=protected)
app.include_router(accounts_router, prefix="/api/v1", dependencies=protected)
app.include_router(app_settings_router, prefix="/api/v1", dependencies=protected)
app.include_router(ads_import_router, prefix="/api/v1", dependencies=protected)
app.include_router(skus_router, prefix="/api/v1", dependencies=protected)
app.include_router(allegro_router, prefix="/api/v1")
app.include_router(allegro_accounts_callback_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1", dependencies=protected)
app.include_router(import_router, prefix="/api/v1", dependencies=protected)
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1", dependencies=protected)
app.include_router(dashboard_router, prefix="/api/v1", dependencies=protected)
app.include_router(financial_vault_router, prefix="/api/v1", dependencies=protected)
app.include_router(security_router, prefix="/api/v1")
app.include_router(stock_router, prefix="/api/v1", dependencies=protected)
app.include_router(orders_router, prefix="/api/v1", dependencies=protected)
app.include_router(sku_mapping_router, prefix="/api/v1", dependencies=protected)
app.include_router(support_router, prefix="/api/v1", dependencies=protected)


@app.get("/health")
def health():
    return {"status": "ok"}
