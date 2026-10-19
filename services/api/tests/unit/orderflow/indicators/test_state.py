"""Kernel state: `snapshot()` / `restore()` (E13-T02, #426; 24-internal-schemas §7.4 "State").

A restore mid-series resumes bit-identically; a blob from another kernel, version, build, params,
source or context, or a malformed one, raises `IndicatorStateError` and leaves the kernel as it
was. `None` is written as JSON null and never read back as a number.
"""

from __future__ import annotations

from typing import Any

import orjson
import pytest

from candleviewer.orderflow.errors import IndicatorStateError
from candleviewer.orderflow.indicators import (
    KERNELS,
    STATE_VERSION,
    BarInput,
    Kernel,
    KernelContext,
    build_kernel,
    compute,
)
from tests.unit.orderflow.indicators._bars import VALID, bits

CTX = KernelContext(0)


def _kernel(name: str, ctx: KernelContext = CTX) -> Kernel:
    params, source = VALID[name]
    return build_kernel(name, params, source=source, context=ctx)


@pytest.mark.parametrize("cut", [0, 1, 13, 214, 449])
@pytest.mark.parametrize("name", sorted(KERNELS))
def test_restore_mid_series_resumes_bit_identically(
    name: str, cut: int, kline: list[BarInput]
) -> None:
    params, source = VALID[name]
    whole = compute(name, kline, params, source=source, context=CTX)
    first = _kernel(name)
    head = first.run(kline[:cut])
    second = _kernel(name)
    second.restore(first.snapshot())
    assert bits(head + second.run(kline[cut:])) == bits(whole)


def test_snapshot_header_names_the_kernel_build_params_source_and_context() -> None:
    doc = orjson.loads(_kernel("zigzag", KernelContext(480)).snapshot())
    assert STATE_VERSION == 1
    assert {k: v for k, v in doc.items() if k != "state"} == {
        "v": 1,
        "indicator": "zigzag",
        "build_version": KERNELS["zigzag"].build_version,
        "params": {"depth": "5", "deviation_pct": "0.1"},
        "source": None,
        "context": {"session_anchor_utc_min": 480},
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("v", 2),
        ("v", True),
        ("indicator", "ema"),
        ("build_version", 2),
        ("build_version", 1.0),
        ("params", {"n": "21"}),
        ("source", "hlc3"),
        ("context", {"session_anchor_utc_min": 480}),
        ("state", None),
    ],
)
def test_a_blob_for_another_kernel_is_refused_and_changes_nothing(
    field: str, value: object, kline: list[BarInput]
) -> None:
    kernel = _kernel("sma")
    kernel.run(kline[:30])
    before = kernel.snapshot()
    doc = orjson.loads(before)
    doc[field] = value
    with pytest.raises(IndicatorStateError):
        kernel.restore(orjson.dumps(doc))
    assert kernel.snapshot() == before


@pytest.mark.parametrize("blob", [b"not json", b"[]", b"null", b'"sma"'])
def test_a_blob_that_is_not_an_object_is_refused(blob: bytes) -> None:
    with pytest.raises(IndicatorStateError):
        _kernel("sma").restore(blob)


ZIGZAG_RING: dict[str, Any] = {"j": 9, "highs": [1.0] * 7, "lows": [1.0] * 7}
BAD_STATES: list[tuple[str, dict[str, Any]]] = [
    ("sma", {"k": 25, "sum": 1.0, "ring": [1.0] * 19}),
    ("sma", {"k": 1, "sum": 1.0, "ring": "x"}),
    ("sma", {"k": -1, "sum": 1.0, "ring": []}),
    ("sma", {"k": 1, "sum": None, "ring": [1.0]}),
    ("sma", {"k": True, "sum": 1.0, "ring": [1.0]}),
    ("ema", {"avg": [21, 1.0, None]}),
    ("ema", {"avg": [3, 1.0, 2.0]}),
    ("ema", {"avg": [3, 1.0]}),
    ("rsi", {"prev": "x", "gain": [0, 0.0, None], "loss": [0, 0.0, None]}),
    ("adx", {"prev": [1.0, 2.0], "averages": [[0, 0.0, None]] * 4}),
    ("adx", {"prev": None, "averages": [[0, 0.0, None]] * 3}),
    ("vwap", {"session": 0, "w_sum": -1.0, "mean": 0.0, "s": 0.0}),
    ("vwap", {"session": "x", "w_sum": 0.0, "mean": 0.0, "s": 0.0}),
    ("cvd", {"period": None, "cvd": None}),
    ("volume", {"x": 1}),
    (
        "zigzag",
        {"j": 2, "highs": [1.0], "lows": [1.0, 2.0], "extrema": [[]] * 4, "swings": [None, None]},
    ),
    (
        "zigzag",
        {
            "j": 9,
            "highs": [1.0] * 7,
            "lows": [1.0] * 7,
            "extrema": [[[5, 1.0], [4, 1.0]], [], [], []],
            "swings": [None, None],
        },
    ),
    ("zigzag", {"j": 0, "highs": [], "lows": [], "extrema": [[]] * 4, "swings": [None]}),
    ("zigzag", {**ZIGZAG_RING, "extrema": [[]] * 3, "swings": [None, None]}),
    ("zigzag", {**ZIGZAG_RING, "extrema": ["x", [], [], []], "swings": [None, None]}),
    ("zigzag", {**ZIGZAG_RING, "extrema": [[1.0], [], [], []], "swings": [None, None]}),
]


@pytest.mark.parametrize(("name", "state"), BAD_STATES)
def test_a_malformed_state_is_refused_and_changes_nothing(
    name: str, state: dict[str, Any], kline: list[BarInput]
) -> None:
    kernel = _kernel(name)
    kernel.run(kline[:40])
    before = kernel.snapshot()
    doc = orjson.loads(before)
    doc["state"] = state
    with pytest.raises(IndicatorStateError, match="malformed"):
        kernel.restore(orjson.dumps(doc))
    assert kernel.snapshot() == before


def test_none_is_written_as_null_and_restored_as_none(kline: list[BarInput]) -> None:
    kernel = _kernel("ema")
    kernel.run(kline[:3])
    doc = orjson.loads(kernel.snapshot())
    assert doc["state"]["avg"][2] is None
    fresh = _kernel("ema")
    fresh.restore(kernel.snapshot())
    assert fresh.run(kline[3:21]) == kernel.run(kline[3:21])
