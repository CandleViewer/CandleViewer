"""E21-T04 PR 2 (#710): the `liquidity_*` settings (defaults, bounds, the pin cap refused at load,
never truncated), the wiring of `ws_wiring.liquidity_engine` from them, and the metrics: each name
registered in the catalogue as exported, labels bounded by `symbol_label`."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.orderflow import heatmap_metrics as hm
from candleviewer.orderflow import liquidity_metrics as lm
from candleviewer.orderflow.funding_metrics import OTHER_SYMBOL, symbol_label
from candleviewer.orderflow.liquidity_engine import PIN_DEPTH
from candleviewer.settings import Settings
from candleviewer.ws_wiring import liquidity_engine


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]  # pydantic-settings kwarg


def test_liquidity_settings_default_to_the_documented_values() -> None:
    s = _settings()
    assert s.liquidity_bands_ticks == (5, 10, 25, 50, 100)
    assert (s.liquidity_reload_consume_pct, s.liquidity_reload_replenish_pct) == (
        Decimal("0.5"), Decimal("0.9"),
    )  # fmt: skip
    assert (s.liquidity_reload_window_ms, s.liquidity_min_size) == (5_000, None)
    assert (s.liquidity_pinned_symbols, s.liquidity_pin_max) == ((), 8)


def test_pins_within_the_cap_load() -> None:
    s = _settings(liquidity_pinned_symbols=("BTCUSDT", "ETHUSDT"), liquidity_pin_max=2)
    assert s.liquidity_pinned_symbols == ("BTCUSDT", "ETHUSDT")


def test_pins_over_the_cap_are_a_config_error_never_a_truncation() -> None:
    with pytest.raises(ValidationError, match="CV_LIQUIDITY_PIN_MAX is 1"):
        _settings(liquidity_pinned_symbols=("BTCUSDT", "ETHUSDT"), liquidity_pin_max=1)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("liquidity_pinned_symbols", ("BTCUSDT", "BTCUSDT")),
        ("liquidity_pinned_symbols", ("btc.usdt",)),
        ("liquidity_pin_max", 0),
        ("liquidity_pin_max", 33),
        ("liquidity_bands_ticks", ()),
        ("liquidity_bands_ticks", (10, 5)),
        ("liquidity_bands_ticks", (0, 5)),
        ("liquidity_reload_consume_pct", Decimal(0)),
        ("liquidity_reload_replenish_pct", Decimal("1.1")),
        ("liquidity_reload_window_ms", 60_001),
        ("liquidity_min_size", Decimal(-1)),
    ],
)
def test_liquidity_settings_out_of_bounds_are_refused(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _settings(**{name: value})


class _Pins:
    def __init__(self) -> None:
        self.pinned: dict[str, int] = {}

    def set_sampler(self, sampler: object) -> None:
        self.sampler = sampler

    def pin_native(self, symbol: str, depth: int) -> None:
        self.pinned[symbol] = depth

    def unpin_native(self, symbol: str) -> None:
        self.pinned.pop(symbol, None)


async def test_ws_wiring_builds_the_engine_from_the_settings() -> None:
    s = _settings(
        liquidity_pinned_symbols=("BTCUSDT",),
        liquidity_reload_window_ms=2_000,
        liquidity_min_size=Decimal("0.5"),
    )
    from candleviewer.bus import Bus

    ingestion = SimpleNamespace(books=None, instruments=None)
    ctx = SimpleNamespace(settings=s, bus=SimpleNamespace(bus=Bus()), ingestion=ingestion)
    pins = _Pins()
    engine = liquidity_engine(cast(Any, ctx), cast(Any, pins))
    assert engine._config.reload_window_ms == 2_000
    assert engine._config.min_size == Decimal("0.5")
    engine.start()
    assert pins.pinned == {"BTCUSDT": PIN_DEPTH}
    await engine.stop()
    assert pins.pinned == {}


def test_metrics_are_registered_exported_and_label_bounded() -> None:
    by_name = {spec.name: spec for spec in CATALOGUE}
    for name in (*lm.EXPORTED_NAMES, "heatmap_pinned_symbols"):
        assert by_name[name].exported, name
        assert by_name[name].status == "live", name
    assert by_name["liquidity_events_overflow_total"].labels == ("symbol", "reason")
    assert by_name["liquidity_band_compute_ms"].kind == "histogram"
    assert "heatmap_pinned_symbols" in hm.EXPORTED_NAMES
    # `symbol` is bounded: a malformed one, and every one past the cap, shares `other`.
    assert symbol_label("not a symbol") == OTHER_SYMBOL
    assert lm.symbol_label is symbol_label
