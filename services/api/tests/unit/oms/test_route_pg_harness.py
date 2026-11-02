"""#5185: the Postgres route tests' wait for a process's startup reconciliation pass (`_reconciled`,
`tests/integration/oms/test_place_order_route_pg.py`) leaves the serving loop idle. It used to turn
that loop in place (`await asyncio.sleep(0)`) until the pass recorded itself. The pass reads only
once the requests the startup resumed have answered (24 Sec.8.5), so that turning covered their
step writes on the order lane's thread, which shares the process's GIL and cores: on a slow runner
the spinning thread held both against the lane, and the writes missed their 1 s bound
(`CV_PERSIST_TIMEOUT`). No database and no sleeps; each bound only turns a hang into a failure."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.domain.primitives import AccountId
from tests.integration.oms import test_place_order_route_pg as route
from tests.integration.oms import test_submission_pipeline_pg as c6

#: A bound on each wait here, never a time a test expects.
_BOUND_S = 10.0


def _world(tmp_path: Path) -> route.World:
    """A world with no database behind it: `_reconciled` reads its audit log only."""
    clock = c6.Clock(datetime(2026, 11, 1, tzinfo=UTC))
    return route.World("", AccountId(uuid4()), uuid4(), clock, tmp_path / "machine_events.wal")


def _turned(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("the wait for the startup pass turned the serving loop")


async def test_the_wait_never_turns_the_serving_loop_and_fails_past_its_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No pass is recorded: the wait ends `TimeoutError` at its bound, and it never turned the
    serving loop meanwhile (`asyncio.sleep`, the spin's step, is never called)."""
    world = _world(tmp_path)
    monkeypatch.setattr(route, "_READY_BOUND_S", 0.05)
    with monkeypatch.context() as patched:
        patched.setattr(asyncio, "sleep", _turned)
        with pytest.raises(TimeoutError):
            await route._reconciled(world, 0)


async def test_a_pass_recorded_on_the_lanes_thread_ends_the_wait_while_the_loop_runs(
    tmp_path: Path,
) -> None:
    """The pass's record lands on another thread (the order lane's, #913 L2), once the serving loop
    has run a task of its own while the wait was on: the loop stayed free, and the record, not the
    wait's bound, ended the wait."""
    world = _world(tmp_path)
    ran = threading.Event()

    def record() -> None:
        if ran.wait(_BOUND_S):
            asyncio.run(world.writer.emit("oms.reconcile", reason="finished"))

    async def beside() -> None:
        ran.set()

    lane = threading.Thread(target=record, name="lane-stand-in", daemon=True)
    lane.start()
    await asyncio.wait_for(asyncio.gather(route._reconciled(world, 0), beside()), _BOUND_S)
    lane.join(_BOUND_S)
    assert route._passes(world) == 1
