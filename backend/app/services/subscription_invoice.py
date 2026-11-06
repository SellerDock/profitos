from datetime import date, timedelta

from app.core.config import settings
from app.models.billing_profile import TenantBillingProfile, TenantSubscription
from app.services.pricing import PRICING_TIERS


def build_subscription_invoice_payload(sub: TenantSubscription, profile: TenantBillingProfile, today: date) -> dict:
    tier = next(tier for tier in PRICING_TIERS if tier.code == sub.tier_code)
    return {
        'Zaplacono': 0, 'ZaplaconoNaDokumencie': 0, 'LiczOd': 'NET',
        'DataWystawienia': today.isoformat(), 'DataSprzedazy': today.isoformat(),
        'FormatDatySprzedazy': 'DZN', 'SposobZaplaty': 'PRZ',
        'TerminPlatnosci': (today + timedelta(days=7)).isoformat(), 'RodzajPodpisuOdbiorcy': 'BWO',
        'Kontrahent': {
            'Nazwa': profile.company_name, 'NIP': ''.join(c for c in profile.nip if c.isdigit()),
            'Ulica': profile.street, 'KodPocztowy': profile.postal_code, 'KodKraju': 'PL',
            'Kraj': 'Polska', 'Miejscowosc': profile.city, 'Email': profile.invoice_email,
            'OsobaFizyczna': False,
        },
        'Pozycje': [{
            'StawkaVat': 0.23, 'Ilosc': 1, 'CenaJednostkowa': float(sub.price_pln),
            'NazwaPelna': f'{settings.BRAND_PRODUCT_NAME} – pakiet roczny {tier.label.lower()} miesięcznie, 12 miesięcy',
            'Jednostka': 'usł.', 'TypStawkiVat': 'PRC', 'GTU': 'BRAK', 'Zal15': False,
        }],
    }
