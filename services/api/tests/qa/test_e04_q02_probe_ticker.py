"""F1 (E04-Q02, #257): a probe-ticker iteration that raises ends the ticker for good.

`HealthRegistry._loop` calls `refresh()` with no exception guard, so one raise from the unguarded
state observer ends the task and `/admin/health` keeps serving the last snapshot. Charter 1 reports
it as #5173 (P1, area/backend-platform; NQ-1, ruled). This is the deterministic in-process
reproduction: a strict expected failure until the fix lands, then skipped (see `_FIXED`).
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


# Order-independent with the fix (#5173, PR #5175): once `HealthRegistry` carries the
# refresh-failure handling, `tests/unit/observability/test_health_probes.py` covers the case and
# this one is skipped; before it the loop has no guard and this is a strict expected failure.
_FIXED = hasattr(HealthRegistry, "_mark_refresh_failed")


@pytest.mark.skipif(
    _FIXED, reason="fixed by #5173; covered by tests/unit/observability/test_health_probes.py"
)
@pytest.mark.xfail(strict=True, reason="F1, #5173: the ticker loop has no exception guard")
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
