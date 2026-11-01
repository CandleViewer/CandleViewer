"""E12-X02 AC1 / X01 AC-03 (#452): every parameter of `/market/bars` and `/market/klines`, hostile,
answers per the oracle (`_oracle.check`): a declared status and catalogued code, no traceback, path,
SQL or echo, and every 200 within the caps. Two lanes:

- PR lane: the dictionary (`_corpus.cases`), then a derandomised Hypothesis property over the
  whole parameter product (300 examples).
- Nightly fuzz: not wired yet (PR-2). The same property at 5 000 examples carries E08-X02's
  `fuzz` marker, which the default lane deselects; no workflow selects this file yet.

The world is E12-Q04's (`_market_world`): recorded data, in process, no socket (C-13.5). Its
client hands a server error back as the 500 it is (`raise_server_exceptions=False`), so the
oracle judges it as a status (`StatusError`) instead of the test dying on the exception.

A known gap is a strict xfail on the one oracle rule it breaks (`raises=`, `_RAISES`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import cache

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.contract._market_world import MarketWorld
from tests.security.bars import _corpus, _oracle

PR = settings(
    max_examples=300, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
NIGHTLY = settings(
    max_examples=5_000, derandomize=True, deadline=None, suppress_health_check=list(HealthCheck)
)
_CASES = _corpus.cases()
_RAISES: dict[str, type[_oracle.OracleError]] = {
    _corpus.F1: _oracle.SpanCapError,  # served over the 400-day cap
    _corpus.F7: _oracle.StatusError,  # a 500
}


@cache
def _world() -> MarketWorld:
    """One app for the module: the corpus and the property only read (C-13.7: no state kept)."""
    world = MarketWorld()
    world.client = TestClient(world.app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    return world


def _known(reason: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(strict=True, raises=_RAISES[reason], reason=reason)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(c, id=f"{c.op}-{i}", marks=[_known(c.xfail)])
        if c.xfail
        else pytest.param(c, id=f"{c.op}-{i}")
        for i, c in enumerate(_CASES)
    ],
)
def test_param_fuzz_dictionary_probe_answers_per_the_oracle(case: _corpus.Case) -> None:
    _oracle.check(case.op, case.query, _world().get(case.op, case.query))


def test_param_fuzz_dictionary_covers_both_routes_and_every_parameter() -> None:
    names = {name for c in _CASES for name in c.query}
    assert {"getBars", "getKlines"} == {c.op for c in _CASES}
    assert {"symbol", "bar_type", "param", "interval", "from", "to", "limit", "cursor"} <= names
    assert {"price_type"} <= names and sum(c.op == "getBars" for c in _CASES) >= 400


_INSTANTS = st.datetimes(
    min_value=datetime(1971, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)
)
_TEXT = st.one_of(st.sampled_from(_corpus.VALUES), st.text(max_size=40), st.integers().map(str))


_Drawn = tuple[str, dict[str, object]]


@st.composite
def _queries(draw: st.DrawFn) -> _Drawn:
    """A query over the full product. `from` is after the epoch: the pre-epoch window is F1's
    pinned case (`_corpus.WINDOWS`, `test_caps_and_cost`), so this property stays a regression
    gate rather than re-finding a known gap."""
    op = draw(st.sampled_from(("getBars", "getKlines")))
    start = draw(_INSTANTS)
    query: dict[str, object] = {
        "symbol": draw(st.sampled_from(("BTCUSDT", *_corpus.SYMBOLS))),
        "from": start.isoformat().replace("+00:00", "Z"),
        "limit": draw(st.integers(min_value=-5, max_value=6_000)),
        "include_open": draw(st.booleans()),
    }
    if draw(st.booleans()):
        query["to"] = draw(_INSTANTS).isoformat().replace("+00:00", "Z")
    if op == "getBars":
        query["bar_type"] = draw(st.sampled_from(_corpus.BAR_TYPES + _corpus.HOSTILE_BAR_TYPES))
        query["param"] = draw(_TEXT)
    else:
        query["interval"] = draw(_TEXT)
        query["price_type"] = draw(st.sampled_from(_corpus.PRICE_TYPES))
    if draw(st.integers(0, 9)) == 0:
        query["cursor"] = draw(st.sampled_from(_corpus.CURSORS))
    return op, query


@PR
@given(_queries())
def test_param_fuzz_property_every_answer_meets_the_oracle(drawn: _Drawn) -> None:
    op, query = drawn
    _oracle.check(op, query, _world().get(op, query))


@pytest.mark.fuzz
@NIGHTLY
@given(_queries())
def test_param_fuzz_nightly_every_answer_meets_the_oracle(drawn: _Drawn) -> None:
    op, query = drawn
    _oracle.check(op, query, _world().get(op, query))
