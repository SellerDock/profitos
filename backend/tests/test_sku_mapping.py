"""
Tests for SKU multiplier pattern CRUD and matching logic.

test_pattern_crud              — create/list/update/delete cycle
test_invalid_regex_rejected    — POST with bad regex returns 422
test_apply_multiplier_2x       — "2 x Glicynian" → ("Glicynian", 2.0)
test_apply_multiplier_no_match — "Glicynian" → ("Glicynian", 1.0)
test_apply_multiplier_priority — two overlapping patterns, lower priority int wins
test_reapply_updates_aliases   — add "3 x Magnez" offer + pattern, reapply → multiplier=3
"""
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.environ.get('POSTGRES_USER', 'apos_user')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'apos_pass')}@"
    f"{os.environ.get('POSTGRES_HOST', 'apos-db')}/"
    f"{os.environ.get('POSTGRES_DB', 'apos_db')}"
)
os.environ.setdefault("API_BEARER_TOKEN", "test-token")


# ── Pure-unit tests (no DB) ────────────────────────────────────────────────────

from app.models.sku import SkuMultiplierPattern
from app.services.sku_mapping_service import apply_multiplier


def _make_pattern(regex: str, multiplier: float, priority: int) -> SkuMultiplierPattern:
    p = SkuMultiplierPattern(tenant_id=1)
    p.pattern_regex = regex
    p.multiplier = Decimal(str(multiplier))
    p.priority = priority
    p.enabled = True
    return p


def test_apply_multiplier_2x():
    patterns = [_make_pattern(r"^2 x (.*)$", 2.0, 10)]
    base, mult = apply_multiplier("2 x Glicynian", patterns)
    assert base == "Glicynian"
    assert mult == Decimal("2.0")


def test_apply_multiplier_no_match():
    patterns = [_make_pattern(r"^2 x (.*)$", 2.0, 10)]
    base, mult = apply_multiplier("Glicynian", patterns)
    assert base == "Glicynian"
    assert mult == Decimal("1.0")


def test_apply_multiplier_builtin_numeric_prefix_without_configured_pattern():
    base, mult = apply_multiplier("2 x Glicynian Magnezu", [])
    assert base == "Glicynian Magnezu"
    assert mult == Decimal("2")


def test_apply_multiplier_priority():
    """Lower priority integer means checked first; that pattern's multiplier wins."""
    p_low = _make_pattern(r"^(\d+) x (.*)$", 99.0, 5)   # priority 5 — first
    p_high = _make_pattern(r"^2 x (.*)$", 2.0, 10)       # priority 10 — second
    # "2 x Omega" matches both; p_low (priority=5) should win
    _, mult = apply_multiplier("2 x Omega", [p_low, p_high])
    assert mult == Decimal("99.0")


# ── Integration tests (real DB via docker-compose) ─────────────────────────────

@pytest.fixture(scope="module")
def db_session():
    engine = create_engine(_DB_URL)
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="module")
def client():
    from app.core.config import settings
    from app.main import app
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {settings.API_BEARER_TOKEN}"})
        yield c


def _cleanup_pattern(client, pattern_id: int):
    client.delete(f"/api/v1/sku-mapping/patterns/{pattern_id}")


def test_pattern_crud(client):
    # Create
    resp = client.post("/api/v1/sku-mapping/patterns", json={
        "pattern_regex": r"^TEST_99 x (.*)$",
        "multiplier": 99,
        "description": "Test pattern",
        "priority": 999,
        "enabled": True,
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    pid = data["id"]
    assert data["pattern_regex"] == r"^TEST_99 x (.*)$"
    assert Decimal(data["multiplier"]) == Decimal("99")

    # List — pattern appears
    resp = client.get("/api/v1/sku-mapping/patterns")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert pid in ids

    # Update
    resp = client.patch(f"/api/v1/sku-mapping/patterns/{pid}", json={"description": "Updated desc"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated desc"

    # Delete
    resp = client.delete(f"/api/v1/sku-mapping/patterns/{pid}")
    assert resp.status_code == 204

    # Confirm gone
    resp = client.get("/api/v1/sku-mapping/patterns")
    ids_after = [p["id"] for p in resp.json()]
    assert pid not in ids_after


def test_invalid_regex_rejected(client):
    resp = client.post("/api/v1/sku-mapping/patterns", json={
        "pattern_regex": r"^[unclosed",
        "multiplier": 2,
    })
    assert resp.status_code == 422


def test_reapply_updates_aliases(client, db_session):
    """Insert a '3 x Magnez' offer + alias, add pattern, run reapply, verify multiplier=3."""
    # Ensure account 1 exists (required FK)
    account_exists = db_session.execute(
        text("SELECT id FROM accounts WHERE id = 1")
    ).fetchone()
    if not account_exists:
        pytest.skip("No account with id=1 in DB — skipping integration test")

    # Clean up any leftover state from previous test runs
    db_session.execute(text(
        "DELETE FROM sku_aliases WHERE raw_name = '3 x Magnez_TEST'"
    ))
    db_session.execute(text(
        "DELETE FROM sku_masters WHERE sku_key = 'magnez-test-99'"
    ))
    db_session.execute(text(
        "DELETE FROM offers_cache WHERE offer_id = 'test-offer-magnez-99'"
    ))
    db_session.commit()

    # Insert master + alias
    db_session.execute(text(
        "INSERT INTO sku_masters (tenant_id, sku_key, name, vat_rate, target_margin_pct) "
        "VALUES (1, 'magnez-test-99', '3 x Magnez_TEST', 23, 0)"
    ))
    db_session.commit()
    master_id = db_session.execute(
        text("SELECT id FROM sku_masters WHERE sku_key = 'magnez-test-99'")
    ).scalar()

    db_session.execute(text(
        "INSERT INTO sku_aliases (tenant_id, sku_master_id, account_id, raw_name, multiplier) "
        "VALUES (1, :mid, 1, '3 x Magnez_TEST', 1.0)"
    ), {"mid": master_id})
    db_session.commit()

    # Add the pattern
    resp = client.post("/api/v1/sku-mapping/patterns", json={
        "pattern_regex": r"^3 x (.*)$",
        "multiplier": 3,
        "description": "Pakiet 3 sztuki (test)",
        "priority": 998,
    })
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]

    try:
        # Run reapply
        resp = client.post("/api/v1/sku-mapping/reapply")
        assert resp.status_code == 200
        result = resp.json()
        assert result["updated_count"] >= 1

        # Verify multiplier updated
        row = db_session.execute(
            text("SELECT multiplier FROM sku_aliases WHERE raw_name = '3 x Magnez_TEST'")
        ).fetchone()
        assert row is not None
        assert Decimal(str(row.multiplier)) == Decimal("3.0")
    finally:
        # Cleanup
        _cleanup_pattern(client, pid)
        db_session.execute(text("DELETE FROM sku_aliases WHERE raw_name = '3 x Magnez_TEST'"))
        db_session.execute(text("DELETE FROM sku_masters WHERE sku_key = 'magnez-test-99'"))
        db_session.commit()
