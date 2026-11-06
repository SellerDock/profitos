import logging
import signal
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import SessionLocal
from app.models.account import Account
from app.models.billing_profile import TenantBillingProfile
from app.models.raw_data import CustomerReturnRaw, PaymentRefundRaw
from app.models.tenant import Tenant
from app.models.user import User
from app.services.billing_state import has_paid_plan_acceptance, imports_allowed, trial_ends_at
from app.services.email import send_trial_ended_paid_plan_email
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
        tenants = db.query(Tenant).filter(Tenant.is_active.is_(True)).all()
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
    )
    scheduler.add_job(
        daily_trial_end_email_job,
        CronTrigger(hour=7, minute=15, timezone="UTC"),
        id="daily_trial_end_email",
        replace_existing=True,
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
