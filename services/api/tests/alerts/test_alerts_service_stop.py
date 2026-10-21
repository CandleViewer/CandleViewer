"""E40-T04 PR-B (review round 1): the alerts module stops every part it started, whichever one
fails to stop, and `AlertsTopic.stop` never swallows the cancellation of whoever is stopping it
(#3361)."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from candleviewer.alerts.dispatcher import AlertDispatcher
from candleviewer.alerts.service import AlertsService
from candleviewer.alerts.ws_topic import AlertsTopic
from tests.alerts._alerts_ws import USER_A, FakeReader, World


class _Part:
    """The evaluator, the dispatcher or the topic as the service drives them, recording each call
    in the order the service made it; its `stop` can fail."""

    def __init__(self, name: str, calls: list[str], *, stop_fails: bool = False) -> None:
        self.name, self.calls, self.stop_fails = name, calls, stop_fails

    async def warm_up(self) -> None: ...

    def start(self) -> None:
        self.calls.append(f"start {self.name}")

    async def stop(self, grace_s: float = 5.0) -> None:
        self.calls.append(f"stop {self.name}")
        if self.stop_fails:
            raise RuntimeError(f"{self.name} stop failed")


@pytest.mark.parametrize("failing", ["evaluator", "dispatcher", "topic"])
async def test_stop_stops_every_part_whichever_one_fails_and_raises(failing: str) -> None:
    calls: list[str] = []
    parts = {
        name: _Part(name, calls, stop_fails=name == failing)
        for name in ("evaluator", "dispatcher", "topic")
    }

    async def factory() -> Any:
        return parts["evaluator"]

    svc = AlertsService()
    svc.bind(factory, cast(AlertDispatcher, parts["dispatcher"]))
    svc.bind_topic(cast(AlertsTopic[Any], parts["topic"]))
    await svc.start(None)  # type: ignore[arg-type]  # ctx is unused on this path
    assert calls == ["start topic", "start dispatcher", "start evaluator"]
    calls.clear()
    with pytest.raises(RuntimeError, match=f"{failing} stop failed"):
        await svc.stop(1.0)
    # in-flight firings drain first, the dispatcher's last settles may tell the topic: it is last
    assert calls == ["stop evaluator", "stop dispatcher", "stop topic"]
    assert svc.evaluator is None


class _Stubborn(FakeReader):
    """A read that survives its first cancellation and keeps waiting."""

    def __init__(self) -> None:
        super().__init__()
        self.swallowed = asyncio.Event()  # set once the first cancellation has been taken
        self.release = asyncio.Event()

    async def list_page(self, **kw: Any) -> Any:
        try:
            return await super().list_page(**kw)
        except asyncio.CancelledError:
            self.swallowed.set()
            await self.release.wait()
            raise


async def test_stop_propagates_a_cancellation_of_its_own_caller() -> None:
    """A load that does not die at once keeps `stop` waiting; the task running `stop` can still be
    cancelled, and `stop` ends by that cancellation (the service's own shutdown is cancellable)."""
    w = World(attached=False)
    reader = _Stubborn()
    reader.gate = asyncio.Event()  # the load is mid-read, and stays so
    w.topic.attach(reader)
    w.conn(USER_A).sub()
    await asyncio.wait_for(reader.entered.wait(), timeout=5)
    stopper = asyncio.ensure_future(w.topic.stop())
    await asyncio.wait_for(reader.swallowed.wait(), timeout=5)  # `stop` is waiting on the load
    assert not stopper.done()
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert stopper.cancelled()
    reader.release.set()  # the load, cancelled once more by that, has ended
    await w.topic.stop()
    assert w.tasks() == []
