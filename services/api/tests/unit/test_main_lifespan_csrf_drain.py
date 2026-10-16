"""#2264: the ASGI lifespan drains in-flight CSRF-refusal audits before the audit module stops.

Behavioural, through the `test_main_lifespan.py` harness: the fake `audit` module records what
the tracker holds when it is stopped, so removing or reordering the drain fails here.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI

from candleviewer.api.csrf import RefusalAuditTracker
from candleviewer.main import _lifespan
from tests.unit.test_main_lifespan import _fake_ctx


class _AuditModule:
    def __init__(self, tracker: RefusalAuditTracker) -> None:
        self.tracker = tracker
        self.in_flight_at_stop: int | None = None

    async def start(self, ctx: object) -> None:
        return None

    async def stop(self, grace_s: float) -> None:
        self.in_flight_at_stop = len(self.tracker)


class _ShortDrain(RefusalAuditTracker):
    """The same tracker with a short bound on the shutdown drain, so a leftover is quick."""

    async def drain(self, timeout_s: float = 0.01) -> int:
        return await super().drain(timeout_s)


def _app(tracker: RefusalAuditTracker) -> tuple[FastAPI, _AuditModule]:
    app, ctx = FastAPI(), _fake_ctx()
    ctx.audit = _AuditModule(tracker)
    app.state.app_context = ctx
    app.state.csrf_refusal_audits = tracker
    return app, ctx.audit


async def test_lifespan_drains_in_flight_audits_before_the_audit_module_stops() -> None:
    tracker, lost = RefusalAuditTracker(), list[str]()
    app, audit = _app(tracker)
    finish = asyncio.Event()

    async def audit_write() -> None:
        await finish.wait()  # the "WAL append" is still running when shutdown starts

    write = tracker.track(audit_write(), on_lost=lambda: lost.append("lost"))
    async with _lifespan(app):
        # It completes at the next turn of the loop; only the drain gives it one before the
        # audit module stops (the fake modules never suspend).
        asyncio.get_running_loop().call_soon(finish.set)

    assert write.done() and audit.in_flight_at_stop == 0
    assert lost == []  # it landed: nothing was lost at shutdown


async def test_lifespan_reports_an_undrained_audit_to_its_owner_and_still_stops_audit() -> None:
    tracker, lost = _ShortDrain(), list[str]()
    app, audit = _app(tracker)
    never = asyncio.Event()

    async def stuck_write() -> None:
        await never.wait()

    write = tracker.track(stuck_write(), on_lost=lambda: lost.append("lost"))
    async with _lifespan(app):
        pass

    assert audit.in_flight_at_stop == 1  # a stuck write never blocks shutdown
    assert lost == ["lost"]
    write.cancel()
    await asyncio.gather(write, return_exceptions=True)
