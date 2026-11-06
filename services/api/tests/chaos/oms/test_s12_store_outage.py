"""C-13.6 #10, the VALIDATE commit (E29-Q04 #1148; E29-T04's pipeline step 9 and S7; the ruling's
BQ-4: an outage of the one node): the storage tier refuses the commit of the submit's first
persist, B1's `VALIDATE`, as the refusal's logs name it (the `commit` door: the submit's first
commit). The request is refused `503 store_unavailable` before any send: nothing recorded, the
venue's create count 0, its key unspent (no anchor kept). Once the tier is back, the same
request under the same key is accepted and sent once, and the oracle finds the book equal to
the venue. On virtual time, the venue derived in-test: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

from candleviewer.oms.errors import StoreUnavailable, problem_for
from candleviewer.storage.errors import StorageTierUnavailable
from tests.chaos.oms._oracle import check
from tests.chaos.oms._world import opened
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos

KEY = 0x512  # the request's client key, which its retry repeats


@virtual
async def test_s12_an_outage_at_the_validate_commit_sends_nothing_and_the_retry_goes_once() -> None:
    async with opened() as world:
        world.door("commit", StorageTierUnavailable("the connection was refused at the commit"))
        with capture_logs() as logs, pytest.raises(StoreUnavailable) as refused:
            await world.submit(key=KEY)
        problem = problem_for(refused.value)
        assert (problem.status, problem.code) == (503, "store_unavailable")
        failed = [e["ev"] for e in logs if e["event"] == "statechart_transition_failed"]
        steps = [e["step"] for e in logs if e["event"] == "oms_submit_refused"]
        assert (failed, steps) == (["VALIDATE"], ["persist"])  # the commit the door met
        assert world.exchange.creates() == {}  # nothing sent
        assert (await world.book()).orders == ()  # nothing recorded
        assert world.store._anchors == {}  # its key unspent
        outcome = await world.submit(key=KEY)  # the tier is back: the same request again
        assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
        link = (await world.row(outcome.order_id)).order_link_id
        assert world.exchange.creates() == {link: 1}
        await check(world)
