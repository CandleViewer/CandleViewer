"""C-13.6 #10 on a real node (E29-Q04 #1148; E29-T04's pipeline step 9 and S7; the ruling's BQ-4:
an outage of the one node, the deployed topology), the VALIDATE commit: the node is stopped as a
submit reaches its first persist, B1's `VALIDATE` (`at_validate`). The request is refused
`503 store_unavailable` before any send: the venue's create count stays as it was, and nothing is
recorded for it. The node took the environment lock's session with it, so the process fences
itself, paged (`oms_environment_lock_lost`, SEC-S3N-01's watchdog), and the oracle finds the book
equal to the venue once the node is back. A restart, the fenced process's way back, then takes the
same request under the same key, unspent, and sends it once; the oracle again. With the node left
up at that commit (`at_validate`'s stop disarmed), the same request is accepted and its create goes
out: the refusal is the outage's (the negative control). Marker `chaos and integration` (`_pg`);
the venue derived in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.oms.errors import StoreUnavailable, problem_for
from candleviewer.oms.order_machine import OrderMachines
from tests.chaos.oms import _pg
from tests.chaos.oms._oracle import check

pytestmark = [pytest.mark.chaos, pytest.mark.integration]
node = _pg.node  # the module's Postgres 16; each test clones its database at head

FIRST, SECOND = 0x161, 0x162  # the two requests' client keys


@contextmanager
def at_validate(stop: Callable[[], None]) -> Iterator[None]:
    """The next order's `VALIDATE` meets `stop` first: B1's `start`, which records it, is entered
    only once `stop` has run (off the lane, outside B1's persist bound); later ones as they are."""
    start, armed = OrderMachines.start, [stop]

    async def stopped_first(self: OrderMachines, *args: Any, **kwargs: Any) -> str:
        if armed:
            await asyncio.to_thread(armed.pop())
        return await start(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(OrderMachines, "start", stopped_first)
        yield


async def test_s16_an_outage_of_the_node_at_the_validate_commit_sends_nothing(
    node: _pg.Node, tmp_path: Path
) -> None:
    db = _pg.fresh(node)
    venue = _pg.Host(held=_pg.HostPort(db.ref))
    async with _pg.running(db, tmp_path, venue) as world:
        first = await world.submit(key=FIRST)
        assert (first.status, first.lifecycle) == (202, "submitted")
        try:
            with at_validate(node.stop), capture_logs() as logs:
                with pytest.raises(StoreUnavailable) as refused:
                    await world.submit(key=SECOND)
        finally:
            began = monotonic()
            await asyncio.to_thread(node.start)
            back = monotonic() - began
        problem = problem_for(refused.value)
        assert (problem.status, problem.code) == (503, "store_unavailable")
        failed = [
            e["ev"] for e in logs
            if e["event"] == "statechart_transition_failed" and e["kind"] == "order"
        ]  # fmt: skip
        steps = [e["step"] for e in logs if e["event"] == "oms_submit_refused"]
        assert (failed, steps) == (["VALIDATE"], ["persist"])  # the commit the outage met
        assert sorted(world.creates().values()) == [1]  # nothing sent for it
        await world.pager.paged("oms_environment_lock_lost")  # fenced: the lock went with the node
        await check(world)  # the first order's row is its venue order's; the refused one has none
    async with _pg.running(db, tmp_path, venue) as again:  # the restart, the way back
        print(f"s16: the node back in {back:.1f} s, the restart ready in {again.ready_s:.1f} s")
        retried = await again.submit(key=SECOND)
        assert (retried.status, retried.lifecycle) == (202, "submitted")
        assert sorted(again.creates().values()) == [1, 1]  # its key unspent: sent once
        await check(again)


async def test_s16_with_the_node_left_up_at_the_validate_commit_the_create_goes_out(
    node: _pg.Node, tmp_path: Path
) -> None:
    db = _pg.fresh(node)
    async with _pg.running(db, tmp_path, _pg.Host(held=_pg.HostPort(db.ref))) as world:
        assert (await world.submit(key=FIRST)).status == 202
        with at_validate(lambda: None):  # its stop disarmed: the node stays up
            outcome = await world.submit(key=SECOND)
        assert (outcome.status, sorted(world.creates().values())) == (202, [1, 1])
        await check(world)
