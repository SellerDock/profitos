from decimal import Decimal

from app.models.account import Account
from app.services.allegro import (
    ALLEGRO_API_BASE,
    AllegroService,
    _extract_ean_from_product_set,
    _extract_vat_rate,
)


def test_extract_vat_rate_prefers_polish_tax_settings_rate():
    offer = {
        "taxSettings": {
            "rates": [
                {"countryCode": "DE", "rate": "19"},
                {"countryCode": "PL", "rate": "8.00"},
            ]
        }
    }

    assert _extract_vat_rate(offer) == Decimal("8.00")


def test_extract_vat_rate_supports_legacy_tax_shape():
    assert _extract_vat_rate({"tax": {"percentage": "5"}}) == Decimal("5")


def test_extract_vat_rate_rejects_out_of_range_values():
    assert _extract_vat_rate({"taxSettings": {"rates": [{"countryCode": "PL", "rate": "100"}]}}) is None


def test_extract_ean_from_realistic_product_offer_shape():
    offer = {
        "productSet": [{
            "product": {
                "id": "0ca14fc3-7084-4fa2-83da-d04104e8b162",
                "parameters": [{
                    "id": "225693",
                    "name": "EAN (GTIN)",
                    "values": ["5900000000000"],
                }],
            },
        }],
    }

    assert _extract_ean_from_product_set(offer) == "5900000000000"


def test_get_all_offers_fetches_product_offer_details_when_list_omits_metadata(monkeypatch):
    service = AllegroService(db=None)  # type: ignore[arg-type]
    account = Account(id=17, tenant_id=1, name="VAT detail account")

    monkeypatch.setattr(service, "refresh_token_if_needed", lambda account_id: account)
    monkeypatch.setattr(service, "_headers", lambda refreshed_account: {"Authorization": "Bearer test"})
    monkeypatch.setattr(
        service,
        "_paginate_offset",
        lambda account, url, params, data_key: [{
            "id": "18587652864",
            "external": {"id": "SKU-8"},
            "name": "Produkt 8%",
            "sellingMode": {"price": {"amount": "108.00", "currency": "PLN"}},
            "stock": {"available": 12},
        }],
    )

    detail_urls = []

    class Response:
        def json(self):
            return {
                "taxSettings": {"rates": [{"countryCode": "PL", "rate": "8.00"}]},
                "productSet": [{
                    "product": {
                        "parameters": [{
                            "id": "225693",
                            "name": "EAN (GTIN)",
                            "values": ["5900000000000"],
                        }],
                    },
                }],
            }

    def fake_get(url, params, headers, timeout=30.0, max_attempts=3):
        detail_urls.append(url)
        return Response()

    monkeypatch.setattr(service, "_get_with_retry", fake_get)

    rows = service.get_all_offers(account.id)

    assert rows[0]["vat_rate"] == "8.00"
    assert rows[0]["ean"] == "5900000000000"
    assert detail_urls == [f"{ALLEGRO_API_BASE}/sale/product-offers/18587652864"]
