import logging
import signal
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import SessionLocal
from app.models.account import Account
from app.models.billing_profile import TenantBillingProfile, TenantSubscription, TenantUsageNotice
from app.models.raw_data import CustomerReturnRaw, PaymentRefundRaw
from app.models.tenant import Tenant
from app.models.user import User
from app.services.billing_state import has_paid_plan_acceptance, imports_allowed, trial_ends_at
from app.services.email import (send_trial_ended_paid_plan_email, send_usage_over_limit_email,
                                send_upgrade_suggestion_email, send_renewal_reminder_email,
                                send_subscription_expired_email)
from app.services.pricing import PRICING_TIERS
from app.services.usage import usage_state
from app.core.config import is_selfhosted, settings

logger = logging.getLogger("apos.scheduler")


def _sync_connected_accounts(default_days: int, force_days: int | None = None, job_name: str = "sync") -> None:
    logger.info("Scheduler: %s starting at %s", job_name, datetime.now(timezone.utc).isoformat())
    from app.services.import_service import ImportService

    with SessionLocal() as db:
        accounts = db.query(Account).filter(Account.access_token.isnot(None)).all()
        logger.info("Scheduler: %s connected account(s)=%d", job_name, len(accounts))
        for account in accounts:
            try:
                tenant = db.get(Tenant, account.tenant_id)
                if not tenant or not imports_allowed(db, tenant):
                    logger.info(
                        "Scheduler: %s account=%d skipped: trial ended and paid plan not accepted",
                        job_name,
                        account.id,
                    )
                    continue
                if force_days is not None:
                    days = force_days
                else:
                    has_returns_backfill = (
                        db.query(CustomerReturnRaw.customer_return_id)
                        .filter(CustomerReturnRaw.account_id == account.id)
                        .first()
                        is not None
                    )
                    has_refunds_backfill = (
                        db.query(PaymentRefundRaw.refund_id)
                        .filter(PaymentRefundRaw.account_id == account.id)
                        .first()
                        is not None
                    )
                    days = default_days if has_returns_backfill and has_refunds_backfill else 90
                result = ImportService(db).sync_account(account.id, days=days)
                logger.info(
                    "Scheduler: %s account=%d (%s) days=%d orders=%d billing=%d offers=%d",
                    job_name,
                    account.id,
                    account.name,
                    days,
                    result.orders_count,
                    result.billing_count,
                    result.offers_count,
                )
            except Exception as exc:
                logger.error("Scheduler: %s account=%d failed: %s", job_name, account.id, exc)


def hourly_sync_job() -> None:
    _sync_connected_accounts(default_days=2, job_name="hourly sync")


def daily_long_lookback_job() -> None:
    _sync_connected_accounts(default_days=2, force_days=90, job_name="daily long lookback")


def daily_trial_end_email_job() -> None:
    if is_selfhosted():
        logger.info("Skipping trial-end emails in selfhosted mode")
        return
    today = datetime.now(timezone.utc).date()
    with SessionLocal() as db:
        # Only legacy tenants have a trial; pool_v2 tenants get usage reminders instead.
        tenants = db.query(Tenant).filter(Tenant.is_active.is_(True), Tenant.billing_scheme == "legacy_trial").all()
        for tenant in tenants:
            if today < trial_ends_at(tenant, today) or has_paid_plan_acceptance(db, tenant.id):
                continue
            profile = (
                db.query(TenantBillingProfile)
                .filter(TenantBillingProfile.tenant_id == tenant.id)
                .first()
            )
            if profile and profile.trial_end_email_sent_at:
                continue
            user = (
                db.query(User)
                .filter(User.tenant_id == tenant.id, User.is_active.is_(True))
                .order_by(User.id.asc())
                .first()
            )
            if not user:
                continue
            if profile is None:
                profile = TenantBillingProfile(tenant_id=tenant.id)
                db.add(profile)
                db.flush()
            sent = send_trial_ended_paid_plan_email(
                to_email=user.email,
                tenant_name=tenant.name,
                trial_ends_at=datetime.combine(trial_ends_at(tenant, today), datetime.min.time()),
                subscription_url=f"{settings.APP_BASE_URL.rstrip('/')}/subscription",
                terms_url=f"{settings.APP_BASE_URL.rstrip('/')}/terms",
            )
            if sent:
                profile.trial_end_email_sent_at = datetime.utcnow()
                db.commit()


def daily_usage_notice_job() -> None:
    if is_selfhosted():
        return
    today = datetime.now(timezone.utc).date()
    url = f"{settings.APP_BASE_URL.rstrip('/')}/subscription"
    with SessionLocal() as db:
        tenant_ids = [row[0] for row in db.query(Tenant.id).filter(
            Tenant.is_active.is_(True), Tenant.billing_scheme == "pool_v2").all()]
        for tenant_id in tenant_ids:
            try:
                tenant = db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().first()
                if not tenant or not tenant.is_active or tenant.billing_scheme != "pool_v2":
                    db.rollback()
                    continue
                subscriptions = db.query(TenantSubscription).filter(
                    TenantSubscription.tenant_id == tenant_id,
                    TenantSubscription.status.in_(("active", "expired")),
                    TenantSubscription.period_end.isnot(None),
                ).all()
                for sub in subscriptions:
                    if sub.status == "active" and sub.period_end < today:
                        sub.status = "expired"
                db.flush()
                # Persist expiration even when no recipient exists or email delivery fails.
                db.commit()
                tenant = db.query(Tenant).filter(Tenant.id == tenant_id).with_for_update().one()
                state = usage_state(db, tenant, today)
                user = db.query(User).filter(User.tenant_id == tenant_id, User.is_active.is_(True)).order_by(User.id.asc()).first()
                if not user:
                    db.rollback()
                    continue

                def send_once(kinds, period, sender, **kwargs):
                    existing = {row[0] for row in db.query(TenantUsageNotice.kind).filter(
                        TenantUsageNotice.tenant_id == tenant_id, TenantUsageNotice.kind.in_(kinds),
                        TenantUsageNotice.period_key == period).all()}
                    if existing:
                        if len(kinds) == 2 and existing == {'upgrade_suggestion'}:
                            db.add(TenantUsageNotice(tenant_id=tenant_id, kind='over_limit', period_key=period))
                            db.flush()
                        return
                    if not sender(to_email=user.email, tenant_name=tenant.name, subscription_url=url, **kwargs):
                        return
                    db.add_all([TenantUsageNotice(tenant_id=tenant_id, kind=kind, period_key=period) for kind in kinds])
                    db.commit()
                    # Reacquire the tenant lock after each successful delivery.
                    db.query(Tenant.id).filter(Tenant.id == tenant_id).with_for_update().one()

                if not state['pool_active']:
                    if state['upgrade_suggested']:
                        tier = next((t for t in PRICING_TIERS if t.code == state['suggested_tier_code']), None)
                        if tier:
                            kinds = ['upgrade_suggestion', 'over_limit'] if state['over_limit'] else ['upgrade_suggestion']
                            send_once(kinds, state['month'], send_upgrade_suggestion_email, tier=tier,
                                      month_orders=state['month_orders'], monthly_limit=state['monthly_limit'])
                    elif state['over_limit']:
                        tier = next((t for t in PRICING_TIERS if t.billing_period == 'year' and
                                     (t.max_orders is None or state['month_orders'] <= t.max_orders)), None)
                        already_suggested = db.query(TenantUsageNotice.id).filter_by(
                            tenant_id=tenant_id, kind='upgrade_suggestion', period_key=state['month']).first()
                        if tier and not already_suggested:
                            send_once(['over_limit'], state['month'], send_usage_over_limit_email, tier=tier,
                                      month_orders=state['month_orders'], monthly_limit=state['monthly_limit'])
                for sub in subscriptions:
                    tier = next((t for t in PRICING_TIERS if t.code == sub.tier_code), None)
                    label = tier.label.lower() if tier else sub.tier_code
                    # No expiry mail after an upgrade (another plan active) or for old history.
                    if (sub.status == 'expired' and sub.period_end < today and not state['active_subscription']
                            and (today - sub.period_end).days <= 7):
                        send_once(['expired'], sub.period_end.isoformat(), send_subscription_expired_email,
                                  period_end=sub.period_end, tier_label=label)
                    elif (sub.status == 'active' and sub.period_start and sub.period_start <= today
                          and not any(o.status == 'active' and o.period_start and o.period_start > sub.period_end
                                      for o in subscriptions)):
                        days = (sub.period_end - today).days
                        kind = 'renewal_7d' if 0 <= days <= 7 else 'renewal_30d' if 7 < days <= 30 else None
                        if kind:
                            send_once([kind], sub.period_end.isoformat(), send_renewal_reminder_email,
                                      period_end=sub.period_end, tier_label=label)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Scheduler: usage notice failed for tenant=%s", tenant_id)


def run_scheduler() -> None:
    stop_event = threading.Event()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        hourly_sync_job,
        "interval",
        hours=1,
        id="hourly_sync",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        daily_long_lookback_job,
        CronTrigger(hour=2, minute=35, timezone="UTC"),
        id="daily_long_lookback",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        daily_trial_end_email_job,
        CronTrigger(hour=7, minute=15, timezone="UTC"),
        id="daily_trial_end_email",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        daily_usage_notice_job,
        CronTrigger(hour=7, minute=40, timezone="UTC"),
        id="daily_usage_notice",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )

    def handle_shutdown(signum, _frame) -> None:
        logger.info("Scheduler received signal %s", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    scheduler.start()
    logger.info("APScheduler started in dedicated process")
    try:
        stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
