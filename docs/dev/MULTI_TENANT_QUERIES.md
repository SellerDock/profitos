# Multi-tenant queries

## Reguła

KAŻDE zapytanie do tabeli per-tenant musi być filtrowane po
`tenant_id == scope.tenant_id`. Brak filtra jest błędem bezpieczeństwa.

Per-tenant tables: `accounts`, `sku_masters`, `sku_aliases`,
`financial_vaults`, `encrypted_sku_costs`,
`encrypted_sku_cost_history`, `account_import_state`, `orders_raw`,
`billing_raw`, `order_events_raw`, `customer_returns_raw`,
`customer_return_items_raw`, `payment_refunds_raw`,
`payment_refund_line_items_raw`, `offers_cache`, `stock_levels`,
`stock_settings`, `allegro_ads_imports`, `sync_log`.

Globalne bez filtra: `billing_type_labels`, `sku_multiplier_patterns`,
`tenants`, `users`, `user_sessions`, `waitlist_entries`. Uwaga:
`users` jest globalną tabelą auth, ale każdy user ma obowiązkowe
`tenant_id` wskazujące jego tenant.

## Przykład SQLAlchemy 2.0

```python
from fastapi import Depends
from sqlalchemy import select

from app.core.tenant import TenantScope, get_scope
from app.models.account import Account


@router.get("/accounts")
def list_accounts(scope: TenantScope = Depends(get_scope)):
    return scope.db.execute(
        select(Account).where(Account.tenant_id == scope.tenant_id)
    ).scalars().all()
```

## Przykład raw SQL

Każdy `text()` z `SELECT` z tabeli per-tenant musi mieć warunek
`tenant_id = :tenant_id` oraz przekazać parametr.

```python
query = text(
    "SELECT * FROM orders_raw "
    "WHERE tenant_id = :tenant_id AND bought_at >= :date_from"
)
result = db.execute(
    query,
    {"tenant_id": scope.tenant_id, "date_from": period.start},
)
```

## IDOR prevention

Po `db.get(Model, id)` zawsze wywołaj `scope.assert_owns(obj)`.

```python
account = scope.db.get(Account, account_id)
scope.assert_owns(account)
```
