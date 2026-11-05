"""C-13.6 #12 and #7 (E29-Q04 #1148; E29-T04's startup sweep, 20 Sec.6.2 and 24 Sec.8.3 rules 3
and 6, SR-E29-15; E29-T06's startup pass, 24 Sec.8.5; the ruling's BQ-3 (a)): an OMS process on
Postgres killed with SIGKILL mid-submission (`_child`), the venue handed to the process after it.
The dead process's session ends, and its environment lock with it (`_pg.freed`); the next process
takes the lock, waits out the fencing grace, sweeps and runs the account's startup pass:

- `door`: a restart finds the order `submitting`, its create at the venue's door when the process
  went down, nothing at the venue: the create is looked up first, then sent once under its own id
  with its native stop (C-2.10, C-2.6);
- `taken`: a restart finds an order `submitting` whose create the venue already holds (the process
  went down after the send): it is looked up and bound by the full match (`adopted_after_lookup`),
  nothing sent again;
- `filled`: the order acknowledged, then part filled at the venue while the account had no
  stream: the startup pass applies the fill to the bound row and lists the correction.

The venue counted one create per id across both processes, and the oracle finds the book, read
from Postgres, equal to the venue, C-2.6 among it. Recovery is wall time: ready within 30 s of the
restart and the startup pass within a cycle of that (`_pg.running`, as `test_startup_sweep_pg`
bounds it), printed (`-rA`). Were the resumed create's lookup skipped, the re-send would meet the
venue's refusal of the reused id and the lookup after it would bind the one order, but the venue
would count two creates, which the oracle fails (the negative control). Markers `chaos`,
`integration` and `nightly` (`_pg`); the venue derived in-test: derived, not evidence (E29-K01,
#843)."""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms import commands
from tests.chaos.oms import _pg
from tests.chaos.oms._child import PART, killed
from tests.chaos.oms._oracle import OracleMismatch, check
from tests.chaos.oms.test_teeth import resent, unfound
from tests.integration.oms.test_submission_pipeline_pg import _order, _orders
from tests.unit.oms.submit_rig import STOP

pytestmark = [pytest.mark.chaos, pytest.mark.integration, pytest.mark.nightly]
node = _pg.node  # the module's Postgres 16; each test clones its database at head

#: What a restart finds at each point: the order's state, and its creates at the venue.
LEFT = {"door": ("submitting", 0), "taken": ("submitting", 1), "filled": ("submitted", 1)}
#: The order's state once the restart has recovered it.
RECOVERED = {"door": "submitted", "taken": "submitted", "filled": "partially_filled"}


@asynccontextmanager
async def restarted(
    node: _pg.Node, host: Path, point: str
) -> AsyncIterator[tuple[_pg.PgWorld, UUID, str]]:
    """The process killed at `point`, its order's row as the kill left it (nothing of a fill
    recorded), its lock freed with its session, then the next process over the same database and
    the venue it left: that process, the order's id and its `order_link_id`."""
    db = _pg.fresh(node)
    handed = await killed(db, host, point)
    [(order_id, link, state)] = _orders(db.su, db.account)
    left = (state, Counter(handed["creates"])[link], _order(db.su, order_id).cum_exec_qty)
    assert left == (*LEFT[point], Decimal(0))
    await _pg.freed(db)
    port = _pg.HostPort(db.ref)
    async with _pg.running(db, host, _pg.Host(held=port), before=port.take(handed)) as world:
        yield world, order_id, link


@pytest.mark.parametrize("point", ["door", "taken", "filled"])
async def test_s14_a_process_killed_mid_submission_is_recovered_by_the_next_ones_start(
    node: _pg.Node, tmp_path: Path, point: str
) -> None:
    async with restarted(node, tmp_path, point) as (world, order_id, link):
        assert await world.settled(order_id, leaving=LEFT[point][0]) == RECOVERED[point]
        startup = world.reports()[0]
        assert startup["trigger"] == "startup"
        print(
            f"s14 ({point}): ready {world.ready_s:.1f} s after the restart, its startup pass "
            f"reported at {world.passed_s:.1f} s, wall time"
        )  # -rA shows it
        calls = world.port.calls
        methods = [call.method for call in calls]
        if point == "door":  # looked up first, then sent once with its native stop
            sent = methods.index("place_order")
            assert {"open_orders", "order_history"} & set(methods[:sent])
            [create] = [call.request for call in calls if call.method == "place_order"]
            assert isinstance(create, PlaceOrderRequest)
            assert (create.order_link_id, create.stop_loss) == (link, STOP)
        elif point == "taken":  # bound, never sent again
            assert "place_order" not in methods
            assert ("orders.submit", "adopted_after_lookup") in world.writer.actions
        else:  # the gap's fill applied by the startup pass, the position under its stop
            assert startup["corrected"] == [link]
            book = await world.book()
            [row], [position] = book.orders, book.positions
            assert (row.cum_exec_qty, position.size, position.stop_loss) == (PART, PART, STOP)
        assert world.creates() == {link: 1}  # one create per id, across both processes
        await check(world)


async def test_s14_without_the_resumed_creates_lookup_the_venue_counts_two_creates(
    node: _pg.Node, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "find_by_link_id", unfound)  # the process after the kill's
    monkeypatch.setattr(commands, "adopt_or_resend", resent)
    async with restarted(node, tmp_path, "taken") as (world, order_id, link):
        # the venue refused the reused id; the lookup after it bound the one order
        assert await world.settled(order_id, leaving="submitting") == "submitted"
        with pytest.raises(OracleMismatch) as raised:
            await check(world)
        assert {(d.item, d.field, d.venue) for d in raised.value.diffs} == {
            (f"order {link}", "creates", 2)
        }
