import logging

from app.core.log_filters import AdsCostMaskingFilter


def test_ads_cost_masked_in_logs(caplog):
    logger = logging.getLogger("app.api.ads_import.test")
    masking_filter = AdsCostMaskingFilter()
    logger.addFilter(masking_filter)
    try:
        with caplog.at_level(logging.INFO, logger="app.api.ads_import.test"):
            logger.info("imported batch total_cost=12345.67 rows=10")
    finally:
        logger.removeFilter(masking_filter)

    assert "total_cost=<masked>" in caplog.text
    assert "12345.67" not in caplog.text
