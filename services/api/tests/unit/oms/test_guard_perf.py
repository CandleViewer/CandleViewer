"""The order-path guard's budget (E28-T04, #908; US-PROF-004: at most 5 ms p95 added to the order
path) and its isolation: `Validator.check_order` on the sized order and the risk gate's verdict,
the synchronous span `cv_risk_guard_seconds` times in `OrderSubmission`, judged from memory alone.

The budget test is `perf`-marked, so the unit lane deselects it and the `py-perf` job runs it
without coverage. It is calibrated for shared runners as the other perf tests are (#1943): GC is
off around the timed rounds, each round times `CHECKS` warm checks, and the fastest round's p95 is
the measure (host load only ever adds time). The isolation test is a unit test: the same checks
run with every socket and file open refused, outside any event loop, and nothing they call awaits.
"""

from __future__ import annotations

import builtins
import gc
import inspect
import socket
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.oms.ports import InterimRiskGate, OrderEffect
from candleviewer.oms.validator import Validator
from tests.unit.oms.quantile import quantile
from tests.unit.oms.test_order_validator import _Gate, _instrument, _order, _profile

ROUNDS = 3
CHECKS = 1_000
#: US-PROF-004: the guard adds at most 5 ms to the order path at p95.
BUDGET_NS = 5_000_000
_NOW = datetime(2026, 11, 4, tzinfo=UTC)


def _guard() -> tuple[Validator, InterimRiskGate]:
    return Validator(read_only_gate=_Gate()), InterimRiskGate(now=lambda: _NOW)


def _orders() -> list[Any]:
    """An entry under `*USDT` (the wildcard expanded at check time) and an order that only
    reduces, so both of the guard's branches are timed."""
    reduce = {"reduce_only": True, "effect": OrderEffect.REDUCE, "intent": "scale_out"}
    return [_order(), _order(side="sell", stop_loss=None, **reduce)]


def _round(samples: list[int]) -> None:
    validator, gate = _guard()
    profile, instrument = _profile("fixed_notional"), _instrument()
    orders = _orders()
    for n in range(CHECKS):
        order = orders[n % 2]
        started = time.perf_counter_ns()
        validator.check_order(order, instrument=instrument, profile=profile)
        decision = gate.check(order, profile=profile)
        samples.append(time.perf_counter_ns() - started)
        assert decision.allowed


@pytest.mark.perf
def test_the_guard_fits_5_ms_at_p95_over_1000_warm_checks() -> None:
    best = 0.0
    gc.collect()
    gc.disable()  # a collection inside one timed check would skew the sample
    try:
        _round([])  # warm-up: imports, compiled validators, the matcher's first pattern
        for _ in range(ROUNDS):
            samples: list[int] = []
            _round(samples)
            assert len(samples) == CHECKS
            p95 = quantile(samples, 0.95)
            best = p95 if best == 0 else min(best, p95)
    finally:
        gc.enable()
    assert best <= BUDGET_NS, f"p95 {best / 1e6:.3f} ms > {BUDGET_NS / 1e6:.0f} ms"


def test_check_touches_no_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC9's isolation for the path that exists (C-2.21): nothing the guard runs is a coroutine,
    and it judges with every socket and every file open refused, outside any event loop."""
    validator, gate = _guard()
    assert not inspect.iscoroutinefunction(validator.check_order)
    assert not inspect.iscoroutinefunction(gate.check)

    def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the guard reached for I/O")

    profile, instrument = _profile("fixed_notional"), _instrument()
    orders = _orders()
    monkeypatch.setattr(socket, "socket", refused)
    monkeypatch.setattr(builtins, "open", refused)
    for order in orders:
        validator.check_order(order, instrument=instrument, profile=profile)
        assert gate.check(order, profile=profile).allowed
