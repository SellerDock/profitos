from decimal import Decimal
from pydantic import BaseModel

from app.schemas.strict import StrictMutationModel


class SkuMasterBase(BaseModel):
    sku_key: str
    name: str
    brand: str | None = None
    product_type: str | None = None
    vat_rate: Decimal = Decimal("23")
    target_margin_pct: Decimal = Decimal("0")
    notes: str | None = None


class SkuMasterCreate(StrictMutationModel):
    sku_key: str
    name: str
    brand: str | None = None
    product_type: str | None = None
    vat_rate: Decimal = Decimal("23")
    target_margin_pct: Decimal = Decimal("0")
    notes: str | None = None


class SkuMasterUpdate(StrictMutationModel):
    sku_key: str | None = None
    name: str | None = None
    brand: str | None = None
    product_type: str | None = None
    vat_rate: Decimal | None = None
    target_margin_pct: Decimal | None = None
    notes: str | None = None


class SkuMasterRead(SkuMasterBase):
    id: int

    model_config = {"from_attributes": True}


class SkuAliasBase(BaseModel):
    sku_master_id: int
    account_id: int
    raw_name: str
    multiplier: Decimal = Decimal("1.0")


class SkuAliasCreate(StrictMutationModel):
    sku_master_id: int
    account_id: int
    raw_name: str
    multiplier: Decimal = Decimal("1.0")


class SkuAliasUpdate(StrictMutationModel):
    raw_name: str | None = None
    multiplier: Decimal | None = None


class SkuAliasRead(SkuAliasBase):
    id: int

    model_config = {"from_attributes": True}
