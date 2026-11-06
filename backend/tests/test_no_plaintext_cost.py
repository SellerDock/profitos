import json

import pytest

FORBIDDEN_NUMERIC_FIELDS = {
    "cost_per_unit",
    "cogs",
    "profit_net",
    "profit_30d",
    "profit",
    "margin_pct",
    "roi_pct",
}


def assert_no_plaintext_cost(payload, path=""):
    if isinstance(payload, dict):
        for key, value in payload.items():
            full = f"{path}.{key}" if path else key
            if key in FORBIDDEN_NUMERIC_FIELDS:
                if value is None or value == "" or value == "null":
                    continue
                try:
                    n = float(value)
                    assert n == 0.0, (
                        f"{full} contains non-zero plaintext cost-derived value: {value}"
                    )
                except (TypeError, ValueError):
                    pytest.fail(f"{full} contains unexpected non-numeric, non-null value: {value!r}")
            else:
                assert_no_plaintext_cost(value, full)
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            assert_no_plaintext_cost(item, f"{path}[{i}]")


@pytest.mark.contract
@pytest.mark.parametrize("endpoint", [
    "/api/v1/products/",
    "/api/v1/dashboard/summary?period=last_30d",
    "/api/v1/dashboard/summary/all",
    "/api/v1/dashboard/summary/comparisons",
    "/api/v1/dashboard/products?period=last_30d",
    "/api/v1/orders/recent",
])
def test_endpoint_returns_no_plaintext_cost(authed_client, seeded_db, endpoint):
    response = authed_client.get(endpoint)
    assert response.status_code == 200, response.text
    assert_no_plaintext_cost(response.json())


@pytest.mark.contract
def test_product_detail_returns_no_plaintext_cost(authed_client, seeded_db):
    response = authed_client.get(
        f"/api/v1/dashboard/product-detail?sku_key={seeded_db['sku_a_key']}&period=last_30d"
    )
    assert response.status_code == 200, response.text
    assert_no_plaintext_cost(response.json())


@pytest.mark.contract
@pytest.mark.parametrize("key", [
    "today",
    "yesterday",
    "last_7d",
    "last_14d",
    "last_30d",
    "last_90d",
    "current_month",
    "last_month",
    "ytd",
])
def test_dashboard_summary_supports_period(authed_client, seeded_db, key):
    response = authed_client.get(f"/api/v1/dashboard/summary?period={key}")
    assert response.status_code == 200, response.text


@pytest.mark.contract
def test_dashboard_summary_unknown_period_returns_422(authed_client):
    response = authed_client.get("/api/v1/dashboard/summary?period=last_42d")
    assert response.status_code == 422
    assert "last_42d" in response.text


@pytest.mark.contract
def test_encrypted_cost_export_only_envelope(authed_client, seeded_db):
    sku_id = seeded_db["sku_a_id"]
    response = authed_client.get(f"/api/v1/security/encrypted-cost-export/{sku_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body.keys()) <= {"envelope", "sku", "note"}
    env = body["envelope"]
    assert set(env.keys()) == {
        "v", "alg", "kdf", "kdfParams", "salt", "iv", "ct", "aad", "keyVersion",
    }
    assert "cost" not in body["sku"]
    assert "price" not in body["sku"]

    flat = json.dumps(body)
    forbidden = ["plaintext", "plain_cost", "unencrypted", "decrypted"]
    for word in forbidden:
        assert word not in flat.lower(), f"{word!r} leaked into export response"
