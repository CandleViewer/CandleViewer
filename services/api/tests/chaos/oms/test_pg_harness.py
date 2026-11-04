"""The Postgres tier's parts that need no Docker (E29-Q04 #1148; C-13.7). The scenarios themselves
are deselected by the PR lanes, so what they lean on runs here: the venue handed from one process
to the next (`_pg.HostPort`), a `PgWorld` among the worlds the oracle must check, the markers
of the scenarios' modules, `chaos`, `integration` and `nightly`, by which the nightly job selects
the tier and the merge group's integration step leaves it out, the node's port outside the
kernel's ephemeral range, and the child's exit once its parent's pipe is closed."""

from __future__ import annotations

import io
import json
import threading
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest

from candleviewer.exchange.base.errors import DuplicateClientIdError
from candleviewer.exchange.base.models import PlaceOrderRequest
from tests.chaos.oms import _child, _pg, test_s14_process_killed, test_s16_postgres_outage
from tests.chaos.oms._venue import Venue
from tests.chaos.oms._world import PRICE, REF, unchecked
from tests.unit.oms.command_rig import link

pytestmark = pytest.mark.chaos


def create(order_link_id: str) -> PlaceOrderRequest:
    return PlaceOrderRequest(
        account=REF, symbol="BTCUSDT", side="buy", order_type="limit", qty=Decimal("0.01"),
        price=PRICE, order_link_id=order_link_id, stop_loss=PRICE - 1000,
    )  # fmt: skip


async def venue_state(port: _pg.HostPort) -> tuple[Any, ...]:
    """What the venue holds, through its own reads: its orders, executions and positions."""
    orders = (*await port.open_orders(REF), *await port.order_history(REF))
    return orders, tuple(await port.executions(REF, 0, 2**62)), tuple(await port.positions(REF))


async def test_the_venue_handed_over_is_the_one_the_next_process_takes_up() -> None:
    last, a, b, c = _pg.HostPort(REF), link(seq=1), link(seq=2), link(seq=3)
    for sent in (a, b):
        await last.place_order(create(sent))
    venue = Venue(last, REF, _pg.now_us)
    await venue.fill(a, Decimal("0.004"), PRICE, push=False)  # part filled: still open
    await venue.fill(b, Decimal("0.01"), PRICE, push=False)  # filled: in the history
    handed = json.loads(json.dumps(last.handed()))  # as the child's file carries it
    after = _pg.HostPort(REF)
    assert after.take(handed) == last.creates() == {a: 1, b: 1}  # the creates are carried
    state = await venue_state(last)
    assert [len(part) for part in state] == [2, 2, 1]  # two orders, two fills, one position
    assert await venue_state(after) == state
    with pytest.raises(DuplicateClientIdError):  # a reused id is refused, as at the venue
        await after.place_order(create(a))
    await after.place_order(create(c))  # and the exchange ids go on from where they stood
    assert len((await venue_state(after))[0]) == 3


async def test_a_pg_world_is_one_the_oracle_must_check_like_any_other(tmp_path: Path) -> None:
    db = _pg.Db("postgresql+asyncpg://cv_app@127.0.0.1:1/q04", REF.account_id, UUID(int=1))
    world = _pg.PgWorld(db, tmp_path, _pg.Host(held=_pg.HostPort(db.ref)))  # connects lazily
    try:
        assert unchecked() == [world]
        world.checked = True
        assert unchecked() == []
    finally:
        await world.pool.dispose()


@pytest.mark.parametrize(
    "scenarios", [test_s14_process_killed, test_s16_postgres_outage], ids=["s14", "s16"]
)
def test_every_postgres_scenario_is_marked_for_the_nightly_job(scenarios: ModuleType) -> None:
    carried = {mark.name for mark in scenarios.pytestmark}
    assert {"chaos", "integration", "nightly"} <= carried


def test_the_nodes_port_is_one_no_outgoing_connection_can_take() -> None:
    assert not 32768 <= _pg.free_port((32768, 60999)) <= 60999  # above the range, never in it
    assert _pg.free_port((1024, 65535)) > 0  # no port outside it: the kernel's pick, as before


def test_the_child_leaves_once_its_parents_pipe_is_closed() -> None:
    reading, closed, left = threading.Event(), threading.Event(), list[int]()

    class Pipe(io.StringIO):
        def read(self, size: int | None = -1) -> str:
            reading.set()
            closed.wait(_pg.WAIT_S)  # the parent's end, open until the test closes it
            return ""

    watcher = _child.watch_parent(Pipe(), left.append)
    assert reading.wait(_pg.WAIT_S) and not left  # an open pipe holds it
    closed.set()  # the parent is done, or gone
    watcher.join(_pg.WAIT_S)
    assert left == [1]
