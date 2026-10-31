"""F1 (E04-Q02, #257): a probe-ticker iteration that raises ends the ticker for good.

`HealthRegistry._loop` calls `refresh()` with no exception guard, so one raise from the unguarded
state observer ends the task and `/admin/health` keeps serving the last snapshot. Charter 1 reports
it, routed to E04 (NQ-1); this is the deterministic in-process reproduction, an expected failure
until the fix lands (strict: the fix turns it into an XPASS that fails CI, so the marker goes then).
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from candleviewer.observability.health_probes import (
    CallableProbe,
    ComponentState,
    HealthRegistry,
    ProbeResult,
)

S = ComponentState


@pytest.mark.xfail(strict=True, reason="F1, fix routed to E04 (NQ-1): the ticker loop has no guard")
async def test_probe_ticker_survives_one_raising_refresh_and_shows_the_next_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yield_once = asyncio.sleep  # the loop's own sleep is replaced; this one stays real
    monkeypatch.setattr(asyncio, "sleep", lambda _s: yield_once(0))
    down = False
    calls = 0

    async def probe() -> ProbeResult:
        return ProbeResult(S.DOWN if down else S.HEALTHY, "")

    def observer(_name: str, _state: S) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:  # the second refresh raises, once
            raise RuntimeError("observer failed")

    reg = HealthRegistry()
    reg.register(CallableProbe("postgres", probe))
    reg.state_observer = observer
    reg.start(1.0)
    try:
        for _ in range(20):
            await yield_once(0)
        first = reg.snapshot()
        assert first is not None and first.overall is S.HEALTHY
        down = True
        for _ in range(200):  # many ticks of the fake clock; no wall time passes
            await yield_once(0)
        latest = reg.snapshot()
        assert latest is not None and latest.overall is S.DOWN
    finally:
        with contextlib.suppress(RuntimeError):  # F1: the dead task re-raises on stop()
            await reg.stop()
