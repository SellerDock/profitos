import logging

import pytest

from app.core.log_filters import install_tenant_log_record_factory


@pytest.mark.contract
def test_tenant_log_record_factory_sets_default_tenant_id():
    install_tenant_log_record_factory()

    record = logging.getLogger("test.tenant").makeRecord(
        "test.tenant",
        logging.INFO,
        __file__,
        1,
        "hello",
        (),
        None,
    )

    assert record.tenant_id == "-"
