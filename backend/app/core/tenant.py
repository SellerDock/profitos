import logging

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth_dep import get_current_user
from app.core.database import get_db
from app.core.tenant_context import current_tenant_id
from app.models.user import User

logger = logging.getLogger("apos.tenant")


class TenantScope:
    """Scope object passed to repository functions.

    ALL queries on per-tenant tables must explicitly filter on
    ``Model.tenant_id == scope.tenant_id``. Legacy bearer-token callers map to
    tenant 1 to preserve current operator integrations.
    """

    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.tenant_id = self._resolve_tenant(user)

    def _resolve_tenant(self, user: User) -> int:
        if user.id == 0:
            return 1
        if user.tenant_id is None:
            raise HTTPException(500, f"User {user.id} has no tenant_id; data corruption")
        return user.tenant_id

    def assert_owns(self, obj) -> None:
        """Verify that an entity loaded by ID belongs to this tenant."""
        if obj is None:
            raise HTTPException(404, "not found")
        owned = getattr(obj, "tenant_id", None)
        if owned != self.tenant_id:
            raise HTTPException(404, "not found")


def get_scope(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantScope:
    scope = TenantScope(db, user)
    current_tenant_id.set(scope.tenant_id)
    logger.info("tenant scope resolved user_id=%s tenant_id=%s", user.id, scope.tenant_id)
    return scope
