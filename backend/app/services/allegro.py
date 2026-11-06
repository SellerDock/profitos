import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.account import Account, AllegroAccountClaim

logger = logging.getLogger("apos.allegro")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

ALLEGRO_AUTH_URL = "https://allegro.pl/auth/oauth/authorize"
ALLEGRO_TOKEN_URL = "https://allegro.pl/auth/oauth/token"
ALLEGRO_API_BASE = "https://api.allegro.pl"
# Allegro requires a custom User-Agent on every REST API call
# (Allegro REST API terms, art. 3.4.c — mandatory since 2026-06-30).
def allegro_user_agent() -> str:
    if settings.ALLEGRO_USER_AGENT is not None:
        return settings.ALLEGRO_USER_AGENT
    return f"ProfitOS/0.1.0 (+{settings.APP_BASE_URL})"

# Allegro hard limit: offset + limit <= 10 000
ALLEGRO_MAX_OFFSET = 10_000


class AllegroService:
    def __init__(self, db: Session):
        self.db = db

    # ── OAuth ──────────────────────────────────────────────────────────────

    def get_auth_url(self, redirect_uri: str, state: str, account: Account | None = None) -> str:
        client_id, _ = self._client_credentials(account)
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        scopes = _normalize_scopes(settings.ALLEGRO_SCOPES)
        if scopes:
            params["scope"] = scopes
        return f"{ALLEGRO_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, account_id: int, code: str, redirect_uri: str) -> Account:
        account = self._get_account(account_id)
        token_data = self.exchange_code_for_tokens(code, redirect_uri, account)
        return self._save_tokens(account, token_data)

    def exchange_code_for_tokens(
        self,
        code: str,
        redirect_uri: str,
        account: Account | None = None,
    ) -> dict:
        client_id, client_secret = self._client_credentials(account)
        resp = httpx.post(
            ALLEGRO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=(client_id, client_secret),
            headers={"User-Agent": allegro_user_agent()},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_current_user_profile(self, access_token: str) -> dict:
        resp = httpx.get(
            f"{ALLEGRO_API_BASE}/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.allegro.public.v1+json",
                "Content-Type": "application/vnd.allegro.public.v1+json",
                "User-Agent": allegro_user_agent(),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def upsert_account_from_profile(
        self,
        tenant_id: int,
        profile: dict,
        token_data: dict,
        account: Account | None = None,
    ) -> Account:
        allegro_user_id = str(profile.get("id") or "").strip()
        if not allegro_user_id:
            raise ValueError("Allegro profile response did not include user id")

        claim = (
            self.db.query(AllegroAccountClaim)
            .filter(AllegroAccountClaim.allegro_user_id == allegro_user_id)
            .first()
        )
        if claim and (account is None or claim.account_id != account.id):
            raise ValueError(
                "To konto Allegro było już wcześniej dodane do ProfitOS. "
                "Jeśli to pomyłka, napisz do supportu."
            )

        existing = account or (
            self.db.query(Account)
            .filter(Account.tenant_id == tenant_id, Account.allegro_user_id == allegro_user_id)
            .first()
        )
        client_id, client_secret = self._client_credentials(existing)
        if existing is None:
            existing = Account(
                tenant_id=tenant_id,
                name=_account_name_from_profile(profile),
                allegro_client_id=client_id,
                allegro_client_secret=client_secret,
                allegro_user_id=allegro_user_id,
            )
            self.db.add(existing)
            self.db.flush()
        else:
            existing.name = _account_name_from_profile(profile)
            existing.allegro_client_id = client_id
            existing.allegro_client_secret = client_secret
            existing.allegro_user_id = allegro_user_id

        saved = self._save_tokens(existing, token_data, commit=False)
        if claim is None:
            self.db.add(AllegroAccountClaim(
                allegro_user_id=allegro_user_id,
                tenant_id=tenant_id,
                account_id=saved.id,
                account_name=saved.name,
            ))
        else:
            claim.tenant_id = tenant_id
            claim.account_id = saved.id
            claim.account_name = saved.name
        self.db.commit()
        self.db.refresh(saved)
        return saved

    def refresh_token_if_needed(self, account_id: int) -> Account:
        account = self._get_account(account_id)
        if not account.refresh_token:
            raise ValueError(f"Account {account_id} has no refresh token — run OAuth first")
        if (
            account.token_expires_at
            and account.token_expires_at > _now() + timedelta(minutes=5)
        ):
            return account
        resp = httpx.post(
            ALLEGRO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": account.refresh_token,
            },
            auth=self._client_credentials(account),
            headers={"User-Agent": allegro_user_agent()},
            timeout=15,
        )
        resp.raise_for_status()
        return self._save_tokens(account, resp.json())

    # ── Paginated data fetchers ────────────────────────────────────────────

    def get_all_orders(self, account_id: int, date_from: str, date_to: str) -> list[dict]:
        """Return all checkout-form line items. Uses 7-day date windows to stay
        within Allegro's offset+limit ≤ 10 000 constraint."""
        account = self.refresh_token_if_needed(account_id)
        forms = self._paginate_by_date_windows(
            account,
            url=f"{ALLEGRO_API_BASE}/order/checkout-forms",
            base_params={"limit": 100},
            data_key="checkoutForms",
            date_from=_parse_iso(date_from),
            date_to=_parse_iso(date_to),
            gte_param="lineItems.boughtAt.gte",
            lte_param="lineItems.boughtAt.lte",
        )
        rows: list[dict] = []
        for form in forms:
            order_id = form.get("id", "")
            buyer_login = (form.get("buyer") or {}).get("login", "")
            status = form.get("status", "")
            delivery = form.get("delivery") or {}
            delivery_cost_obj = delivery.get("cost") or {}
            delivery_method = delivery.get("method") or {}
            delivery_amount = delivery_cost_obj.get("amount", "0")
            for item in form.get("lineItems", []):
                offer = item.get("offer") or {}
                external = offer.get("external") or {}
                price_obj = item.get("price") or {}
                vat_rate = _extract_vat_rate(item)
                rows.append({
                    "line_item_id": item.get("id", f"{order_id}_unknown"),
                    "order_id": order_id,
                    "offer_id": offer.get("id"),
                    "sku": external.get("id"),
                    "buyer_login": buyer_login,
                    "quantity": int(item.get("quantity", 1)),
                    "unit_price": price_obj.get("amount", "0"),
                    "vat_rate": str(vat_rate) if vat_rate is not None else None,
                    "delivery_amount": delivery_amount,
                    # These fields are intentionally kept with the import payload
                    # (rather than the order-line table): they are needed to create
                    # a short-lived Smart estimate per checkout form.
                    "delivery_is_smart": delivery.get("smart") is True,
                    "delivery_method_name": delivery_method.get("name"),
                    "currency": price_obj.get("currency", "PLN"),
                    "status": status,
                    "bought_at": item.get("boughtAt"),
                })
        return rows

    def get_all_billing(self, account_id: int, date_from: str, date_to: str) -> list[dict]:
        """Billing API has strict offset+limit ≤ 10 000. We iterate over 7-day
        windows so each window's offset stays well within the limit."""
        account = self.refresh_token_if_needed(account_id)
        entries = self._paginate_by_date_windows(
            account,
            url=f"{ALLEGRO_API_BASE}/billing/billing-entries",
            base_params={"limit": 100},
            data_key="billingEntries",
            date_from=_parse_iso(date_from),
            date_to=_parse_iso(date_to),
            gte_param="occurredAt.gte",
            lte_param="occurredAt.lte",
        )
        seen: set[str] = set()
        rows: list[dict] = []
        for e in entries:
            entry_id = e.get("id", "")
            if entry_id in seen:
                continue  # windows may overlap at boundaries
            seen.add(entry_id)
            value = e.get("value") or {}
            offer = e.get("offer") or {}
            order = e.get("order") or {}
            type_obj = e.get("type") or {}
            shipping_is_smart, shipping_order_is_smart = _extract_billing_shipping_flags(e)
            ads_service_date = _extract_ads_service_date(e)
            rows.append({
                "entry_id": entry_id,
                "offer_id": offer.get("id"),
                "order_id": order.get("id"),
                "type": type_obj.get("id"),
                "amount": value.get("amount", "0"),
                "currency": value.get("currency", "PLN"),
                "occurred_at": e.get("occurredAt"),
                "ads_service_date": ads_service_date.isoformat() if ads_service_date else None,
                "shipping_is_smart": shipping_is_smart,
                "shipping_order_is_smart": shipping_order_is_smart,
            })
        return rows

    def get_latest_order_event(self, account_id: int) -> dict | None:
        """Return latest order event stats cursor."""
        account = self.refresh_token_if_needed(account_id)
        resp = self._get_with_retry(
            f"{ALLEGRO_API_BASE}/order/event-stats",
            params={},
            headers=self._headers(account),
            timeout=15,
        )
        return resp.json().get("latestEvent")

    def get_order_events(self, account_id: int, from_event_id: str, limit: int = 1000) -> list[dict]:
        """Return subsequent order events after the stored cursor."""
        account = self.refresh_token_if_needed(account_id)
        params: dict = {
            "from": from_event_id,
            "limit": limit,
            "type": [
                "BUYER_CANCELLED",
                "AUTO_CANCELLED",
                "READY_FOR_PROCESSING",
                "FULFILLMENT_STATUS_CHANGED",
            ],
        }
        rows: list[dict] = []
        while True:
            resp = self._get_with_retry(
                f"{ALLEGRO_API_BASE}/order/events",
                params=params,
                headers=self._headers(account),
                timeout=30,
            )
            events = resp.json().get("events", [])
            if not events:
                break
            rows.extend(events)
            if len(events) < limit:
                break
            next_from = events[-1].get("id")
            if not next_from or next_from == params["from"]:
                break
            params["from"] = next_from
        return rows

    def get_all_customer_returns(self, account_id: int, date_from: str, date_to: str) -> list[dict]:
        """Fetch customer returns in a createdAt date window."""
        account = self.refresh_token_if_needed(account_id)
        limit = 1000
        offset = 0
        rows: list[dict] = []
        while True:
            resp = self._get_with_retry(
                f"{ALLEGRO_API_BASE}/order/customer-returns",
                params={
                    "limit": limit,
                    "offset": offset,
                    "createdAt.gte": date_from,
                    "createdAt.lte": date_to,
                },
                headers=self._headers(account, accept="application/vnd.allegro.beta.v1+json"),
                timeout=30,
            )
            items = resp.json().get("customerReturns", [])
            rows.extend(items)
            if len(items) < limit:
                break
            offset += limit
        return rows

    def get_all_payment_refunds(self, account_id: int, date_from: str, date_to: str) -> list[dict]:
        """Fetch payment refunds in a created/occurred date window."""
        account = self.refresh_token_if_needed(account_id)
        limit = 100
        offset = 0
        rows: list[dict] = []
        while True:
            resp = self._get_with_retry(
                f"{ALLEGRO_API_BASE}/payments/refunds",
                params={
                    "limit": limit,
                    "offset": offset,
                    "occurredAt.gte": date_from,
                    "occurredAt.lte": date_to,
                },
                headers=self._headers(account),
                timeout=30,
            )
            items = resp.json().get("refunds", [])
            rows.extend(items)
            if len(items) < limit:
                break
            offset += limit
        return rows

    def get_billing_types(self, account_id: int) -> list[dict]:
        """Fetch the full list of Allegro billing type definitions.
        Returns list of {"id": str, "name": str} dicts."""
        account = self.refresh_token_if_needed(account_id)
        resp = httpx.get(
            f"{ALLEGRO_API_BASE}/billing/billing-types",
            headers=self._headers(account),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        # API returns a plain list, not a wrapped object
        return data if isinstance(data, list) else data.get("billingTypes", [])

    def get_all_offers(self, account_id: int) -> list[dict]:
        """Offers have no date filter — plain offset pagination (bounded dataset)."""
        account = self.refresh_token_if_needed(account_id)
        offers = self._paginate_offset(
            account,
            url=f"{ALLEGRO_API_BASE}/sale/offers",
            params={"limit": 1000, "publication.status": "ACTIVE"},
            data_key="offers",
        )
        rows: list[dict] = []
        for o in offers:
            offer_id = o.get("id", "")
            external = o.get("external") or {}
            selling = o.get("sellingMode") or {}
            price_obj = selling.get("price") or {}
            ean = _extract_ean_from_product_set(o)
            vat_rate = _extract_vat_rate(o)
            if offer_id and (vat_rate is None or ean is None):
                detail_vat_rate, detail_ean = self._get_offer_detail_metadata(account, offer_id)
                vat_rate = vat_rate if vat_rate is not None else detail_vat_rate
                ean = ean or detail_ean
            stock = o.get("stock") or {}
            rows.append({
                "offer_id": offer_id,
                "sku": external.get("id"),
                "name": o.get("name"),
                "price": price_obj.get("amount"),
                "vat_rate": str(vat_rate) if vat_rate is not None else None,
                "currency": price_obj.get("currency", "PLN"),
                "ean": ean,
                "stock_available": _safe_int(stock.get("available")),
            })
        return rows

    def _get_offer_detail_metadata(
        self,
        account: Account,
        offer_id: str,
    ) -> tuple[Decimal | None, str | None]:
        """Fetch VAT and EAN because the offer-list endpoint omits product details."""
        try:
            resp = self._get_with_retry(
                f"{ALLEGRO_API_BASE}/sale/product-offers/{offer_id}",
                params={},
                headers=self._headers(account),
                timeout=20.0,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            logger.warning("Could not fetch Allegro offer details offer_id=%s status=%s", offer_id, status)
            return None, None
        except httpx.HTTPError as exc:
            logger.warning("Could not fetch Allegro offer details offer_id=%s: %s", offer_id, exc)
            return None, None
        detail = resp.json()
        return _extract_vat_rate(detail), _extract_ean_from_product_set(detail)

    # ── Pagination helpers ─────────────────────────────────────────────────

    def _paginate_by_date_windows(
        self,
        account: Account,
        url: str,
        base_params: dict,
        data_key: str,
        date_from: datetime,
        date_to: datetime,
        gte_param: str,
        lte_param: str,
        window_days: int = 7,
    ) -> list[dict]:
        """Split the date range into windows and paginate each window with offset.
        This ensures offset never exceeds ALLEGRO_MAX_OFFSET - limit."""
        results: list[dict] = []
        limit = int(base_params.get("limit", 100))
        max_pages_per_window = ALLEGRO_MAX_OFFSET // limit  # e.g. 100 pages @ limit=100

        window_start = date_from
        while window_start < date_to:
            window_end = min(window_start + timedelta(days=window_days), date_to)
            params = {
                **base_params,
                gte_param: window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                lte_param: window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            logger.debug("Fetching %s window %s – %s", data_key, window_start.date(), window_end.date())

            for page in range(max_pages_per_window):
                params["offset"] = page * limit
                resp = self._get_with_retry(url, params=params, headers=self._headers(account))
                items = resp.json().get(data_key, [])
                results.extend(items)
                if len(items) < limit:
                    break
                if page == max_pages_per_window - 1:
                    logger.warning(
                        "Window %s–%s hit offset ceiling (%d entries). "
                        "Reduce window_days if data loss is a concern.",
                        window_start.date(), window_end.date(),
                        max_pages_per_window * limit,
                    )

            window_start = window_end

        return results

    def _paginate_offset(
        self,
        account: Account,
        url: str,
        params: dict,
        data_key: str,
    ) -> list[dict]:
        """Simple offset pagination. Stops when a page returns fewer items than limit."""
        results: list[dict] = []
        params = dict(params)
        limit = int(params.get("limit", 100))
        max_pages = ALLEGRO_MAX_OFFSET // limit

        for page in range(max_pages):
            params["offset"] = page * limit
            resp = self._get_with_retry(url, params=params, headers=self._headers(account))
            items = resp.json().get(data_key, [])
            results.extend(items)
            if len(items) < limit:
                break

        return results

    # ── HTTP with retry ────────────────────────────────────────────────────

    def _get_with_retry(
        self,
        url: str,
        params: dict,
        headers: dict,
        timeout: float = 30.0,
        max_attempts: int = 3,
    ) -> httpx.Response:
        """GET with exponential backoff retry on network errors, 5xx, and 429."""
        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(max_attempts):
            try:
                resp = httpx.get(url, params=params, headers=headers, timeout=timeout)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                    logger.warning("Rate limited by Allegro, waiting %ds", retry_after)
                    time.sleep(retry_after)
                    continue

                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning(
                        "Allegro %d on %s (attempt %d/%d), retrying in %ds",
                        resp.status_code, url, attempt + 1, max_attempts, wait,
                    )
                    time.sleep(wait)
                    last_exc = httpx.HTTPStatusError(
                        f"Server error {resp.status_code}", request=resp.request, response=resp
                    )
                    continue

                resp.raise_for_status()
                return resp

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                wait = 2 ** attempt
                logger.warning(
                    "Network error on %s (attempt %d/%d): %s — retrying in %ds",
                    url, attempt + 1, max_attempts, exc, wait,
                )
                last_exc = exc
                time.sleep(wait)

        raise last_exc

    # ── DB helpers ─────────────────────────────────────────────────────────

    def _get_account(self, account_id: int) -> Account:
        account = self.db.get(Account, account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        return account

    def _save_tokens(self, account: Account, token_data: dict, commit: bool = True) -> Account:
        account.access_token = token_data["access_token"]
        if "refresh_token" in token_data:
            account.refresh_token = token_data["refresh_token"]
        expires_in = token_data.get("expires_in", 43200)
        account.token_expires_at = _now() + timedelta(seconds=expires_in)
        if commit:
            self.db.commit()
            self.db.refresh(account)
        else:
            self.db.flush()
        return account

    def _client_credentials(self, account: Account | None = None) -> tuple[str, str]:
        if settings.ALLEGRO_CLIENT_ID and settings.ALLEGRO_CLIENT_SECRET:
            return settings.ALLEGRO_CLIENT_ID, settings.ALLEGRO_CLIENT_SECRET
        if account and account.allegro_client_id and account.allegro_client_secret:
            return account.allegro_client_id, account.allegro_client_secret
        raise ValueError("Allegro OAuth credentials are not configured")

    def _headers(self, account: Account, accept: str = "application/vnd.allegro.public.v1+json") -> dict:
        return {
            "Authorization": f"Bearer {account.access_token}",
            "Accept": accept,
            "User-Agent": allegro_user_agent(),
        }


def _normalize_scopes(scopes: str | None) -> str:
    return " ".join(part for part in re.split(r"[\s,]+", scopes or "") if part)


def _extract_billing_shipping_flags(entry: dict) -> tuple[bool | None, bool | None]:
    fee_smart: bool | None = None
    order_smart: bool | None = None

    additional_info = entry.get("additionalInfo") or []
    if not isinstance(additional_info, list):
        return fee_smart, order_smart

    for item in additional_info:
        if not isinstance(item, dict):
            continue
        flag_type = item.get("type")
        value = _parse_polish_bool(item.get("value"))
        if value is None:
            continue
        if flag_type == "IS_FEE_SMART":
            fee_smart = value
        elif flag_type == "IS_ORDER_SMART":
            order_smart = value

    return fee_smart, order_smart


def _extract_ads_service_date(entry: dict) -> date | None:
    type_id = (entry.get("type") or {}).get("id")
    if type_id != "NSP":
        return None

    additional_info = entry.get("additionalInfo") or []
    if not isinstance(additional_info, list):
        return None

    for item in additional_info:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "feeDate":
            continue
        return _parse_polish_date(item.get("value"))
    return None


def _parse_iso(value: str) -> datetime:
    """Parse ISO-8601 string to naive UTC datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # fallback: strip timezone offset
    return datetime.fromisoformat(value[:19])


def _account_name_from_profile(profile: dict) -> str:
    login = str(profile.get("login") or "").strip()
    if login:
        return login[:255]
    company = profile.get("company") or {}
    company_name = str(company.get("name") or "").strip()
    if company_name:
        return company_name[:255]
    email = str(profile.get("email") or "").strip()
    if email:
        return email[:255]
    return f"Allegro {profile.get('id')}"[:255]


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if parsed < 0 or parsed > 25:
        return None
    return parsed


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_polish_bool(value: object) -> bool | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"tak", "true", "1", "yes"}:
        return True
    if normalized in {"nie", "false", "0", "no"}:
        return False
    return None


def _parse_polish_date(value: object) -> date | None:
    raw = str(value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _extract_vat_rate(offer: dict) -> Decimal | None:
    tax_settings = offer.get("taxSettings") or {}
    rates = tax_settings.get("rates") or []
    if isinstance(rates, list):
        fallback = None
        for rate in rates:
            if not isinstance(rate, dict):
                continue
            value = _decimal_or_none(rate.get("rate"))
            if value is None:
                continue
            fallback = fallback if fallback is not None else value
            if rate.get("countryCode") == "PL":
                return value
        if fallback is not None:
            return fallback

    tax = offer.get("tax") or {}
    if isinstance(tax, dict):
        return _decimal_or_none(tax.get("rate") or tax.get("percentage"))
    return None


def _extract_ean_from_product_set(offer: dict) -> str | None:
    """Return the first EAN/GTIN from Allegro product-offer parameters."""
    product_set = offer.get("productSet") or []
    if not isinstance(product_set, list):
        return None

    for item in product_set:
        if not isinstance(item, dict):
            continue
        product = item.get("product") or {}
        if not isinstance(product, dict):
            continue
        parameters = product.get("parameters") or []
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            parameter_id = str(parameter.get("id") or "")
            parameter_name = str(parameter.get("name") or "").upper()
            options = parameter.get("options") or {}
            is_gtin = isinstance(options, dict) and options.get("isGTIN") is True
            if parameter_id != "225693" and "EAN" not in parameter_name and not is_gtin:
                continue
            values = parameter.get("values") or parameter.get("valuesLabels") or []
            if not isinstance(values, list):
                values = [values]
            for value in values:
                normalized = re.sub(r"\s+", "", str(value or ""))
                if normalized:
                    return normalized[:64]
    return None
