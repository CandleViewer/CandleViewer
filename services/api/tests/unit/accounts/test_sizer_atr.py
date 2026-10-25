"""E28-T03 (#907): the TB-8 consumer tests (E28 threat model Sec.5, F-11; E13 model Sec.12). The
sizer sizes an `atr` stop from the kernel's ATR only (SR-E28-11), falls back to the profile's
`fallback_sl_offset_pct` with `stop_fallback` when no warm kernel reading serves (SR-E28-12), and
records the reading's provenance in the explanation (SR-E28-13)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

import pytest
from pydantic import ValidationError

from candleviewer.accounts import sizer as sz
from tests.unit.accounts.test_sizer import atr, profile, sized

D = Decimal
_KERNEL_STOP: Final = D("63400.0")  # 64000 - 400 x 1.5 (P-PCT's sl_atr_multiple)
_FALLBACK_STOP: Final = D("62720.0")  # 64000 x (1 - 0.02), P-PCT's fallback_sl_offset_pct


def _sized_with(reading: sz.AtrReading | None) -> sz.LegSizing:
    return sized(profile("P-PCT"), market=sz.SizingMarket(atr=reading))


@pytest.mark.parametrize("source", ["worker", "client", "preset", "cached"])
def test_atr_stop_offset_source_is_kernel(source: str) -> None:
    kernel = _sized_with(atr(D(400)))
    assert (kernel.outcome, kernel.stop, kernel.atr_source) == (
        "ok",
        sz.ResolvedStop(_KERNEL_STOP, D(600), fallback=False),
        "kernel",
    )
    # A non-kernel ATR, deliberately different, never moves the stop: no kernel reading served.
    other = _sized_with(atr(D(900), source=source))
    assert other.stop is not None and other.stop.price == _FALLBACK_STOP
    assert (other.outcome, other.stop_fallback, other.atr_source, other.atr) == (
        "ok",
        True,
        "fallback",
        None,
    )
    assert other.rules[0] == "stop_fallback"


@pytest.mark.parametrize(
    "reading",
    [
        None,
        *(
            atr(None, unavailable=r)
            for r in ("missing", "parity_flagged", "stale", "warmup", "nan")
        ),
    ],
    ids=["no-reading", "missing", "parity_flagged", "stale", "warmup", "nan"],
)
def test_atr_unavailable_fails_closed(reading: sz.AtrReading | None) -> None:
    got = _sized_with(reading)
    # The leg keeps a native stop at the server-side fallback, flagged; never an unprotected leg.
    assert got.stop is not None and got.stop.price == _FALLBACK_STOP
    assert (got.outcome, got.stop_fallback, got.atr_source, got.atr) == (
        "ok",
        True,
        "fallback",
        None,
    )


def test_atr_stop_records_kernel_provenance() -> None:
    reading = atr(D(400), version=3, build_version=7)
    got = _sized_with(reading)
    assert got.atr == reading
    assert got.atr is not None
    provenance = (got.atr.source, got.atr.version, got.atr.build_version, got.atr.period)
    assert provenance == ("kernel", 3, 7, 14)
    assert (got.atr.as_of, got.atr_source, got.atr_multiple) == (
        datetime(2026, 10, 5, tzinfo=UTC),
        "kernel",
        D("1.5"),
    )


def test_atr_provenance_is_not_recorded_for_a_ticks_stop() -> None:
    got = sized(profile("P-RISK"), market=sz.SizingMarket(atr=atr(D(400))))
    assert (got.atr, got.atr_source, got.atr_multiple) == (None, None, None)


def test_atr_take_profit_reads_the_kernel_only() -> None:
    p = profile("P-QTY", sl_offset_unit="ticks", sl_offset_value="600", tp_offset_unit="atr")
    got = sized(p, market=sz.SizingMarket(atr=atr(D(400), source="worker")))
    assert (got.atr, got.tps) == (None, ())


_FIELDS: Final = {
    "timeframe": "1h",
    "period": 14,
    "value": "400",
    "as_of": datetime(2026, 10, 5, tzinfo=UTC),
    "source": "kernel",
    "version": 1,
    "build_version": 1,
}


@pytest.mark.parametrize(
    "change",
    [
        {"source": None},  # missing provenance
        {"version": None},
        {"build_version": None},
        {"source": "server"},  # unknown source
        {"source": "Kernel"},
        {"version": 0},  # out of bounds
        {"build_version": 2**31},
        {"version": True},
        {"build_version": "1"},
        {"value": "NaN"},  # a NaN is a typed reason, never a number
        {"value": "Infinity"},
        {"value": None},  # no value and no reason
        {"unavailable": "warmup"},  # a value and a reason
        {"value": None, "unavailable": "late"},
        {"atr_value": "900"},  # no extra or client hint
        {"sl_atr_multiple": "3"},
    ],
)
def test_atr_reading_refuses_missing_unknown_or_unbounded_provenance(change: Any) -> None:
    fields = {k: v for k, v in (_FIELDS | change).items() if v is not None or k == "value"}
    with pytest.raises(ValidationError):
        sz.AtrReading.model_validate(fields)


@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (sz.SizingMarket, {"atr_value": "400"}),
        (sz.SizingMarket, {"qty": "1"}),
        (sz.SizingIntent, {"symbol": "BTCUSDT", "side": "buy", "order_type": "market", "qty": "1"}),
    ],
)
def test_sizing_inputs_refuse_a_client_hint(model: Any, fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(fields)
