"""`closePosition` and `closeAllPositions` (E29-T07 #915; E29-S03 #978): the replay and
close-all edges the routes keep, on the doubles of `position_writes_world`. A repeat whose rows
cannot be read, a concurrent repeat the pipeline answers, and close-all's principal, body, cancel,
scope and record edges: each answers as 22 says and sends nothing it should not. No network
(C-13.5)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from candleviewer.api.position_close import CLOSE_ALL_PATH, CLOSE_PATH
from candleviewer.oms.errors import OmsNotReady, StoreUnavailable
from candleviewer.oms.idempotency import Replay
from tests.unit.api import test_order_acceptance as acc
from tests.unit.api.oms_reads_world import MISSING
from tests.unit.api.position_writes_world import ON_A, World, first_close, on, post
from tests.unit.api.test_position_close_route import anchor

FULL: dict[str, Any] = {"order_type": "market", "pct": "100"}


async def close(world: World, **kw: Any) -> Any:
    return await post(world, on(CLOSE_PATH, ON_A), body=FULL, **kw)


async def flatten(world: World, body: Any = None, **kw: Any) -> Any:
    return await post(world, CLOSE_ALL_PATH, body={} if body is None else body, **kw)


# --- closePosition: a repeat's rows -----------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "code"),
    [(RuntimeError("down"), "store_unavailable"), (OmsNotReady(), "oms_not_ready")],
    ids=["store_down", "lane_stopped"],
)
async def test_close_position_a_repeat_whose_rows_cannot_be_read_sends_nothing(
    error: Exception, code: str
) -> None:
    """21 Sec.3.3.10: a repeat answered from its anchor reads its rows as they stand now; a read
    that fails is 503, never a second close."""
    world, key, first = World(), uuid.uuid4(), first_close()
    world.route.orders.error = error
    world.anchors.answers[("closePosition", key)] = Replay(anchor(first))
    world.pipeline.replays[first.anchor_id] = acc.replay_of(first)
    answer = await close(world, key=key)
    assert (answer.status_code, answer.json()["code"]) == (503, code)
    assert world.submitted() == []


async def test_close_position_a_concurrent_repeat_the_pipeline_answers_reads_its_rows() -> None:
    """The persist met the key held by a concurrent first request: the pipeline answers it as a
    repeat, and the route renders the rows as read now, replayed, keeping nothing of its own."""
    world, first = World(), first_close()
    assert first.written is not None
    row = acc.stored(first.written.order, lifecycle_state="submitted", state="submitted")
    world.route.orders.rows[row.id] = row
    world.pipeline.close = acc.replay_of(first)
    answer = await close(world)
    assert answer.status_code == 202 and answer.headers["idempotency-replayed"] == "true"
    assert world.positions.records == [] and len(world.cache) == 0


async def test_close_position_a_concurrent_repeat_whose_rows_cannot_be_read_is_503() -> None:
    world, first = World(), first_close()
    world.route.orders.error = RuntimeError("down")
    world.pipeline.close = acc.replay_of(first)
    answer = await close(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")


# --- closeAllPositions: the edges before and around the closes -------------------------------


@pytest.mark.parametrize(
    ("principals", "status", "code"),
    [("none", 501, "not_implemented"), ("fail", 503, "store_unavailable")],
)
async def test_close_all_with_no_principal_source_or_its_store_down_sends_nothing(
    principals: str, status: int, code: str
) -> None:
    world = World(principals=principals)
    answer = await flatten(world)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.submitted() == []


async def test_close_all_an_unknown_bearer_is_401_unauthenticated() -> None:
    world = World()
    answer = await flatten(world, who="nobody")
    assert (answer.status_code, answer.json()["code"]) == (401, "unauthenticated")


async def test_close_all_a_body_past_its_cap_is_422_body_too_large() -> None:
    world = World()
    answer = await flatten(world, {"exchange_account_ids": ["x" * 20_000]})
    assert answer.status_code == 422
    assert answer.json()["errors"][0]["rule"] == "body_too_large" and world.submitted() == []


async def test_close_all_a_failing_cancel_never_holds_the_closes_back() -> None:
    """C-2.6: flattening never waits on its cancel; the closes still go, whole."""
    world = World()
    world.cancel_all.error = StoreUnavailable()
    answer = await flatten(world)
    assert answer.status_code == 200 and answer.json()["succeeded"] == 1
    assert len(world.submitted()) == 2


async def test_close_all_a_scope_read_on_a_stopped_lane_is_503_not_ready() -> None:
    world = World()

    async def stopped(scope: Any, request: Any) -> Any:
        raise OmsNotReady

    world.cancel_all.scope = stopped  # type: ignore[method-assign]  # the order lane has stopped
    answer = await flatten(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert world.submitted() == []


@pytest.mark.parametrize(
    ("who", "body", "code"),
    [("manager", {"exchange_account_ids": [str(MISSING)]}, "account_scope_denied"),
     ("viewer", {}, "forbidden")],
)  # fmt: skip
async def test_close_all_a_refusal_whose_record_cannot_be_written_still_answers_403(
    who: str, body: Any, code: str
) -> None:
    """The 403 of RBAC or of the scope stands when its `rbac.denied` record cannot be written,
    logged, as `testApiKey`'s does; nothing is sent."""
    world = World()
    world.audit.fail = True
    answer = await flatten(world, body, who=who)
    assert (answer.status_code, answer.json()["code"]) == (403, code)
    assert world.submitted() == []
