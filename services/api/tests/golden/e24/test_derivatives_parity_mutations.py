"""E24-T06 mutation tests (AC2, BQ-10): each perturbs the engine side only and asserts the harness
fails loudly with an actionable `ParityDivergence` (metric, first bar, both values). Ordinary
passing tests, not xfail. Constants are monkeypatched locally; no engine edit."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.orderflow import derivatives
from tests.golden.e24 import _parity as P
from tests.golden.e24 import _reference as R
from tests.golden.e24.conftest import RefOf


def _assert_names(exc: P.ParityDivergence, label: str) -> None:
    text = str(exc)
    assert text.startswith(label) or label in text
    assert re.search(r"at bar \d{13} \(\d{4}-\d\d-\d\dT", text), text
    assert "engine=" in text
    assert "reference=" in text


def _rekey(ref: R.Ref, by_ms: int) -> R.Ref:
    """The reference rows under the shifted grid's keys: same values, same position."""
    return {s + by_ms: v for s, v in ref.items()}


@pytest.mark.parametrize("shift_ms", [60_000, 1])
def test_shifted_bar_boundary_is_caught(shift_ms: int, ref_of: RefOf) -> None:
    """The engine buckets onto a grid shifted by one bar / 1 ms; the reference is unshifted."""
    rows, ref = ref_of("btc_8h_slice")
    report = P.compare(P.run_full(P.shift_bars(rows, shift_ms)), _rekey(ref, shift_ms))
    assert not report.clean
    with pytest.raises(P.ParityDivergence) as caught:
        P.assert_parity(report)
    _assert_names(caught.value, min(report.first.values(), key=lambda d: d.start_ms).label)


def test_carried_forward_oi_past_the_staleness_bound_is_caught(
    monkeypatch: pytest.MonkeyPatch, ref_of: RefOf
) -> None:
    rows, ref = ref_of("btc_8h_15m_stale_open")
    P.assert_parity(P.compare(P.run_full(rows), ref))  # the unperturbed engine is clean
    monkeypatch.setattr(derivatives, "OI_STALENESS_MS", 10**12)
    report = P.compare(P.run_full(rows), ref)
    with pytest.raises(P.ParityDivergence) as caught:
        P.assert_parity(report)
    _assert_names(caught.value, "open_interest_delta")
    assert report.counts["open_interest_delta"] > 0
    assert report.first["open_interest_delta"].reference is None  # the reference never carries


def test_eight_hour_assumption_on_a_four_hour_symbol_is_caught(ref_of: RefOf) -> None:
    rows, ref = ref_of("btc_4h_paired")
    P.assert_parity(P.compare(P.run_full(rows), ref))
    report = P.compare(P.run_full(rows, interval_min=480), ref)
    with pytest.raises(P.ParityDivergence) as caught:
        P.assert_parity(report)
    _assert_names(caught.value, "funding_annualized")
    first = report.first["funding_annualized"]
    assert isinstance(first.engine, Decimal)
    assert first.engine * 2 == first.reference  # 1095 against 2190: exactly half


def test_a_series_within_its_declared_tolerance_is_not_a_divergence() -> None:
    assert P._equal("premium_pct[last]", Decimal("1.0000000000005"), Decimal("1.0"))
    assert not P._equal("premium_pct[last]", Decimal("1.000000000002"), Decimal("1.0"))
    assert not P._equal("basis[last]", Decimal("1.0000000000005"), Decimal("1.0"))  # exact
    assert not P._equal("open_interest", None, Decimal("0"))  # None is never zero


def test_grid_mismatch_is_a_divergence_not_a_pass(ref_of: RefOf) -> None:
    rows, ref = ref_of("btc_8h_slice")
    with pytest.raises(P.ParityDivergence, match="bar grids differ"):
        P.compare(P.run_full(rows)[:-1], ref)


def test_the_divergence_summary_artifact_carries_per_series_counts(
    monkeypatch: pytest.MonkeyPatch, ref_of: RefOf, tmp_path: Path
) -> None:
    rows, ref = ref_of("btc_4h_paired")
    report = P.compare(P.run_full(rows, interval_min=480), ref)
    dest = tmp_path / "summary.json"
    monkeypatch.setenv("CV_PARITY_SUMMARY", str(dest))
    P.write_summary({"btc_4h_paired": report})
    body = dest.read_text()
    assert '"funding_annualized"' in body
    assert report.counts["funding_annualized"] > 0
