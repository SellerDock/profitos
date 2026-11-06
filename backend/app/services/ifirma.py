from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.core.config import settings


class IFirmaNotConfigured(RuntimeError):
    pass


class IFirmaClient:
    """Minimal iFirma API client for invoice endpoints.

    iFirma signs requests as HMAC-SHA1 over:
    url + username + key_name + request_body
    """

    def __init__(self, *, username: str | None = None, invoice_key: str | None = None, key_name: str | None = None):
        self.username = username or settings.ifirma_username
        self.invoice_key = invoice_key or settings.ifirma_invoice_key
        self.key_name = key_name or settings.ifirma_invoice_key_name
        self.base_url = settings.ifirma_api_base_url.rstrip("/")
        if not self.username or not self.invoice_key:
            raise IFirmaNotConfigured("iFirma username and invoice key are required")

    def _auth_header(self, url: str, body: str = "") -> str:
        message = f"{url}{self.username}{self.key_name}{body}".encode("utf-8")
        digest = hmac.new(bytes.fromhex(self.invoice_key), message, hashlib.sha1).hexdigest()
        return f"IAPIS user={self.username}, hmac-sha1={digest}"

    def _headers(self, url: str, body: str = "") -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-type": "application/json; charset=UTF-8",
            "Authentication": self._auth_header(url, body),
        }

    def list_invoices(self, *, date_from: str, date_to: str | None = None, status: str | None = None) -> dict[str, Any]:
        params = {"dataOd": date_from}
        if date_to:
            params["dataDo"] = date_to
        if status:
            params["status"] = status
        url = f"{self.base_url}/faktury.json"
        response = httpx.get(url, params=params, headers=self._headers(url), timeout=30)
        response.raise_for_status()
        return response.json()

    def create_domestic_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/fakturakraj.json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        response = httpx.post(url, content=body.encode("utf-8"), headers=self._headers(url, body), timeout=60)
        response.raise_for_status()
        return response.json()
