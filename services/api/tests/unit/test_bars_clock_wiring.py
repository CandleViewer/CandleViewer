"""#529: the bar builders run on the exchange-corrected clock, not the raw host clock."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.app import create_app, exchange_corrected_clock
from candleviewer.bars_wiring import wire_bars
from candleviewer.settings import Environment, Settings

OFFSET_US = 120_000_000  # venue 2 min ahead of the host


class _Guard:
    def __init__(self, offset_us: int) -> None:
        self.offset = offset_us

    def offset_us(self) -> int:
        return self.offset


def _ctx(guard: _Guard | None) -> Any:
    return SimpleNamespace(ingestion=SimpleNamespace(clock=guard))


def _host_us() -> int:
    return time.time_ns() // 1000


def test_exchange_corrected_clock_adds_the_guard_offset() -> None:
    clock = exchange_corrected_clock(_ctx(_Guard(OFFSET_US)))
    before = _host_us()
    now = clock()
    assert before + OFFSET_US <= now <= _host_us() + OFFSET_US


def test_exchange_corrected_clock_follows_the_guard_per_call() -> None:
    guard = _Guard(OFFSET_US)
    clock = exchange_corrected_clock(_ctx(guard))
    guard.offset = -OFFSET_US
    assert clock() < _host_us() - OFFSET_US + 1_000_000


def test_exchange_corrected_clock_without_a_guard_is_the_host_clock() -> None:
    clock = exchange_corrected_clock(_ctx(None))
    before = _host_us()
    assert before <= clock() <= _host_us()


def test_exchange_corrected_clock_resolves_a_late_attached_guard() -> None:
    ctx = _ctx(None)
    clock = exchange_corrected_clock(ctx)  # built before the public WS attaches the guard
    ctx.ingestion.clock = _Guard(OFFSET_US)
    assert clock() >= _host_us() + OFFSET_US - 1_000_000


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        git_sha="deadbeef",
        version="9.9.9",
        bars_state_root=str(tmp_path / "bars"),
        metrics_enabled=False,
    )


def test_create_app_hands_the_corrected_clock_to_the_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    real = wire_bars

    def spy(ctx: Any, **kwargs: Any) -> Any:
        seen["now_us"] = kwargs["now_us"]
        return real(ctx, **kwargs)

    monkeypatch.setattr("candleviewer.app.wire_bars", spy)
    app = create_app(_settings(tmp_path))
    app.state.app_context.ingestion.clock = _Guard(OFFSET_US)  # as `wire_clock_offset` attaches
    assert seen["now_us"]() >= _host_us() + OFFSET_US - 1_000_000


def test_create_app_keeps_the_bars_now_us_test_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    real = wire_bars

    def spy(ctx: Any, **kwargs: Any) -> Any:
        seen["now_us"] = kwargs["now_us"]
        return real(ctx, **kwargs)

    monkeypatch.setattr("candleviewer.app.wire_bars", spy)
    app = create_app(_settings(tmp_path), bars_now_us=lambda: 42)
    app.state.app_context.ingestion.clock = _Guard(OFFSET_US)
    assert seen["now_us"]() == 42
