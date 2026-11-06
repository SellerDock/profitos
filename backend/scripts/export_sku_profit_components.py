"""Read-only export of per-SKU profit components for one tenant and period.

Usage:
  docker exec apos-backend sh -c 'cd /app && \
    python -m scripts.export_sku_profit_components \
      --tenant-id <TENANT_ID> --date-from <YYYY-MM-DD> --date-to <YYYY-MM-DD> \
      --account-id <ACCOUNT_ID> [--account-id <ACCOUNT_ID> ...]'

The JSON document is written to stdout so a caller can pipe/parse it. The
script is strictly read-only: it performs no INSERT/UPDATE/DELETE, never
commits, and rolls the session back before exit.

Purchase costs live in a client-side encrypted Financial Vault. This script
does NOT decrypt anything and does not accept a password or key. It returns
the encrypted envelopes exactly as stored (plus the public vault parameters);
the caller is responsible for decryption.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace

from sqlalchemy import tuple_

from app.core.database import SessionLocal
from app.core.tenant import TenantScope
from app.models.account import Account
from app.models.sku import EncryptedSkuCost, FinancialVault
from app.services.dashboard_engine import DashboardEngine, get_custom_period

FORMAT_VERSION = 1
CURRENCY = "PLN"
VAULT_SCOPE = "global"


class ExportError(Exception):
    """Validation failure; rendered to stderr and mapped to exit code 2."""


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ExportError(f"Invalid date {value!r}; expected YYYY-MM-DD") from exc


def _dedupe(values: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _validate_accounts(db, tenant_id: int, account_ids: list[int]) -> None:
    if not account_ids:
        raise ExportError("At least one --account-id is required")
    accounts = db.query(Account).filter(Account.id.in_(account_ids)).all()
    by_id = {account.id: account for account in accounts}
    missing = [account_id for account_id in account_ids if account_id not in by_id]
    if missing:
        raise ExportError(
            "Unknown account id(s): " + ", ".join(str(a) for a in missing)
        )
    foreign = [
        account_id for account_id in account_ids
        if by_id[account_id].tenant_id != tenant_id
    ]
    if foreign:
        raise ExportError(
            f"Account id(s) {', '.join(str(a) for a in foreign)} do not belong "
            f"to tenant {tenant_id}"
        )


def _load_vault(db, tenant_id: int) -> dict | None:
    vault = (
        db.query(FinancialVault)
        .filter(FinancialVault.tenant_id == tenant_id, FinancialVault.scope == VAULT_SCOPE)
        .first()
    )
    if vault is None:
        return None
    return {
        "kdf": vault.kdf,
        "salt": vault.salt,
        "memory_cost": vault.memory_cost,
        "time_cost": vault.time_cost,
        "parallelism": vault.parallelism,
        "verify_nonce": vault.verify_nonce,
        "verify_ciphertext": vault.verify_ciphertext,
        "key_version": vault.key_version,
    }


def _load_cost_updated_at(db, tenant_id: int, envelopes: set[tuple[str, str]]) -> dict[tuple[str, str], datetime]:
    """Map (ciphertext, nonce) -> updated_at when unambiguous.

    The engine may serve a cost inherited from an alias or a "N x" bundle
    base; matching the returned envelope back to its source row gives the
    correct timestamp without reimplementing the inheritance rules. Envelopes
    are nonce-unique, so a key that matches more than one row is dropped.
    """
    if not envelopes:
        return {}
    rows = (
        db.query(
            EncryptedSkuCost.ciphertext,
            EncryptedSkuCost.nonce,
            EncryptedSkuCost.updated_at,
        )
        .filter(
            EncryptedSkuCost.tenant_id == tenant_id,
            tuple_(EncryptedSkuCost.ciphertext, EncryptedSkuCost.nonce).in_(list(envelopes)),
        )
        .all()
    )
    grouped: dict[tuple[str, str], list[datetime]] = {}
    for ciphertext, nonce, updated_at in rows:
        grouped.setdefault((ciphertext, nonce), []).append(updated_at)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}


def _serialize_row(row, account_id: int, cost_updated_at: dict[tuple[str, str], datetime]) -> dict:
    envelope = row.encrypted_cost
    updated_at = None
    if envelope:
        updated_at = cost_updated_at.get((envelope["ciphertext"], envelope["nonce"]))
    return {
        "account_id": account_id,
        "sku_key": row.sku_key,
        "units_sold": row.units_sold,
        "cogs_units": row.cogs_units,
        "revenue_net": row.revenue_net,
        "total_allegro_net": row.total_allegro_net,
        "price_adjust_cost": row.price_adjust_cost,
        "campaign_bonus": row.campaign_bonus,
        "refund_commission": row.refund_commission,
        "commission_refunds_amount": row.commission_refunds_amount,
        "cost_multiplier": row.cost_multiplier,
        "encrypted_cost": envelope,
        "cost_updated_at": updated_at.isoformat() if updated_at is not None else None,
    }


def build_export(
    db,
    *,
    tenant_id: int,
    date_from: date,
    date_to: date,
    account_ids: list[int],
) -> dict:
    """Build the export payload. Read-only; performs no writes."""
    accounts = _dedupe(account_ids)
    _validate_accounts(db, tenant_id, accounts)

    period = get_custom_period(date_from.isoformat(), date_to.isoformat())
    scope = TenantScope(db, SimpleNamespace(id=-1, tenant_id=tenant_id))
    engine = DashboardEngine(scope)

    collected: list[tuple[int, object]] = []
    for account_id in accounts:
        for row in engine.products(period, account_id, None, CURRENCY):
            collected.append((account_id, row))

    envelopes = {
        (row.encrypted_cost["ciphertext"], row.encrypted_cost["nonce"])
        for _, row in collected
        if row.encrypted_cost
    }
    cost_updated_at = _load_cost_updated_at(db, tenant_id, envelopes)

    rows = [
        _serialize_row(row, account_id, cost_updated_at)
        for account_id, row in collected
    ]

    return {
        "format": FORMAT_VERSION,
        "tenant_id": tenant_id,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "currency": CURRENCY,
        "generated_at": datetime.now(UTC).isoformat(),
        "vault": _load_vault(db, tenant_id),
        "rows": rows,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_sku_profit_components",
        description="Read-only per-SKU profit component export (encrypted costs, no decryption).",
    )
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD")
    parser.add_argument("--account-id", type=int, action="append", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        date_from = _parse_iso_date(args.date_from)
        date_to = _parse_iso_date(args.date_to)
        if date_from > date_to:
            raise ExportError("--date-from must be <= --date-to")
        account_ids = _dedupe(args.account_id)
        if not account_ids:
            raise ExportError("At least one --account-id is required")
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        payload = build_export(
            db,
            tenant_id=args.tenant_id,
            date_from=date_from,
            date_to=date_to,
            account_ids=account_ids,
        )
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.rollback()
        db.close()

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
