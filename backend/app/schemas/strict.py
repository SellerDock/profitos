from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

PLAINTEXT_COST_DERIVED_FIELDS = {
    "cost",
    "cost_per_unit",
    "purchase_cost",
    "buy_price",
    "cogs",
    "profit",
    "profit_net",
    "margin_value",
    "margin_amount",
}


class StrictMutationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_plaintext_cost_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            offenders = PLAINTEXT_COST_DERIVED_FIELDS & data.keys()
            if offenders:
                raise ValueError(
                    "Plaintext cost-derived fields are not accepted: "
                    f"{sorted(offenders)}. Use encrypted_cost envelope."
                )
        return data
