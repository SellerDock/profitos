import pytest
from fastapi import HTTPException

from app.api.dashboard import _COMPARISON_PERIODS, _VALID_PERIODS, _requested_periods


def test_requested_dashboard_periods_returns_ordered_deduplicated_subset():
    assert _requested_periods("current_month,today,current_month", _VALID_PERIODS, "dashboard") == (
        "current_month",
        "today",
    )


def test_requested_comparison_periods_rejects_unknown_key():
    with pytest.raises(HTTPException) as exc_info:
        _requested_periods("today,not-a-period", _COMPARISON_PERIODS, "comparison")

    assert exc_info.value.status_code == 422
