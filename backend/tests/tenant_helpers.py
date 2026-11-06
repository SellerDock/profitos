from sqlalchemy.orm import Session

from app.core.tenant import TenantScope
from app.models.user import User


def operator_scope(db: Session) -> TenantScope:
    return TenantScope(
        db,
        User(
            id=0,
            email="legacy@bearer",
            password_hash="",
            is_operator=True,
            tenant_id=None,
            is_active=True,
        ),
    )
