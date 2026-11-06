from contextvars import ContextVar

current_tenant_id: ContextVar[int | None] = ContextVar("tenant_id", default=None)
