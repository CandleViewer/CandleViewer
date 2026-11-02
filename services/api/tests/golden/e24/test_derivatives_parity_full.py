"""E24-T06 full run: every manifest case over the whole corpus window (450 1 m bars), engine
against the DuckDB reference, incremental against full. `harness`: deselected from the PR lane
(addopts); run with `-m harness`. The scheduled workflow is a separate follow-up PR.
`CV_PARITY_SUMMARY=<path>` writes the per-case divergence counts (the nightly artifact)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden.e24 import _loader as L
from tests.golden.e24 import _parity as P
from tests.golden.e24 import _reference as R

pytestmark = pytest.mark.harness

ALL = [c.id for c in L.cases()]


def test_full_window_parity_over_every_case(tmp_path: Path) -> None:
    reports: dict[str, P.Report] = {}
    for case_id in ALL:
        rows = L.build_rows(L.case_by_id(case_id))
        ref = R.run(rows, tmp_path / case_id)
        full = P.run_full(rows)
        reports[case_id] = P.compare(full, ref)
        assert P.run_incremental(rows) == full, f"{case_id}: incremental differs from full"
    P.write_summary(reports)
    for case_id, report in reports.items():
        assert report.bars > 0, case_id
        P.assert_parity(report)


def test_full_window_is_the_whole_kline_corpus() -> None:
    assert L.case_by_id("btc_8h_full").bar_count == 450
    assert len(L.build_rows(L.case_by_id("btc_8h_full")).bars) == 450


def test_five_minute_grid_classifies_every_bar(tmp_path: Path) -> None:
    """The 5 min bars start at :13, three minutes off the OI samples, so each holds one sample."""
    rows = L.build_rows(L.case_by_id("btc_8h_5m_full"))
    report = P.compare(P.run_full(rows), R.run(rows, tmp_path))
    assert report.clean
    assert report.non_none["oi_price_quadrant"] > 0
