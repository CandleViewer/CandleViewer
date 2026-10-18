"""#3346: one failed module `stop()` never keeps `Supervisor._stop_each` from the next one.

`_stop_each` promises that a raising or hanging `stop()` never prevents a later one, such as
`secrets.stop()` zeroing the KEK (C-2.7, C-12.2). These tests run the real `_stop_each` over
`audit` then `secrets`, with an `audit` stop that hangs or raises, and read the bound each stop is
given instead of timing it (#3342): `asyncio.timeout` is replaced by a recorder that cuts the
guarded stop at once, so nothing sleeps and no assertion depends on elapsed time. `_stop_each`
stops the names it is given in that order; the reverse start order `stop_all` gives it is pinned
by `tests/unit/credentials_m2/test_degraded_wiring.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import cast

import pytest

from candleviewer.app import AppContext, Supervisor

_GRACE_S = 0.05
#: Patched over `STOP_SLACK_S` (1.0), so a literal 1 s slack in `_stop_each` would ask for 1.05.
_SLACK_S = 0.1


async def _hang() -> None:
    await asyncio.Event().wait()


async def _raise() -> None:
    raise RuntimeError("audit stop failed")  # before any wait, so the cut cannot land first


class _Audit:
    """The first module: records its `stop()`, then hangs or raises, and records how it ended."""

    def __init__(self, events: list[str], fail: Callable[[], Awaitable[None]]) -> None:
        self._events, self._fail = events, fail

    async def stop(self, grace_s: float) -> None:
        self._events.append(f"audit.stop({grace_s:g})")
        try:
            await self._fail()
        except asyncio.CancelledError:  # the bound's cut, re-raised for the timeout to absorb
            self._events.append("audit cut")
            raise
        except RuntimeError:
            self._events.append("audit raised")
            raise


class _Secrets:
    """The later module: records its `stop()` and returns without yielding, before any cut."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def stop(self, grace_s: float) -> None:
        self._events.append(f"secrets.stop({grace_s:g})")


@pytest.fixture
def bounds(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """Every bound `_stop_each` asks `asyncio.timeout` for, in call order. Each guarded stop is
    cut at once (`timeout(0)`): a hung stop ends at its first wait instead of after its bound."""
    monkeypatch.setattr("candleviewer.app.STOP_SLACK_S", _SLACK_S)
    asked: list[float | None] = []
    real_timeout = asyncio.timeout

    def _cut_at_once(delay: float | None) -> asyncio.Timeout:
        asked.append(delay)
        return real_timeout(0)

    monkeypatch.setattr(asyncio, "timeout", _cut_at_once)
    return asked


@pytest.mark.parametrize(
    ("fail", "ended"), [(_hang, "audit cut"), (_raise, "audit raised")], ids=["hung", "raising"]
)
async def test_stop_each_after_a_hung_or_raising_stop_still_stops_secrets_with_its_own_bound(
    bounds: list[float | None], fail: Callable[[], Awaitable[None]], ended: str
) -> None:
    """`secrets` stops once `audit`'s stop was cut or raised, with the same grace and a bound of
    its own: the grace plus the slack, not what `audit` left of one. A `return` or `break` after
    the failure log, a reversed loop, one deadline for all stops or concurrent stops (in the hung
    case) each fail it."""
    events: list[str] = []
    ctx = SimpleNamespace(audit=_Audit(events, fail), secrets=_Secrets(events))
    supervisor = Supervisor(cast(AppContext, ctx))
    # `wait_for` bounds the test itself through `asyncio.timeouts`, which the patch leaves alone.
    await asyncio.wait_for(supervisor._stop_each(["audit", "secrets"], _GRACE_S), 5)
    assert events == ["audit.stop(0.05)", ended, "secrets.stop(0.05)"]
    assert bounds == [pytest.approx(0.15), pytest.approx(0.15)]  # 0.05 grace + 0.1 slack, each
