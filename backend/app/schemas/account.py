from datetime import datetime
from pydantic import BaseModel

from app.schemas.strict import StrictMutationModel


class AccountBase(BaseModel):
    name: str
    allegro_client_id: str
    color: str = "#6366f1"


class AccountCreate(StrictMutationModel):
    name: str
    allegro_client_id: str
    color: str = "#6366f1"
    allegro_client_secret: str


class AccountUpdate(StrictMutationModel):
    name: str | None = None
    allegro_client_id: str | None = None
    allegro_client_secret: str | None = None
    color: str | None = None


class AccountRead(AccountBase):
    id: int
    created_at: datetime
    token_expires_at: datetime | None = None
    is_connected: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_status(cls, account) -> "AccountRead":
        obj = cls.model_validate(account)
        obj.is_connected = bool(account.access_token)
        return obj
