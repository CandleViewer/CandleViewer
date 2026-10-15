"""Bounded label values on the client WS gateway metrics (PR #2209 review)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from candleviewer.ws.gateway import close_reason_label
from candleviewer.ws.lifecycle import CLOSE_REASONS
from candleviewer.ws.upstream import (
    MAX_SYMBOL_LABELS,
    OTHER_SYMBOL,
    UpstreamRefs,
    cv_ws_upstream_consumers_in_use,
)


@pytest.fixture(autouse=True)
def _clean_upstream_gauge() -> Iterator[None]:
    """The gauge is module-global; isolate every test from series leaked by others (#2360)."""
    cv_ws_upstream_consumers_in_use.clear()
    yield
    cv_ws_upstream_consumers_in_use.clear()


def _series() -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for metric in cv_ws_upstream_consumers_in_use.collect():
        for s in metric.samples:
            out[(s.labels["symbol"], s.labels["topic"])] = s.value
    return out


def test_close_reason_label_unknown_reason_records_other() -> None:
    assert close_reason_label("totally-made-up-reason-from-a-client") == "other"


def test_close_reason_label_known_reasons_pass_through() -> None:
    for reason in CLOSE_REASONS:
        assert close_reason_label(reason) == reason


async def test_upstream_gauge_removed_when_refcount_reaches_zero() -> None:
    refs = UpstreamRefs(grace_s=1.0)
    key = ("ZZLBLUSDT", "trades", ())
    await refs.acquire(key, "c1")
    assert _series()[("ZZLBLUSDT", "trades")] == 1
    refs.release(key, "c1", now=0.0)
    assert ("ZZLBLUSDT", "trades") not in _series()
    await refs.sweep(now=5.0)
    assert ("ZZLBLUSDT", "trades") not in _series()


async def test_upstream_gauge_symbol_label_bounded_with_other() -> None:
    refs = UpstreamRefs(grace_s=1.0)
    syms = [f"ZZB{i:03d}USDT" for i in range(MAX_SYMBOL_LABELS + 5)]
    for s in syms:
        await refs.acquire((s, "book", ()), "c1")
    series = {k: v for k, v in _series().items() if k[1] == "book"}
    labelled = {k[0] for k in series} - {OTHER_SYMBOL}
    assert len(labelled) == MAX_SYMBOL_LABELS
    assert series[(OTHER_SYMBOL, "book")] == 5
    for s in syms:
        refs.release((s, "book", ()), "c1", now=0.0)
    await refs.sweep(now=5.0)
    assert not [k for k in _series() if k[1] == "book"]


def test_autouse_fixture_is_active_and_starts_clean(request: pytest.FixtureRequest) -> None:
    assert "_clean_upstream_gauge" in request.fixturenames
    assert _series() == {}


def test_fixture_clears_stray_series_before_and_after() -> None:
    """Drive the fixture generator by hand so both halves are proven (#2360)."""
    fixture_fn = getattr(_clean_upstream_gauge, "__wrapped__", None)
    if fixture_fn is None:  # pytest >= 8.4 wraps fixtures in a definition object
        fixture_fn = _clean_upstream_gauge._get_wrapped_function()  # type: ignore[attr-defined]  # noqa: SLF001 - pytest>=8.4 API
    stray = cv_ws_upstream_consumers_in_use.labels(symbol="ZZSTRAYUSDT", topic="book")
    stray.set(1)
    assert ("ZZSTRAYUSDT", "book") in _series()
    gen = fixture_fn()
    next(gen)  # setup half: pre-existing leak is cleared
    assert _series() == {}
    cv_ws_upstream_consumers_in_use.labels(symbol="ZZSTRAYUSDT", topic="book").set(1)
    assert next(gen, None) is None  # teardown half: leak created during the test is cleared
    assert _series() == {}
