import logging
import re

_AMOUNT_KEYS = re.compile(
    r"\b(total_cost|cost|sales_value|cpc|roas)\s*=\s*[-\d.,]+",
    re.IGNORECASE,
)


class AdsCostMaskingFilter(logging.Filter):
    """Maskuje kwoty z Allegro Ads w log records.

    Decyzja operatora: pytanie #3 audytu, opcja B — kwoty ad-spend
    nie powinny trafiać do logów (mogą być eksportowane do shared
    destinations). API i UI zostają bez zmian.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(("app.api.ads_import", "app.services.ads", "apos.ads_import")):
            try:
                msg = record.getMessage()
                if _AMOUNT_KEYS.search(msg):
                    record.msg = _AMOUNT_KEYS.sub(r"\1=<masked>", msg)
                    record.args = ()
            except Exception:
                pass
        return True


class TenantContextLogger(logging.Filter):
    """Attach tenant_id from request context to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        from app.core.tenant_context import current_tenant_id

        tenant_id = current_tenant_id.get(None)
        record.tenant_id = tenant_id if tenant_id is not None else "-"
        return True


def install_tenant_log_record_factory() -> None:
    old_factory = logging.getLogRecordFactory()
    if getattr(old_factory, "_apos_tenant_factory", False):
        return

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "tenant_id"):
            record.tenant_id = "-"
        return record

    record_factory._apos_tenant_factory = True
    logging.setLogRecordFactory(record_factory)
