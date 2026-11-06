from __future__ import annotations

import logging
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings
from app.models.user import WaitlistEntry

logger = logging.getLogger("apos.email")


def _plain_activation_body(*, activation_url: str, tenant_name: str, expires_at: datetime) -> str:
    expires = expires_at.strftime("%d.%m.%Y, %H:%M")
    return (
        "Dzień dobry,\n\n"
        f"utworzyliśmy dostęp do {settings.BRAND_PRODUCT_NAME} dla: {tenant_name}.\n\n"
        "Kliknij poniższy link, ustaw hasło i dokończ aktywację konta:\n"
        f"{activation_url}\n\n"
        f"Link jest ważny do {expires}.\n\n"
        f"Jeśli nie czekasz na dostęp do {settings.BRAND_PRODUCT_NAME}, zignoruj tę wiadomość.\n\n"
        "Pozdrawiamy,\n"
        f"{settings.BRAND_PRODUCT_NAME}"
    )


def send_activation_email(
    *,
    to_email: str,
    activation_url: str,
    tenant_name: str,
    expires_at: datetime,
) -> bool:
    subject = f"Twój dostęp do {settings.BRAND_PRODUCT_NAME}"
    body = _plain_activation_body(
        activation_url=activation_url,
        tenant_name=tenant_name,
        expires_at=expires_at,
    )
    sent = _send_plain_email(to_email=to_email, subject=subject, body=body)
    if sent:
        logger.info("activation email sent to=%s tenant=%s", to_email, tenant_name)
    return sent


def _send_plain_email(*, to_email: str, subject: str, body: str) -> bool:
    if not settings.smtp_enabled:
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.smtp_from_name or settings.BRAND_PRODUCT_NAME, settings.smtp_from_email or ""))
    msg["To"] = to_email
    msg.set_content(body)

    return _send_email_message(msg)


def _send_email_message(msg: EmailMessage) -> bool:
    if not settings.smtp_enabled:
        return False

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.ehlo()
        if settings.smtp_starttls:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)

    return True


def send_support_report_email(
    *,
    from_user_email: str,
    tenant_id: int,
    message: str,
    attachment_filename: str | None = None,
    attachment_content_type: str | None = None,
    attachment_bytes: bytes | None = None,
) -> bool:
    if not settings.waitlist_admin_email:
        return False

    body = (
        f"Nowe zgłoszenie z panelu {settings.BRAND_PRODUCT_NAME}.\n\n"
        f"Użytkownik: {from_user_email}\n"
        f"Tenant ID: {tenant_id}\n"
        f"Załącznik: {attachment_filename or '-'}\n\n"
        "Treść zgłoszenia:\n"
        f"{message}\n"
    )
    msg = EmailMessage()
    msg["Subject"] = f"Zgłoszenie {settings.BRAND_PRODUCT_NAME}: {from_user_email}"
    msg["From"] = formataddr((settings.smtp_from_name or settings.BRAND_PRODUCT_NAME, settings.smtp_from_email or ""))
    msg["To"] = settings.waitlist_admin_email
    msg["Reply-To"] = from_user_email
    msg.set_content(body)

    if attachment_filename and attachment_bytes is not None:
        content_type = attachment_content_type or "application/octet-stream"
        maintype, _, subtype = content_type.partition("/")
        if not maintype or not subtype:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(
            attachment_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=attachment_filename,
        )

    sent = _send_email_message(msg)
    if sent:
        logger.info("support report sent from=%s tenant=%s to=%s", from_user_email, tenant_id, settings.waitlist_admin_email)
    return sent


def send_waitlist_admin_notification_email(*, entry: WaitlistEntry) -> bool:
    if not settings.waitlist_admin_email:
        return False

    body = (
        f"Nowa rejestracja {settings.BRAND_PRODUCT_NAME}.\n\n"
        f"Email: {entry.email}\n"
        f"Firma: {entry.company or '-'}\n"
        f"Miesięczne zamówienia: {entry.monthly_orders or '-'}\n"
        f"Wiadomość: {entry.message or '-'}\n"
    )
    sent = _send_plain_email(
        to_email=settings.waitlist_admin_email,
        subject=f"Nowa rejestracja {settings.BRAND_PRODUCT_NAME}: {entry.email}",
        body=body,
    )
    if sent:
        logger.info("waitlist admin notification sent entry_email=%s to=%s", entry.email, settings.waitlist_admin_email)
    return sent


def send_trial_ended_paid_plan_email(
    *,
    to_email: str,
    tenant_name: str,
    trial_ends_at: datetime,
    subscription_url: str,
    terms_url: str,
) -> bool:
    body = (
        "Dzień dobry,\n\n"
        f"okres próbny {settings.BRAND_PRODUCT_NAME} dla konta {tenant_name} zakończył się "
        f"{trial_ends_at.strftime('%d.%m.%Y')}.\n\n"
        "Jeśli chcesz dalej automatycznie pobierać zamówienia i korzystać z panelu, "
        "przejdź do rozliczeń, zaakceptuj regulamin i kliknij „Przechodzę na pakiet płatny”.\n\n"
        f"Rozliczenia: {subscription_url}\n"
        f"Regulamin: {terms_url}\n\n"
        "Opłata zostanie naliczona dopiero po zakończeniu triala, według liczby zamówień "
        "i cennika widocznego w panelu. Faktury wystawiamy za okresy miesięczne.\n\n"
        "Jeśli nie chcesz kontynuować, nie musisz nic robić – nowe synchronizacje Allegro "
        "zostaną wstrzymane po trialu.\n\n"
        "Pozdrawiamy,\n"
        f"{settings.BRAND_PRODUCT_NAME}"
    )
    sent = _send_plain_email(
        to_email=to_email,
        subject=f"{settings.BRAND_PRODUCT_NAME}: zakończył się okres próbny",
        body=body,
    )
    if sent:
        logger.info("trial ended paid plan email sent to=%s tenant=%s", to_email, tenant_name)
    return sent


def _tier_offer(tier) -> str:
    if tier.is_custom:
        return f"{tier.label} – cena ustalana indywidualnie"
    return f"{tier.label} – {tier.price_pln} zł netto rocznie"


def send_usage_over_limit_email(*, to_email: str, tenant_name: str, subscription_url: str,
                                month_orders: int, monthly_limit: int, tier) -> bool:
    return _send_plain_email(
        to_email=to_email, subject=f"{settings.BRAND_PRODUCT_NAME}: przekroczony limit zamówień",
        body=(f"Dzień dobry,\n\nkonto {tenant_name} ma w tym miesiącu {month_orders} zamówień "
              f"przy limicie {monthly_limit}. Panel i import działają dalej bez przerwy.\n\n"
              f"Sprawdź pasujący pakiet: {_tier_offer(tier)}.\n{subscription_url}\n\n"
              f"Pozdrawiamy,\n{settings.BRAND_PRODUCT_NAME}"),
    )


def send_upgrade_suggestion_email(*, to_email: str, tenant_name: str, subscription_url: str,
                                  month_orders: int, monthly_limit: int, tier) -> bool:
    return _send_plain_email(
        to_email=to_email, subject=f"{settings.BRAND_PRODUCT_NAME}: propozycja zmiany pakietu",
        body=(f"Dzień dobry,\n\nkonto {tenant_name} regularnie przekracza limit {monthly_limit} zamówień. "
              f"W tym miesiącu liczba zamówień wynosi {month_orders}. "
              "Panel i import działają dalej bez przerwy.\n\n"
              f"Sprawdź proponowany pakiet: {_tier_offer(tier)}.\n{subscription_url}\n\n"
              f"Pozdrawiamy,\n{settings.BRAND_PRODUCT_NAME}"),
    )


def send_renewal_reminder_email(*, to_email: str, tenant_name: str, subscription_url: str,
                                period_end: date, tier_label: str) -> bool:
    return _send_plain_email(
        to_email=to_email, subject=f"{settings.BRAND_PRODUCT_NAME}: przypomnienie o odnowieniu pakietu",
        body=(f"Dzień dobry,\n\npakiet {tier_label} dla konta {tenant_name} kończy się "
              f"{period_end.strftime('%d.%m.%Y')}. Po wygaśnięciu konto przejdzie na darmowe "
              f"200 zamówień miesięcznie.\n\nOdnowienie pakietu: {subscription_url}\n\n"
              f"Pozdrawiamy,\n{settings.BRAND_PRODUCT_NAME}"),
    )


def send_subscription_expired_email(*, to_email: str, tenant_name: str, subscription_url: str,
                                    period_end: date, tier_label: str) -> bool:
    return _send_plain_email(
        to_email=to_email, subject=f"{settings.BRAND_PRODUCT_NAME}: pakiet wygasł",
        body=(f"Dzień dobry,\n\npakiet {tier_label} dla konta {tenant_name} wygasł "
              f"{period_end.strftime('%d.%m.%Y')}. Konto przechodzi na darmowe "
              f"200 zamówień miesięcznie.\n\nWybierz pakiet: {subscription_url}\n\n"
              f"Pozdrawiamy,\n{settings.BRAND_PRODUCT_NAME}"),
    )


def send_subscription_request_admin_email(*, subscription, profile) -> bool:
    if not settings.waitlist_admin_email:
        return False
    return _send_plain_email(
        to_email=settings.waitlist_admin_email,
        subject=f'Nowe zamówienie pakietu {settings.BRAND_PRODUCT_NAME}',
        body=(f'Firma: {profile.company_name}\nNIP: {profile.nip}\n'
              f'Pakiet: {subscription.tier_code}\nCena netto: {subscription.price_pln} zł\n'
              f'ID zamówienia: {subscription.id}\n'),
    )
