from datetime import date

from app.services.allegro import AllegroService, _extract_ads_service_date, _extract_billing_shipping_flags


def test_extracts_smart_shipping_flags_from_billing_additional_info():
    entry = {
        "additionalInfo": [
            {"type": "IS_FEE_SMART", "name": "Oplata Smart!", "value": "Tak"},
            {"type": "IS_ORDER_SMART", "name": "Zamowienie Smart!", "value": "Nie"},
        ]
    }

    assert _extract_billing_shipping_flags(entry) == (True, False)


def test_extracts_ads_service_date_from_nsp_billing_additional_info():
    entry = {
        "type": {"id": "NSP", "name": "Oplata za kampanie Ads"},
        "additionalInfo": [
            {"type": "feeDate", "name": "Oplata za dzien", "value": "06.05.2026"},
        ],
    }

    assert _extract_ads_service_date(entry) == date(2026, 5, 6)


def test_ads_service_date_ignores_non_ads_entries():
    entry = {
        "type": {"id": "SUC", "name": "Prowizja od sprzedazy"},
        "additionalInfo": [
            {"type": "feeDate", "name": "Oplata za dzien", "value": "06.05.2026"},
        ],
    }

    assert _extract_ads_service_date(entry) is None


def test_checkout_order_extracts_smart_and_delivery_method(monkeypatch):
    service = AllegroService(db=None)
    monkeypatch.setattr(service, "refresh_token_if_needed", lambda account_id: object())
    monkeypatch.setattr(service, "_paginate_by_date_windows", lambda *args, **kwargs: [{
        "id": "order-smart",
        "status": "READY_FOR_PROCESSING",
        "delivery": {
            "smart": True,
            "method": {"name": "Allegro Paczkomaty InPost"},
            "cost": {"amount": "0.00"},
        },
        "lineItems": [{
            "id": "line-smart",
            "offer": {"id": "offer-smart", "external": {"id": "SKU-SMART"}},
            "price": {"amount": "45.00", "currency": "PLN"},
            "quantity": 1,
            "boughtAt": "2026-07-21T10:00:00Z",
        }],
    }])

    row = service.get_all_orders(1, "2026-07-21T00:00:00Z", "2026-07-21T23:59:59Z")[0]

    assert row["delivery_is_smart"] is True
    assert row["delivery_method_name"] == "Allegro Paczkomaty InPost"
