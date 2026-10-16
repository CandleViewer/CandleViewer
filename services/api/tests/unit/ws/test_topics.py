"""E17-S02 topic registry: parser + option schema, conformance cases GENERATED from `FAMILIES`.

Adding a family to `candleviewer.ws.topics.FAMILIES` adds its cases here automatically: every
declared pattern gets a valid sample, a wrong-arity sample (`invalid_topic_format`) and, for
symbol-bearing patterns, a non-USDT-perp sample (`unsupported_symbol`); every declared option
gets an unknown-key twin (`invalid_options`, S12).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws._generated.error_codes import WS_ERROR_CODES
from candleviewer.ws.topics import (
    FAMILIES,
    MIN_THROTTLE_MS,
    TOPIC_REGISTRY,
    TopicError,
    effective_options,
    parse_topic,
    validate_options,
)

_SAMPLE_SEG = {
    "symbol": "BTCUSDT",
    "depth": "50",
    "bar_type": "time",
    "param": "5",
    "profile_kind": "volume",
    "entity": "kill_switch",
    "state": "state",
}


def _sample(family: str, shape: tuple[str, ...]) -> str:
    return ".".join((family, *(_SAMPLE_SEG[s] for s in shape)))


_VALID = [
    pytest.param(_sample(f.family, shape), id=_sample(f.family, shape))
    for f in FAMILIES.values()
    for shape in f.shapes
]


def _code(fn: Any, *args: Any, **kw: Any) -> str:
    with pytest.raises(TopicError) as exc:
        fn(*args, **kw)
    return exc.value.code


@pytest.mark.parametrize("ch", _VALID)
def test_parse_topic_every_declared_pattern_parses(ch: str) -> None:
    t = parse_topic(ch)
    assert t.ch == ch and t.family.family == ch.split(".")[0]


@pytest.mark.parametrize("ch", _VALID)
def test_parse_topic_wrong_arity_is_invalid_topic_format(ch: str) -> None:
    fam = FAMILIES[ch.split(".")[0]]
    arities = {len(s) for s in fam.shapes}
    extra = max(arities) + 1
    bad = ".".join([fam.family, *(["X1"] * extra)])
    assert _code(parse_topic, bad) == "invalid_topic_format"


@pytest.mark.parametrize(
    "ch",
    [pytest.param(_sample(f.family, s), id=f.family) for f in FAMILIES.values() for s in f.shapes
     if "symbol" in s],
)  # fmt: skip
def test_parse_topic_non_usdt_perp_symbol_is_unsupported_symbol(ch: str) -> None:
    assert _code(parse_topic, ch.replace("BTCUSDT", "ETHUSD")) == "unsupported_symbol"
    assert _code(parse_topic, ch.replace("BTCUSDT", "btcusdt")) == "unsupported_symbol"


@pytest.mark.parametrize(
    ("ch", "code"),
    [
        ("book.BTCUSDT.77", "invalid_topic_format"),
        ("bars.BTCUSDT.time.1.5", "invalid_topic_format"),  # dotted param
        ("book.ETHUSD.50", "unsupported_symbol"),
        ("candles.BTCUSDT", "unknown_topic"),
        ("", "invalid_topic_format"),
        ("x" * 121, "invalid_topic_format"),
        (7, "invalid_topic_format"),
        ("bars.BTCUSDT.weird.1", "invalid_topic_format"),
        ("profile.BTCUSDT.tpx", "invalid_topic_format"),
        ("bars.BTCUSDT.renko.a-b", "invalid_topic_format"),
        ("book.BTCUSDT.x", "invalid_topic_format"),
    ],
)
def test_parse_topic_malformed_names_are_distinguished(ch: Any, code: str) -> None:
    assert _code(parse_topic, ch) == code


@pytest.mark.parametrize("depth", [1, 50, 200, 500])
def test_parse_topic_book_depth_enum(depth: int) -> None:
    assert parse_topic(f"book.BTCUSDT.{depth}").depth == depth


@pytest.mark.parametrize("param", ["atr:14", "10:3", "1", "D"])
def test_parse_topic_colon_params_are_legal(param: str) -> None:
    assert parse_topic(f"bars.BTCUSDT.renko.{param}").param == param


def test_parse_topic_unknown_instrument_is_unsupported_symbol() -> None:
    assert _code(parse_topic, "trades.ZZZUSDT", instrument_known=lambda s: s == "BTCUSDT") == (
        "unsupported_symbol"
    )


@pytest.mark.parametrize(
    ("family", "opt"),
    [pytest.param(f.family, o, id=f"{f.family}.{o}") for f in FAMILIES.values() for o in f.options],
)
def test_validate_options_typo_of_every_declared_option_is_rejected(family: str, opt: str) -> None:
    with pytest.raises(TopicError) as exc:
        validate_options(FAMILIES[family], {opt + "x": 1})
    assert (exc.value.code, exc.value.field) == ("invalid_options", opt + "x")


@pytest.mark.parametrize(
    ("family", "opts", "ok"),
    [
        ("footprint", {"min_stack": 2}, True),
        ("footprint", {"min_stack": 10}, True),
        ("footprint", {"min_stack": 1}, False),
        ("footprint", {"min_stack": 11}, False),
        ("footprint", {"min_stack": True}, False),
        ("ticker", {"symbols": ["BTCUSDT"] * 40}, True),
        ("ticker", {"symbols": ["BTCUSDT"] * 41}, False),
        ("ticker", {"symbols": ["ETHUSD"]}, False),
        ("trades", {"min_size": "0.5"}, True),
        ("trades", {"min_size": 0.5}, False),
        ("heatmap", {"time_bucket_ms": 1000}, True),
        ("heatmap", {"time_bucket_ms": 999}, False),
        ("orders", {"exchange_account_ids": ["nope"]}, False),
        ("orders", {"exchange_account_ids": []}, False),
        ("book", {"throttle_ms": 60001}, False),
        ("book", {"encoding": "xml"}, False),
        ("footprint", {"imbalance_ratio": 1.5}, True),
        ("metrics", {"param": "a.b"}, False),
        ("metrics", {"metrics": ["cvd"], "param": "atr:14"}, True),
    ],
)
def test_validate_options_boundaries(family: str, opts: dict[str, Any], ok: bool) -> None:
    if ok:
        assert validate_options(FAMILIES[family], opts) == opts
    else:
        assert _code(validate_options, FAMILIES[family], opts) == "invalid_options"


def test_validate_options_non_object_is_invalid() -> None:
    assert _code(validate_options, FAMILIES["book"], [1]) == "invalid_options"


@pytest.mark.parametrize(("requested", "effective"), [(5, 50), (50, 50), (1000, 1000)])
def test_effective_throttle_is_floored_at_50(requested: int, effective: int) -> None:
    eff = effective_options(parse_topic("book.BTCUSDT.50"), {"throttle_ms": requested})
    assert eff["throttle_ms"] == effective == max(requested, MIN_THROTTLE_MS)


def test_effective_defaults_per_topic() -> None:
    assert effective_options(parse_topic("book.BTCUSDT.1"), {})["throttle_ms"] == 20
    assert effective_options(parse_topic("book.BTCUSDT.200"), {})["throttle_ms"] == 100
    assert effective_options(parse_topic("heatmap.BTCUSDT"), {})["throttle_ms"] == 500
    hm = effective_options(parse_topic("heatmap.BTCUSDT"), {"time_bucket_ms": 1000})
    assert hm["throttle_ms"] == 1000
    hm = effective_options(parse_topic("heatmap.BTCUSDT"), {"throttle_ms": 5})
    assert hm["throttle_ms"] == 50
    orders = effective_options(parse_topic("orders"), {"throttle_ms": 500})
    assert (orders["throttle_ms"], orders["coalesce"]) == (0, False)  # never throttled
    assert effective_options(parse_topic("profile.BTCUSDT.tpo"), {})["encoding"] == "structured"


def test_binary_on_structured_only_topic_is_encoding_unsupported() -> None:
    for f in FAMILIES.values():
        if f.binary or f.family == "system":
            continue
        ch = _sample(f.family, f.shapes[0])
        code = _code(effective_options, parse_topic(ch), {"encoding": "binary"})
        assert code == "encoding_unsupported", f.family


def test_registry_exposes_pattern_and_permission_pairs() -> None:
    pairs = dict(TOPIC_REGISTRY)
    assert pairs["book.{symbol}.{depth}"] == "marketdata:read"
    assert pairs["ticker"] == "marketdata:read"
    assert pairs["wallet"] == "accounts:read"
    assert pairs["system"] is None
    # `machines` contributes one pattern per §6.4 kind instead of its family pattern
    assert len(TOPIC_REGISTRY) == sum(len(f.shapes) for f in FAMILIES.values()) - 1 + 13
    assert pairs["machines.order:{uuid}.state"] == "orders:read"
    assert pairs["machines.session:{uuid}.state"] is None


def test_every_error_code_the_registry_can_raise_is_in_the_catalogue() -> None:
    raised = {
        "unknown_topic", "invalid_topic_format", "unsupported_symbol", "invalid_options",
        "encoding_unsupported",
    }  # fmt: skip
    assert raised <= {c.value for c in WS_ERROR_CODES}
