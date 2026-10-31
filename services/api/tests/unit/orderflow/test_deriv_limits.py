"""E24-T01/T03 bounds asserted verbatim (`orderflow/deriv_limits.py`); a change edits this test."""

from __future__ import annotations

import pytest

from candleviewer.orderflow import deriv_limits as L
from candleviewer.orderflow import deriv_metrics as M
from candleviewer.orderflow import funding as F

DAY = L.US_PER_DAY


def test_deriv_limits_constants_verbatim() -> None:
    assert (L.MAX_WINDOW_DAYS_OI, L.MAX_WINDOW_DAYS_LIQ) == (400, 31)
    assert (L.MAX_LIMIT, L.DEFAULT_LIMIT) == (500, 100)
    assert (L.CURSOR_TTL_S, L.CURSOR_MAX_LEN) == (3600, 512)
    assert L.CLUSTER_WINDOW_MS_MAX_REST == 60_000
    assert DAY == 86_400_000_000


def test_deriv_limits_cursor_bounds_match_funding_cursor_codec() -> None:
    # The OI cursor reuses `orderflow.funding`'s codec, so its bounds must agree.
    assert (F.CURSOR_TTL_S, F.CURSOR_MAX_LEN) == (L.CURSOR_TTL_S, L.CURSOR_MAX_LEN)


def test_check_window_defaults_end_to_now_and_start_to_cap() -> None:
    assert L.check_window(None, None, now_us=100 * DAY, max_days=31) == (69 * DAY, 100 * DAY)
    assert L.check_window(DAY, 2 * DAY, now_us=0, max_days=31) == (DAY, 2 * DAY)


@pytest.mark.parametrize(("start", "end"), [(2 * DAY, DAY), (DAY, DAY), (0, 31 * DAY + 1)])
def test_check_window_inverted_empty_or_oversized_is_invalid_time_range(
    start: int, end: int
) -> None:
    with pytest.raises(L.DerivInvalidRequest) as info:
        L.check_window(start, end, now_us=0, max_days=31)
    assert info.value.code == "invalid_time_range"


@pytest.mark.parametrize("limit", [0, -1, 501])
def test_check_limit_outside_1_500_is_validation_failed(limit: int) -> None:
    with pytest.raises(L.DerivInvalidRequest) as info:
        L.check_limit(limit)
    assert info.value.code == "validation_failed"
    assert L.check_limit(500) == 500


def test_deriv_metrics_names_and_labels() -> None:
    assert M.deriv_oi_backfill_pages_total._labelnames == ("symbol", "interval", "result")
    assert M.deriv_oi_rows_written_total._labelnames == ("source",)
    assert M.deriv_liquidation_prints_total._labelnames == ("side",)
    assert M.deriv_sub_cap_rejected_total._name == "deriv_sub_cap_rejected"
