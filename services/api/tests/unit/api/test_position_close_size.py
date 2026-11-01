"""`POST /positions/{positionId}/close` (`closePosition`), its size as E29-S03 (#978) resolves it,
on the doubles of `position_writes_world`: step 13's size and its refusals (BQ-2 to BQ-4), the
`position.closed` fields (BQ-9), `oms_partial_close_total` (20 Sec.12.1), the venue read's refusal
answered 422 and a rejected close's re-read (BQ-7), and the hedge index from the stored row
(BQ-6), as the orchestrator ruled them. Each test names the scenario or the ruling it proves; the
RBAC and IDOR cases are `test_position_close_route.py`'s, re-run with these. No network
(C-13.5)."""

from __future__ import annotations

import ast
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest
from prometheus_client import generate_latest

import candleviewer
from candleviewer.api.position_close import CLOSE_PATH, partial_result, size_detail
from candleviewer.oms.errors import (
    FieldError,
    OmsError,
    OmsNotReady,
    OrderInvalid,
    PositionChanged,
    StoreUnavailable,
)
from candleviewer.oms.idempotency import Replay
from candleviewer.oms.position_writes import CLOSE_ACTION, CloseSize, CloseTerms
from candleviewer.oms.submit import SubmitOutcome
from tests.unit.api.position_writes_world import FLAT, HEDGED, ON_A, World, first_close, on, post
from tests.unit.api.test_position_close_route import anchor
from tests.unit.oms.submit_rig import instrument

HALF: dict[str, Any] = {"order_type": "market", "pct": "50"}
FULL: dict[str, Any] = {"order_type": "market", "pct": "100"}
_DUST = (
    "The close would leave less than the smallest size that can be closed; "
    "close the whole position instead."
)


async def close(world: World, body: Any, position: str = ON_A, **kw: Any) -> Any:
    return await post(world, on(CLOSE_PATH, position), body=body, **kw)


def counted(world: World) -> dict[str, float]:
    """`oms_partial_close_total` by result, read off the world's registry."""
    text = generate_latest(world.metrics.registry).decode()
    pattern = r'^oms_partial_close_total\{[^}]*result="(\w+)"[^}]*\} (\S+)$'
    return {result: float(n) for result, n in re.findall(pattern, text, re.MULTILINE)}


def closes(world: World) -> list[tuple[str, str]]:
    return [(r.outcome, r.reason) for r, _ in world.records.written if r.action == CLOSE_ACTION]


def minimum(world: World, value: str) -> None:
    """BTCUSDT's `min_order_qty` as step 13 reads it (its `qty_step` stays 0.001)."""
    world.positions.listed["BTCUSDT"] = instrument(min_order_qty=Decimal(value))


# --- the size (BQ-2), its record (BQ-9) and its count (BQ-12) ------------------------------------


async def test_scenario_percentage_close_sends_the_resolved_size_and_records_it() -> None:
    """0.200 x 50 % is 0.100, sent as the close's `fixed_qty`; the record holds what was asked,
    the size sent, the size left and whether the floor changed it."""
    world = World()
    answer = await close(world, HALF)
    assert answer.status_code == 202, answer.text
    [request] = world.submitted()
    assert (request.sizing.mode, request.sizing.qty) == ("fixed_qty", Decimal("0.100"))
    [record] = world.positions.records
    assert {k: record.detail.get(k) for k in ("requested_pct", "requested_qty", "resolved_qty",
                                             "remaining_qty", "rounded", "full")} == {
        "requested_pct": "50", "requested_qty": None, "resolved_qty": "0.100",
        "remaining_qty": "0.100", "rounded": "false", "full": "false",
    }  # fmt: skip
    assert counted(world) == {"accepted": 1.0}


async def test_close_position_a_qty_close_is_floored_to_the_lot_step_and_says_so() -> None:
    world = World()
    answer = await close(world, {"order_type": "market", "qty": "0.1005"})
    assert answer.status_code == 202, answer.text
    assert world.submitted()[0].sizing.qty == Decimal("0.100")
    [record] = world.positions.records
    assert (record.detail["requested_qty"], record.detail["resolved_qty"],
            record.detail["rounded"]) == ("0.1005", "0.100", "true")  # fmt: skip


async def test_close_position_a_full_close_is_never_refused_for_its_size_nor_counted() -> None:
    """BQ-4 as ruled: the whole size is sent even under the instrument's minimum; only a close
    below 100 % is counted."""
    world = World()
    minimum(world, "1")
    answer = await close(world, FULL)
    assert answer.status_code == 202, answer.text
    assert world.submitted()[0].sizing.qty == Decimal("0.200")
    assert counted(world) == {}


async def test_close_position_the_hedge_index_comes_from_the_stored_row_alone() -> None:
    """BQ-6: the body names no index; the short on index 2 is closed by a buy on index 2."""
    world = World()
    assert (await close(world, HALF, HEDGED)).status_code == 202
    [request] = world.submitted()
    assert (request.position_idx, request.side, request.sizing.qty) == (2, "buy", Decimal("0.100"))


# --- step 13's refusals (BQ-3, BQ-4), recorded, nothing sent -----------------------------------


async def test_scenario_rounding_leaves_dust_422_with_the_remainder_nothing_sent() -> None:
    """Closing 75 % of 0.200 leaves 0.050, under a minimum of 0.150: refused before any exchange
    call with the remainder named, so a client offers the full close."""
    world = World()
    minimum(world, "0.150")
    answer = await close(world, {"order_type": "market", "pct": "75"})
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert answer.json()["errors"] == [{
        "field": "pct", "rule": "dust_remainder", "message": _DUST, "symbol": "BTCUSDT",
        "limit": "0.150", "resolved": "0.150", "remaining": "0.050",
    }]  # fmt: skip
    assert closes(world) == [("denied", "validation_failed")] and world.submitted() == []
    assert counted(world) == {"dust_remainder": 1.0}


async def test_close_position_bq5_a_remainder_under_the_floor_is_dust_until_e29_k01() -> None:
    """BQ-5 as ruled: SR-E22-03's `MIN_SIZE_FLOOR`, read per symbol, holds the dust check until
    E29-K01 confirms the venue fact: 75 % of 0.200 leaves 0.050, above the minimum of 0.001 but
    under a floor of 0.060, so it is refused with that floor as its limit, nothing sent."""
    world = World(floor=lambda symbol: Decimal("0.060") if symbol == "BTCUSDT" else None)
    answer = await close(world, {"order_type": "market", "pct": "75"})
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    [error] = answer.json()["errors"]
    assert (error["rule"], error["limit"], error["resolved"], error["remaining"]) == (
        "dust_remainder",
        "0.060",
        "0.150",
        "0.050",
    )
    assert world.submitted() == [] and counted(world) == {"dust_remainder": 1.0}


async def test_close_position_a_symbol_the_floor_does_not_list_keeps_the_minimum_alone() -> None:
    world = World(floor=lambda symbol: None)
    assert (await close(world, {"order_type": "market", "pct": "75"})).status_code == 202
    assert world.submitted()[0].sizing.qty == Decimal("0.150")


async def test_close_position_bq5_a_floor_that_cannot_be_read_is_left_out_never_refusing() -> None:
    """The floor is advisory (C-2.6): one that fails leaves the close held to `min_order_qty`
    alone, so the 75 % close the floor of 0.060 would refuse is sent, never refused for it."""

    def unread(symbol: str) -> Decimal | None:
        raise RuntimeError("no reference price")

    world = World(floor=unread)
    assert (await close(world, {"order_type": "market", "pct": "75"})).status_code == 202
    assert world.submitted()[0].sizing.qty == Decimal("0.150")
    assert counted(world) == {"accepted": 1.0}


def test_create_app_hands_the_close_route_the_apps_own_sr_e22_03_floor() -> None:
    """BQ-5: the close route's dust floor is the app's SR-E22-03 helper, the one the trades
    topic and `/market/trades` read, never a second copy of the rule."""
    source = (Path(candleviewer.__file__).parent / "app.py").read_text(encoding="utf-8")
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None)
        == "make_position_close_router"
    ]  # fmt: skip
    [call] = calls
    [floor] = [kw.value for kw in call.keywords if kw.arg == "min_size_floor"]
    assert ast.unparse(floor) == "functools.partial(_catalogue_min_size_floor, ctx)"


async def test_close_position_a_size_under_the_minimum_is_422_qty_below_minimum() -> None:
    world = World()
    answer = await close(world, {"order_type": "market", "pct": "0.4"})
    assert answer.status_code == 422
    [error] = answer.json()["errors"]
    assert (error["rule"], error["resolved"], error["limit"]) == ("qty_below_minimum", "0.000",
                                                                  "0.001")  # fmt: skip
    assert "remaining" not in error and world.submitted() == []
    assert counted(world) == {"qty_below_minimum": 1.0}


async def test_close_position_a_partial_close_of_a_flat_row_counts_as_the_position_changed() -> (
    None
):
    world = World()
    answer = await close(world, HALF, FLAT)
    assert answer.json()["errors"][0]["rule"] == "position_flat"
    assert counted(world) == {"position_changed": 1.0}


@pytest.mark.parametrize(
    ("error", "status", "recorded"),
    [(StoreUnavailable(), 503, [("denied", "store_unavailable")]), (OmsNotReady(), 503, [])],
    ids=["unread", "no_catalogue_yet"],
)
async def test_close_position_an_instrument_step_13_cannot_read_sends_nothing(
    error: OmsError, status: int, recorded: list[tuple[str, str]]
) -> None:
    world = World()
    world.positions.instrument_error = error
    answer = await close(world, HALF)
    assert answer.status_code == status
    assert closes(world) == recorded and world.submitted() == []
    assert counted(world) == {"rejected": 1.0}


# --- the venue's read and the venue's answer (BQ-7) ---------------------------------------------


async def test_scenario_never_reverses_the_venue_read_refusal_is_422_unswept_uncached() -> None:
    """The pipeline's read of the venue showed the position smaller than the close: answered as
    step 13's own refusal, its record the pipeline's, nothing kept or swept."""
    world = World()
    shrunk = FieldError("qty", "exceeds_position", "The position is now smaller than the close.")
    world.pipeline.close = PositionChanged(shrunk.message, errors=(shrunk,))
    answer = await close(world, HALF)
    assert (answer.status_code, answer.json()["errors"][0]["rule"]) == (422, "exceeds_position")
    assert world.positions.sweeps == [] and len(world.cache) == 0
    assert world.positions.refreshes == [] and counted(world) == {"position_changed": 1.0}


async def test_close_position_a_rejected_close_re_reads_its_position_before_the_502() -> None:
    world = World()
    world.pipeline.close = SubmitOutcome(502, uuid.uuid4(), uuid.uuid4(), code="exchange_error",
                                         ret_code=110017)  # fmt: skip
    answer = await close(world, HALF)
    assert (answer.status_code, answer.json()["exchange"]) == (502, {"ret_code": 110017})
    assert world.positions.refreshes == [uuid.UUID(ON_A)]
    assert counted(world) == {"rejected": 1.0}


async def test_close_position_a_failed_re_read_leaves_the_502_standing() -> None:
    world = World()
    world.pipeline.close = SubmitOutcome(502, uuid.uuid4(), uuid.uuid4(), code="exchange_error",
                                         ret_code=110017)  # fmt: skip
    world.positions.refresh_error = OmsNotReady()
    assert (await close(world, HALF)).status_code == 502


@pytest.mark.parametrize("status", [429, "replayed_502"])
async def test_close_position_only_a_first_502_re_reads_the_position(status: Any) -> None:
    world, key = World(), uuid.uuid4()
    if status == 429:
        world.pipeline.close = SubmitOutcome(
            429, uuid.uuid4(), uuid.uuid4(), code="exchange_rate_limited", retry_after_s=1
        )
    else:  # a repeat of a recorded 502 sends and reads nothing
        first = first_close()
        world.anchors.answers[("closePosition", key)] = Replay(anchor(first, 502))
        world.pipeline.replays[first.anchor_id] = SubmitOutcome(
            502, first.anchor_id, first.order_id, code="exchange_error", ret_code=110017,
            replayed=True,
        )  # fmt: skip
    await close(world, HALF, key=key)
    assert world.positions.refreshes == []


@pytest.mark.parametrize("status", [429, 502])
async def test_close_position_a_repeat_the_pipeline_answers_is_never_counted(
    status: Literal[429, 502],
) -> None:
    """20 Sec.12.1: a repeat answered from the anchor is not counted, the pipeline's own answer
    to a concurrent repeat (`replayed`) included, and it re-reads nothing."""
    world = World()
    code = {429: "exchange_rate_limited", 502: "exchange_error"}[status]
    world.pipeline.close = SubmitOutcome(status, uuid.uuid4(), uuid.uuid4(), code=code,
                                         replayed=True)  # fmt: skip
    assert (await close(world, HALF)).status_code == status
    assert counted(world) == {} and world.positions.refreshes == []


# --- the helpers ------------------------------------------------------------------------------


def test_size_detail_names_the_body_asked_by_qty_and_whether_it_rounded() -> None:
    size = CloseSize(Decimal("0.1005"), Decimal("0.100"), Decimal("0.100"), False)
    assert size_detail(CloseTerms("market", qty=Decimal("0.1005")), size) == {
        "requested_qty": "0.1005", "resolved_qty": "0.100", "remaining_qty": "0.100",
        "rounded": "true",
    }  # fmt: skip


@pytest.mark.parametrize(
    ("rule", "status", "result"),
    [("dust_remainder", 422, "dust_remainder"), ("qty_below_minimum", 422, "qty_below_minimum"),
     ("exceeds_position", 422, "position_changed"), ("listed", 422, "rejected"),
     ("dust_remainder", 503, "rejected")],
)  # fmt: skip
def test_partial_result_maps_a_step_13_rule_else_rejected(
    rule: str, status: int, result: str
) -> None:
    refused = OrderInvalid(errors=(FieldError("pct", rule, "x"),))
    assert partial_result(refused, status) == result
    assert partial_result(StoreUnavailable(), 503) == "rejected"
