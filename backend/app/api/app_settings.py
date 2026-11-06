from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.tenant import TenantScope, get_scope
from app.schemas.strict import StrictMutationModel

router = APIRouter(prefix="/app-settings", tags=["app-settings"])

_DEFAULT_SETTINGS = {
    "is_vat_payer": False,
}


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _get_settings(scope: TenantScope) -> dict:
    rows = scope.db.execute(
        text("SELECT key, value FROM stock_settings WHERE tenant_id = :tenant_id AND key IN ('is_vat_payer')"),
        {"tenant_id": scope.tenant_id},
    ).fetchall()
    result = dict(_DEFAULT_SETTINGS)
    for row in rows:
        if row.key == "is_vat_payer":
            result["is_vat_payer"] = _parse_bool(row.value)
    return result


class AppSettingsUpdate(StrictMutationModel):
    is_vat_payer: bool


@router.get("/")
def get_app_settings(scope: TenantScope = Depends(get_scope)):
    return _get_settings(scope)


@router.put("/")
def update_app_settings(data: AppSettingsUpdate, scope: TenantScope = Depends(get_scope)):
    scope.db.execute(
        text(
            "INSERT INTO stock_settings (tenant_id, key, value) VALUES (:tenant_id, :key, :value) "
            "ON CONFLICT (tenant_id, key) DO UPDATE SET value = :value"
        ),
        {"tenant_id": scope.tenant_id, "key": "is_vat_payer", "value": 1 if data.is_vat_payer else 0},
    )
    scope.db.commit()
    return _get_settings(scope)
