"""The order path's spans (E29-T04 #913 S4-G3; `20-architecture.md` Sec.12.3, 24 Sec.8.2).

A single order's submission is one trace: `http.request` on `placeOrder`, then `oms.submit` with
its children `oms.validate` (`OrderSubmission.submit`'s steps 1 to 8), `oms.persist` (step 9) and
`oms.send` (steps 10 and 11), each started at its first step, and the venue's create,
`exchange.place_order`, under `oms.send` across B1's invoke. A refusal at steps 1 to 8 ends after
`oms.validate`; a repeat answered at step 9 starts no `oms.send`. A span that ends in an exception
keeps its class alone, never its message (C-12.6). The pipeline runs over the real B1 facade,
command port and fake venue (`submit_rig`); the route over the runtime and its order lane
(`test_place_order_perf.serving`), the test's own loop's or `OrderLane`'s thread. Spans land in
an in-memory exporter; nothing is exported anywhere."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterator, Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Any
from uuid import uuid4

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from candleviewer.exchange.base.errors import OmsErrorCode, RateBudgetExceededError
from candleviewer.exchange.base.fakes import FakeReject, FakeTradingPort
from candleviewer.observability.tracing import span
from candleviewer.oms.errors import OmsError, TickSizeViolation
from candleviewer.oms.submit import OrderRequest
from candleviewer.oms_lane import OrderLane
from candleviewer.oms_wiring import OmsRuntime
from tests.unit.api.test_place_order_perf import RAW, serving
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr

_EXPORTER = InMemorySpanExporter()
_PROVIDER = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
#: A bound on each route test's waits, never a time the test expects.
BOUND_S = 10.0


@pytest.fixture(autouse=True)
def _traced(monkeypatch: pytest.MonkeyPatch) -> None:
    _EXPORTER.clear()
    monkeypatch.setattr(trace, "get_tracer", _PROVIDER.get_tracer)


@pytest.fixture(autouse=True)
def _native_stops(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """C-2.6 on every path here, as `test_order_exits_pg.py` asserts it: once a test ends, every
    create that a fake venue built during the test took carries its stop unless it is reduce-only,
    read off each venue double's own call records."""
    venues: list[FakeTradingPort] = []
    built = FakeTradingPort.__init__

    def kept(self: FakeTradingPort, *args: Any, **kwargs: Any) -> None:
        built(self, *args, **kwargs)
        venues.append(self)

    monkeypatch.setattr(FakeTradingPort, "__init__", kept)
    yield
    creates = [c.request for v in venues for c in v.calls if c.method == "place_order"]
    bare = [c.order_link_id for c in creates if not c.reduce_only and c.stop_loss is None]
    assert bare == [], "an entry reached the venue without its native stop (C-2.6)"


def _spans() -> dict[str, list[ReadableSpan]]:
    """The finished spans by name, each name's in the order they ended."""
    named: dict[str, list[ReadableSpan]] = {}
    for ended in _EXPORTER.get_finished_spans():
        named.setdefault(ended.name, []).append(ended)
    return named


def _under(child: ReadableSpan, parent: ReadableSpan) -> bool:
    """Whether `child` is `parent`'s child, in its trace."""
    up, at = child.parent, parent.context
    if up is None or at is None:
        return False
    return (up.trace_id, up.span_id) == (at.trace_id, at.span_id)


def _in_turn(spans: Sequence[ReadableSpan]) -> bool:
    """Whether each of `spans` ended before the next one started."""
    times = [(s.start_time or 0, s.end_time or 0) for s in spans]
    return all(ended <= started for (_, ended), (started, _) in pairwise(times))


async def test_a_submission_is_one_oms_submit_span_with_validate_persist_and_send_children() -> (
    None
):
    """One `oms.submit`, a root here (no route), whose three children each start at their first
    step and end before the next starts: one `oms.validate` (the facade's own, around B1's first
    persist, is gone), then `oms.persist`, then `oms.send`, none inside another. `oms.submit`
    carries the symbol, the environment, the `order_link_id` and its result; its children carry
    none of their own."""
    async with sr.rigged() as rig:
        outcome = await rig.submit()
        await rig.quiet()
    assert outcome.status == 202 and outcome.order_id is not None
    named = _spans()
    [submitted] = named["oms.submit"]
    children = [one for name in ("oms.validate", "oms.persist", "oms.send") for one in named[name]]
    assert [child.name for child in children] == ["oms.validate", "oms.persist", "oms.send"]
    assert all(_under(child, submitted) for child in children) and submitted.parent is None
    assert _in_turn(children)
    assert [dict(child.attributes or {}) for child in children] == [{}, {}, {}]
    link = rig.store._orders[outcome.order_id].order_link_id
    assert dict(submitted.attributes or {}) == {
        "symbol": sr.SYMBOL, "env": "demo", "order_link_id": link, "result": "accepted",
    }  # fmt: skip


async def test_the_venue_create_is_an_exchange_place_order_span_under_oms_send() -> None:
    """B1 sends the create from its own invoke, whose context was taken where its machine was
    built, inside `oms.persist`: the watch carries `oms.send`'s trace context, so the create's
    span is `oms.send`'s child. The create carries its native stop (C-2.6)."""
    async with sr.rigged() as rig:
        await rig.submit()
        await rig.quiet()
    named = _spans()
    [sent], [created] = named["oms.send"], named["exchange.place_order"]
    assert _under(created, sent)
    [create] = [call.request for call in rig.port.demo.calls if call.method == "place_order"]
    assert getattr(create, "stop_loss", None) == sr.STOP


async def test_a_resumed_create_starts_a_trace_of_its_own() -> None:
    """A create B1 resumes with no registration (a restart's, a rebuild's) has no request's trace
    context: its `exchange.place_order` is a root span, whatever span is current where B1's invoke
    runs."""
    rig = cr.build_rig()
    order = cr.new_order()
    await rig.stored(order)
    with span("oms.persist"):  # the context a resumed create's invoke may run in
        answer = await rig.port.place(cr.command("place", order))
    assert answer["ok"] is True
    [created] = _spans()["exchange.place_order"]
    assert created.parent is None


async def test_a_refusal_at_steps_1_to_8_ends_after_oms_validate_with_its_class_and_no_event() -> (
    None
):
    """A tick-size refusal (step 4): `oms.validate` ends in it, and neither `oms.persist` nor
    `oms.send` starts. `oms.submit` ends with the refusal's code as its result, and each span
    that ends in it is `ERROR` with its class alone, with no exception event (C-12.6)."""
    async with sr.rigged() as rig:
        with pytest.raises(TickSizeViolation):
            await rig.submit(sr.entry(price=Decimal("60000.05")))
    named = _spans()
    assert sorted(named) == ["oms.submit", "oms.validate"]
    [submitted], [validated] = named["oms.submit"], named["oms.validate"]
    assert _under(validated, submitted)
    assert dict(submitted.attributes or {}) == {
        "symbol": sr.SYMBOL, "env": "demo", "result": "tick_size_violation",
    }  # fmt: skip
    for ended in (submitted, validated):
        status = (ended.status.status_code, ended.status.description)
        assert status == (StatusCode.ERROR, "TickSizeViolation")
        assert list(ended.events) == []


def _rejected(rig: sr.SubmitRig) -> OrderRequest:
    rig.port.demo.script("place_order", FakeReject(OmsErrorCode.INSUFFICIENT_MARGIN, 110007))
    return sr.entry()


def _rate_refused(rig: sr.SubmitRig) -> OrderRequest:
    rig.port.demo.script("place_order", RateBudgetExceededError("no token", retry_after_s=1.5))
    return sr.entry()


def _unrecorded(rig: sr.SubmitRig) -> OrderRequest:
    rig.read_only.is_read_only = True  # refused at step 1, its record refused too (C-2.9)
    rig.port.audits.refuse = OSError("the audit lane is down")
    return sr.entry()


@pytest.mark.parametrize(
    ("arrange", "result"),
    [
        (_rejected, "exchange_error"),
        (_rate_refused, "exchange_rate_limited"),
        (_unrecorded, "audit_unavailable"),
    ],
    ids=["502", "429", "refusal_unrecorded"],
)
async def test_oms_submit_ends_with_the_code_its_request_is_answered(
    arrange: Callable[[sr.SubmitRig], OrderRequest], result: str
) -> None:
    """`oms.submit`'s `result` (20 Sec.12.3) is the answer's own code: a venue's rejection's 502
    `exchange_error`, a refused rate token's 429 `exchange_rate_limited`, and a refusal whose
    record does not land, `audit_unavailable` in its own code's place (C-2.9)."""
    async with sr.rigged() as rig:
        with contextlib.suppress(OmsError):  # the 503 that stands in for the refusal
            await rig.submit(arrange(rig))
        await rig.quiet()
    [submitted] = _spans()["oms.submit"]
    assert (submitted.attributes or {})["result"] == result


async def test_a_refusals_message_reaches_no_span() -> None:
    """Ruling Q3 (C-12.6): the refusal's detail and its rules' messages are on its problem, never
    on a span, its status or an event."""
    async with sr.rigged() as rig:
        with pytest.raises(TickSizeViolation) as refused:
            await rig.submit(sr.entry(price=Decimal("60000.05")))
    texts = [str(refused.value), *(error.message for error in refused.value.errors)]
    assert all(texts)
    spans = _EXPORTER.get_finished_spans()
    assert spans and not [t for t in texts for s in spans if t in s.to_json()]


async def test_a_repeat_answered_at_step_9_ends_oms_persist_and_starts_no_oms_send() -> None:
    """21 Sec.3.3.10: a held key's repeat is answered at step 9 by its decided outcome, nothing
    sent: `oms.persist` ends normally, and no `oms.send` or create span starts (20 Sec.12.3)."""
    async with sr.rigged() as rig:
        await rig.submit()
        await rig.quiet()
        _EXPORTER.clear()
        rig.port.demo.calls.clear()
        replayed = await rig.submit()
    assert replayed.replayed and rig.calls() == []
    named = _spans()
    assert sorted(named) == ["oms.persist", "oms.submit", "oms.validate"]
    [submitted], [persisted] = named["oms.submit"], named["oms.persist"]
    assert _under(persisted, submitted)
    assert persisted.status.status_code is StatusCode.UNSET
    assert (submitted.attributes or {})["result"] == "accepted"


async def _placed(client: httpx.AsyncClient, runtime: OmsRuntime) -> httpx.Response:
    """One `POST /orders` under a new key, then the facade's turns settled on its lane."""
    headers = {"content-type": "application/json", "idempotency-key": str(uuid4())}
    answer = await client.post("/orders", content=RAW, headers=headers)
    parts = runtime._composed()
    async with asyncio.timeout(BOUND_S):
        for _ in range(4):
            for _ in range(32):
                await asyncio.sleep(0)
            await parts.lane.call(parts.machines.idle())
    return answer


async def test_place_order_is_one_http_request_span_over_the_submission() -> None:
    """The route is one `http.request` span with its method, route and status code, and the
    submission's `oms.submit` is its child (20 Sec.12.3)."""
    async with serving() as (client, runtime):
        answer = await _placed(client, runtime)
    assert answer.status_code == 202, answer.text
    named = _spans()
    [request], [submitted] = named["http.request"], named["oms.submit"]
    assert request.parent is None and _under(submitted, request)
    assert dict(request.attributes or {}) == {
        "http.method": "POST", "http.route": "/orders", "http.status_code": 202,
    }  # fmt: skip


async def test_the_route_span_parents_the_submission_across_the_order_lane() -> None:
    """On `OrderLane`'s own thread and loop (29 CV-C13): the hop carries the route's context, so
    `oms.submit` is `http.request`'s child, and the create B1 sends there is `oms.send`'s."""
    async with serving(lane=OrderLane) as (client, runtime):
        assert isinstance(runtime._composed().lane, OrderLane)
        answer = await _placed(client, runtime)
    assert answer.status_code == 202, answer.text
    named = _spans()
    [request], [submitted] = named["http.request"], named["oms.submit"]
    [sent], [created] = named["oms.send"], named["exchange.place_order"]
    assert _under(submitted, request) and _under(created, sent)
