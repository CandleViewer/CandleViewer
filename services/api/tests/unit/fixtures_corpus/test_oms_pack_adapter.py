"""The OMS scenario pack replayed through the adapter's parsers and port (E29-Q01, #844, BQ-6).

The ticket's determinism criterion at the parse level: every private frame a scenario delivers and
every REST body it stubs is read by the adapter's parsers from two separate loads, and the two reads
agree. A scenario that is no abuse case is read whole: no frame rejected, no body refused but the
one documented. The same OMS state from the same replay is E29-Q02's conformance test. No network.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import AccountRef
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.exchange.bybit.mapping import map_ret_code
from tests._oms_fixtures import RestReply, load, scenario_names
from tests.unit.exchange.bybit._trading import Venue, link, make_port

#: The account the pack's `OUR_ID` links name: the fixture ids of `tests/unit/oms/stream_world.py`.
ACCOUNT_ID = AccountId(UUID("a1000000-0000-4000-8000-000000000001"))
ACCOUNT = AccountRef(
    account_id=ACCOUNT_ID,
    uid=str(ACCOUNT_ID.int % 10**15),
    environment="demo",
    key_ref=str(ACCOUNT_ID),
)
NOW_US: TsUs = 1_746_270_400_000_000
ABUSE = {"hostile_pushes", "credential_shaped_inputs"}  # the adapter may refuse these
#: The documented position example is an inverse row, which the linear page refuses.
REFUSED = {"rest_position_list": ["UnknownStateError"]}
PAGES: dict[str, type[BaseModel]] = {
    "GET /v5/order/realtime": tp.OrderPage,
    "GET /v5/order/history": tp.OrderPage,
    "GET /v5/execution/list": tp.ExecutionPage,
    "GET /v5/position/list": tp.PositionPage,
    "POST /v5/order/create": tp.OrderReply,
}


def read_frame(frame: str) -> tuple[str, ...]:
    """What the adapter makes of one stream frame: a reply, its events, or why it refused it."""
    try:
        parsed = pp.classify(frame)
        if isinstance(parsed, pp.Reply):
            return ("reply", parsed.op, str(parsed.granted))
        events = pp.read_push(parsed, ACCOUNT, now_us=NOW_US)
    except (pp.FrameRejected, ExchangeError, ValueError) as error:
        return ("refused", type(error).__name__, str(error))
    return ("events", *(event.model_dump_json() for event in events))


def read_body(call: str, body: dict[str, Any]) -> tuple[str, ...]:
    """What the adapter makes of one stubbed reply: its error class, its page or its refusal."""
    if body.get("retCode", 0) != 0:
        error = map_ret_code(body["retCode"], body["retMsg"], create=call.endswith("/create"))
        return ("error", type(error).__name__, str(getattr(error, "filter_name", None)), str(error))
    if call not in PAGES or "result" not in body:
        return ("body", json.dumps(body, sort_keys=True))
    try:
        return ("page", tp.parse(PAGES[call], body["result"], "pack").model_dump_json())
    except ExchangeError as error:
        return ("refused", type(error).__name__)


def replay(frames: tuple[str, ...], replies: Mapping[str, RestReply]) -> list[tuple[str, ...]]:
    return [read_frame(f) for f in frames] + [read_body(c, r.body) for c, r in replies.items()]


@pytest.mark.parametrize("name", scenario_names())
def test_a_scenario_read_through_the_adapter_twice_reads_the_same(name: str) -> None:
    one, two = load(name), load(name)
    assert replay(one.delivered_frames(), one.replies) == replay(
        two.delivered_frames(), two.replies
    )


@pytest.mark.parametrize("name", [n for n in scenario_names() if n not in ABUSE])
def test_a_scenario_that_is_no_abuse_case_is_read_whole(name: str) -> None:
    scenario = load(name)
    reads = replay(scenario.delivered_frames(), scenario.replies)
    assert [r[1] for r in reads if r[0] == "refused"] == REFUSED.get(name, [])
    assert all(len(r) > 1 for r in reads)  # a push the adapter reads gives at least one event


def test_a_bundled_push_is_read_as_one_event_a_row() -> None:
    reads = [read_frame(f) for f in load("ws_partial_fill").delivered_frames()]
    assert [len(r) - 1 for r in reads] == [1, 1, 1, 3, 1]  # five frames, seven rows


def test_the_adapter_refuses_only_the_fee_rate_frame_of_the_hostile_pushes() -> None:
    """Delivered frames 9 and 10 (the duplicate shifts the later ones): the fee rate no column
    holds is rejected, and the control-character exec id is read, for the OMS to refuse."""
    reads = [read_frame(f) for f in load("hostile_pushes").delivered_frames()]
    assert [(i, r[2]) for i, r in enumerate(reads) if r[0] == "refused"] == [
        (9, "private frame rejected: malformed")
    ]
    assert "\\u0007" in reads[10][1]


def test_a_rendered_template_read_through_the_adapter_twice_reads_the_same() -> None:
    """Compared as digests: a failing run prints no generated value."""
    scenario = load("credential_shaped_inputs")

    def digest(seed: str) -> str:
        rendered = scenario.render(seed)
        return hashlib.sha256(repr(replay(rendered.frames, rendered.replies)).encode()).hexdigest()

    assert digest("seed-one") == digest("seed-one")
    assert digest("seed-one") != digest("seed-two")  # the seed does reach what the adapter reads


@pytest.mark.parametrize("name", scenario_names())
def test_a_derived_read_page_leaves_no_cursor_for_the_port_to_follow(name: str) -> None:
    """A stub answers every call alike: a cursor left in a derived page would repeat in the walk."""
    own = {c: r.body for c, r in load(name).replies.items() if c in PAGES and "/" not in r.payload}
    assert [c for c, body in own.items() if body.get("result", {}).get("nextPageCursor")] == []


async def test_the_squatted_id_lookups_end_in_one_request_each_and_find_the_foreign_order() -> None:
    """Served as the README says, the AC-11 stubs end the port's paged reads on their first page."""
    venue = Venue()
    for call, reply in load("squatted_link_id").replies.items():
        venue.on(call.split(" ")[1], reply.body, status=reply.status)
    port, child = make_port(venue), link(ACCOUNT_ID, seq=6)
    [found] = await port.order_history(ACCOUNT, order_link_id=child)
    assert (found.order_link_id, found.side, found.state) == (child, "sell", "filled")
    assert await port.open_orders(ACCOUNT, order_link_id=child) == []
    assert venue.paths() == ["/v5/order/history", "/v5/order/realtime"]
