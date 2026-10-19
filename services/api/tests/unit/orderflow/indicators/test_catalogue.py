"""The v1 indicator catalogue (E13-T02, #426; ADR-0034; 24-internal-schemas §7.1).

Pins `compute` to the ADR-0034 assignment table and `category`/`pane` to the plan's table, checks
that every server definition says what its kernel computes, and covers the definition-time checks
that keep a bad descriptor from ever loading.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.orderflow.errors import DuplicateIndicatorError
from candleviewer.orderflow.indicators import KERNELS
from candleviewer.orderflow.indicators.catalogue import (
    DELTA,
    EMA,
    SERVER_DEFINITIONS,
    SMA,
    V1_INDICATORS,
    IndicatorCatalogue,
    IndicatorDef,
    OutputSpec,
    ParamSpec,
    default_catalogue,
)
from candleviewer.orderflow.indicators.kernels import AtrKernel
from candleviewer.orderflow.indicators.types import ParamValue

#: The assignment table of `docs/plan/spikes/e13-o4.md` §5 (ADR-0034 decision 1), verbatim and
#: in its order.
ADR_0034 = (
    ("sma", "server"), ("ema", "server"), ("wma", "client_worker"), ("vwma", "client_worker"),
    ("smma", "client_worker"), ("dema", "client_worker"), ("tema", "client_worker"),
    ("vwap", "server"), ("bollinger", "client_worker"), ("keltner", "client_worker"),
    ("donchian", "client_worker"), ("atr", "server"), ("adx", "server"), ("rsi", "server"),
    ("macd", "client_worker"), ("stochastic", "client_worker"), ("cci", "client_worker"),
    ("williams_r", "client_worker"), ("supertrend", "client_worker"), ("zigzag", "server"),
    ("ichimoku", "client_worker"), ("psar", "client_worker"), ("volume", "server"),
    ("volume_ma", "client_worker"), ("obv", "client_worker"), ("cmf", "client_worker"),
    ("mfi", "client_worker"), ("cvd", "server"),
)  # fmt: skip

#: The category and pane per indicator family (the #426 plan's table, section 3.2).
PLACEMENT = {
    **dict.fromkeys(("sma", "ema", "wma", "vwma", "smma", "dema", "tema"), ("trend", "price")),
    **dict.fromkeys(("rsi", "macd", "stochastic", "cci", "williams_r"), ("momentum", "sub")),
    **dict.fromkeys(("bollinger", "keltner", "donchian"), ("volatility", "price")),
    **dict.fromkeys(("atr", "adx"), ("volatility", "sub")),
    **dict.fromkeys(("supertrend", "zigzag", "ichimoku", "psar"), ("trend", "price")),
    **dict.fromkeys(("volume", "volume_ma"), ("volume", "both")),
    **dict.fromkeys(("obv", "cmf", "mfi"), ("volume", "sub")),
    "cvd": ("orderflow", "sub"),
    "vwap": ("volume", "price"),
}

#: Warmup at the defaults: the first value lands on this bar.
WARMUP = {
    "sma": 20, "ema": 21, "wma": 20, "vwma": 20, "smma": 20, "dema": 39, "tema": 58, "vwap": 1,
    "bollinger": 20, "keltner": 20, "donchian": 20, "atr": 14, "adx": 28, "rsi": 15, "macd": 26,
    "stochastic": 14, "cci": 20, "williams_r": 14, "supertrend": 10, "zigzag": 11,
    "ichimoku": 9, "psar": 2, "volume": 1, "volume_ma": 20, "obv": 1, "cmf": 20, "mfi": 15,
    "cvd": 1,
}  # fmt: skip


def test_catalogue_holds_the_28_v1_indicators_in_adr_0034_order() -> None:
    assert [d.id for d in default_catalogue()] == [name for name, _ in ADR_0034]


def test_catalogue_compute_is_pinned_to_the_adr_0034_table() -> None:
    assert [(d.id, d.compute) for d in V1_INDICATORS] == list(ADR_0034)
    assert sum(d.compute == "server" for d in V1_INDICATORS) == 9


def test_catalogue_category_and_pane_follow_the_plan_table() -> None:
    assert {d.id: (d.category, d.pane) for d in V1_INDICATORS} == PLACEMENT


def test_catalogue_server_set_is_exactly_the_kernel_set_plus_delta() -> None:
    assert set(SERVER_DEFINITIONS) == set(KERNELS)
    assert SERVER_DEFINITIONS["delta"] is DELTA and DELTA not in V1_INDICATORS
    for definition in V1_INDICATORS:
        assert (definition.id in KERNELS) == (definition.compute == "server"), definition.id


@pytest.mark.parametrize("definition", list(SERVER_DEFINITIONS.values()), ids=lambda d: d.id)
def test_catalogue_server_definition_says_what_its_kernel_computes(
    definition: IndicatorDef,
) -> None:
    kernel = KERNELS[definition.id]
    assert definition.kernel is kernel
    assert tuple(o.id for o in definition.outputs) == kernel.outputs
    assert tuple(p.name for p in definition.params) == kernel.param_names
    assert definition.nullable_when == kernel.nullable_when
    assert definition.warmup_bars() == kernel.warmup_bars(definition.defaults())
    kernel(definition.defaults(), source=kernel.sources[0])  # the defaults are in its domain


def test_catalogue_warmup_at_the_defaults_is_pinned() -> None:
    assert {d.id: d.warmup_bars() for d in V1_INDICATORS} == WARMUP


def test_catalogue_warmup_grows_with_the_period() -> None:
    by_id = {d.id: d for d in V1_INDICATORS}
    params: Mapping[str, Mapping[str, ParamValue]] = {
        "dema": {"n": 50},
        "tema": {"n": 50},
        "keltner": {"n": 20, "mult": Decimal(2), "atr_n": 60},
        "macd": {"fast": 40, "slow": 26, "signal": 9},
        "stochastic": {"n": 14, "smooth_k": 3, "smooth_d": 3},
        "mfi": {"n": 50},
    }
    got = {name: by_id[name].warmup_bars(p) for name, p in params.items()}
    assert got == {"dema": 99, "tema": 148, "keltner": 60, "macd": 40, "stochastic": 16, "mfi": 51}


def test_catalogue_sma_and_ema_defaults_are_20_and_21() -> None:
    assert (SMA.defaults(), EMA.defaults()) == ({"n": 20}, {"n": 21})


def test_catalogue_every_indicator_is_described_for_screen_readers() -> None:
    for d in V1_INDICATORS:
        assert d.title and d.unit and d.nullable_when, d.id
        assert all(o.name for o in d.outputs) and all(p.title for p in d.params), d.id
        assert (d.value_type, d.scope, d.inputs, d.cadence) == (
            "number",
            "symbol",
            ("bars",),
            "on_bar_close",
        ), d.id
        assert d.deterministic and d.confidence == "exact" and not d.estimated, d.id


def test_catalogue_every_numeric_parameter_is_bounded_and_fractional_ones_stepped() -> None:
    for d in (*V1_INDICATORS, DELTA):
        for p in d.params:
            if p.type == "string":
                assert p.enum and p.default in p.enum, (d.id, p.name)
                continue
            assert p.minimum is not None and p.maximum is not None, (d.id, p.name)
            assert (p.multiple_of is not None) == (p.type == "number"), (d.id, p.name)


def test_catalogue_only_vwap_and_supertrend_have_an_output_in_another_unit() -> None:
    mixed = {d.id: d for d in V1_INDICATORS if d.shared_unit() is None}
    assert set(mixed) == {"vwap", "supertrend"}
    assert mixed["vwap"].output_unit("band_sigma") == "zscore"
    assert mixed["supertrend"].output_unit("direction") == "ratio"
    for d in V1_INDICATORS:
        assert d.output_unit(d.outputs[0].id) == d.unit, d.id  # the primary series' unit
        if d.id not in mixed:
            assert d.shared_unit() == d.unit, d.id


def test_catalogue_output_unit_refuses_an_output_the_indicator_lacks() -> None:
    with pytest.raises(KeyError):
        SMA.output_unit("ema")


def test_catalogue_json_defaults_are_json_numbers_and_tokens() -> None:
    by_id = {d.id: d for d in V1_INDICATORS}
    assert by_id["psar"].json_defaults() == {"step": 0.02, "max_step": 0.2}
    assert by_id["bollinger"].json_defaults() == {"n": 20, "mult": 2}
    assert by_id["zigzag"].json_defaults() == {"depth": 5, "deviation_pct": 0}
    assert by_id["cvd"].json_defaults() == {"anchor": "session"}


def test_catalogue_default_catalogue_is_fresh_each_time() -> None:
    first, second = default_catalogue(), default_catalogue()
    first.register(replace(SMA, id="sma_custom", kernel=None, warmup=lambda _: 1))
    assert len(first) == 29 and len(second) == 28
    assert first.get("sma_custom") is not None and second.get("sma_custom") is None


def test_catalogue_refuses_a_duplicate_id() -> None:
    catalogue = IndicatorCatalogue([SMA])
    with pytest.raises(DuplicateIndicatorError, match="already registered"):
        catalogue.register(SMA)


@pytest.mark.parametrize(
    "build",
    [
        lambda: ParamSpec("N", "Period", "integer", 20, 1, 5000),
        lambda: ParamSpec("anchor", "Anchor", "string", "x", enum=("session",)),
        lambda: ParamSpec("anchor", "Anchor", "string", "session"),
        lambda: ParamSpec("n", "Period", "integer", 20),
        lambda: ParamSpec("n", "Period", "integer", 20, 1, 5000, Decimal("1")),
        lambda: ParamSpec("mult", "Mult", "number", Decimal("2"), Decimal(1), Decimal(10)),
        lambda: ParamSpec("n", "Period", "integer", 0, 1, 5000),
        lambda: ParamSpec("m", "M", "number", cast(Any, 2.0), Decimal(1), Decimal(9), Decimal(1)),
        lambda: OutputSpec("Upper", "Upper band"),
        lambda: OutputSpec("upper", ""),
    ],
    ids=[
        "bad-name",
        "enum-without-default",
        "string-without-enum",
        "unbounded",
        "integer-with-step",
        "fraction-without-step",
        "default-out-of-bounds",
        "float-default",
        "bad-output-id",
        "unnamed-output",
    ],
)
def test_catalogue_refuses_a_malformed_parameter_or_output(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match=r"\S"):
        build()


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "Bad"},
        {"title": ""},
        {"outputs": ()},
        {"outputs": (OutputSpec("atr", "ATR"), OutputSpec("atr", "Again"))},
        {"params": (ParamSpec("n", "P", "integer", 14, 1, 5000),) * 2},
        {"id": "atr_custom"},
        {"outputs": (OutputSpec("value", "Value"),)},
        {"params": (ParamSpec("length", "Period", "integer", 14, 1, 5000),)},
        {"nullable_when": "Never null."},
        {"kernel": None, "warmup": lambda _: 0},
    ],
    ids=[
        "bad-id",
        "untitled",
        "no-outputs",
        "duplicate-output",
        "duplicate-param",
        "id-not-the-kernel",
        "outputs-not-the-kernel",
        "params-not-the-kernel",
        "prose-not-the-kernel",
        "no-warmup-bar",
    ],
)
def test_catalogue_refuses_a_definition_that_disagrees_with_itself_or_its_kernel(
    changes: dict[str, Any],
) -> None:
    atr = SERVER_DEFINITIONS["atr"]
    assert atr.kernel is AtrKernel
    with pytest.raises(ValueError, match=r"\S"):
        replace(atr, **changes)
