import hashlib
import hmac

from app.services.ifirma import IFirmaClient


def test_ifirma_auth_header_uses_iapis_hmac_sha1_with_hex_key():
    client = IFirmaClient(username="user@example.com", invoice_key="7365637265742d6b6579", key_name="faktura")
    url = "https://www.ifirma.pl/iapi/fakturakraj.json"
    body = '{"DataWystawienia":"2026-05-12"}'

    expected = hmac.new(
        bytes.fromhex("7365637265742d6b6579"),
        f"{url}user@example.comfaktura{body}".encode("utf-8"),
        hashlib.sha1,
    ).hexdigest()

    assert client._auth_header(url, body) == f"IAPIS user=user@example.com, hmac-sha1={expected}"
