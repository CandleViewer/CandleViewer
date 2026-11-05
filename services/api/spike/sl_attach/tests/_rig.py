"""The offline rig: the real port and private stream over #843's corpus venue (plus `trading-stop`
in the corpus's reply shape; S2 moves it), on a virtual clock, behind `Tap` and `SlGuardedPort`.
No network (the session guard in `conftest.py`)."""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef, PlaceOrderRequest
from candleviewer.exchange.base.reconnect import ConnectionBudget, ReconnectPolicy
from candleviewer.exchange.bybit.private_stream import PrivateStreams
from candleviewer.exchange.bybit.trading import BybitTradingPort
from spike.oms_demo_path.harness import Links
from spike.oms_demo_path.ledger import IntentLedger
from spike.oms_demo_path.measure import ClockOffset
from spike.oms_demo_path.offline import Corpus, CorpusVenue, VenueOrder, default_corpus, patched
from spike.oms_demo_path.safety import QtyLimits, digest
from spike.oms_demo_path.scrub import Scrubber
from spike.sl_attach.arms import ArmRunner, Clock, SlGuardedPort, Tap, Watch
from spike.sl_attach.config import ArmConfig
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._trading import RecordingGovernor

SIGNER = "fixture-signer-id"
CORPUS = Corpus(default_corpus())


class StopVenue(CorpusVenue):
    """The corpus venue with `POST /v5/position/trading-stop`: the position's stop becomes the
    written one and a position push follows; `stop_answers` scripts refusals (corpus error
    shapes, values patched), served first, one per write. `create_answers` answers a create
    before the venue acts on it, `create_after` after it has (an open outcome that filled),
    `create_late` before it acts, which it then does `Rig.late_s` later (`held_back`: a late
    fill; with `Rig.rest_s`, the order rests `New` that long before it fills);
    `close_answers` answers a reduce-only close unacted, `close_unfilled` acks one unfilled;
    `position_answers` answers position reads first, one per read (`None`: as the venue).
    `Rig.fill_late_s`: an opener acked `ok` rests, then `Rig.late` (fill, cancel, or partial:
    one step filled, the rest cancelled) that late."""

    def __init__(self, corpus: Corpus, **options: Any) -> None:
        super().__init__(corpus, **options)
        self.stop_writes: list[dict[str, Any]] = []
        self.stop_answers: list[dict[str, Any]] = []
        self.create_answers: list[dict[str, Any]] = []
        self.create_after: list[dict[str, Any]] = []
        self.close_answers: list[dict[str, Any]] = []
        self.close_unfilled = False
        self.create_late: list[dict[str, Any]] = []
        self.held_back: list[dict[str, Any]] = []
        self.position_answers: list[dict[str, Any] | None] = []
        self.resting = False

    def _skewed(self, request: httpx.Request) -> httpx.Response | None:
        """Not judged here: the REST client signs on the real wall clock, the venue runs on the
        virtual one (#843's own tests prove its `10002`)."""
        return None

    def _order_create(self, body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        closing = bool(body["reduceOnly"])
        answers = self.close_answers if closing else self.create_answers
        if answers:
            self.creates.append(body)
            return answers.pop(0)
        if self.create_late and not closing:
            self.held_back.append(body)  # recorded in `creates` when the venue acts on it
            return self.create_late.pop(0)
        if closing and self.close_unfilled:
            self.creates.append(body)
            link = str(body["orderLinkId"])
            return self._ok("trading-create-reply", orderId=str(uuid4()), orderLinkId=link)
        reply = super()._order_create(body, params)
        return self.create_after.pop(0) if self.create_after and not closing else reply

    def _match(self, order: VenueOrder) -> None:
        if not self.resting:
            super()._match(order)

    def act(self, body: dict[str, Any]) -> None:
        """The venue acts on a held-back create now (it matches and pushes as any create)."""
        super()._order_create(body, {})

    def _position_list(self, body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        answer = self.position_answers.pop(0) if self.position_answers else None
        return super()._position_list(body, params) if answer is None else answer

    def _position_trading_stop(
        self, body: dict[str, Any], _params: dict[str, str]
    ) -> dict[str, Any]:
        self.stop_writes.append(body)
        if self.stop_answers:
            return self.stop_answers.pop(0)
        self.stop = Decimal(body["stopLoss"])
        position = self.corpus.push("position")["data"][0]
        self._send("position", self._position_row(position, rest=False))
        return self._ok("trading-trading-stop-reply")


def error(code: int, msg: str) -> dict[str, Any]:
    """A corpus error envelope with its code and text patched (never a hand-written shape)."""
    return patched(CORPUS.rest("trading-error-110001"), retCode=code, retMsg=msg)


class MemoryLedger(IntentLedger):
    """#843's intent ledger, its row kept in memory (its fsync path is #843's own, tested there;
    a thread hop would race the virtual clock)."""

    async def record(self, req: PlaceOrderRequest) -> None:
        self.digests.add(digest(req.order_link_id))
        self.intents += 1


class Rig:
    def __init__(
        self,
        tmp: Path,
        *,
        create_delay_s: float = 0.03,
        stop_delay_s: float = 0.12,
        cfg: ArmConfig | None = None,
    ) -> None:
        self.clock = VirtualClock()
        self.venue_skew_ms = 0
        self.create_delay_s, self.stop_delay_s = create_delay_s, stop_delay_s
        self.ack_delay_s = 0.0
        self.late_s = self.rest_s = self.fill_late_s = 0.0
        self.late = "fill"
        self._late: set[asyncio.Task[None]] = set()
        self.venue = StopVenue(CORPUS, now_ms=lambda: self.wall_ms() + self.venue_skew_ms)
        self.tap = Tap(httpx.MockTransport(self._handle), wall_ms=lambda: float(self.wall_ms()))
        self.offset = ClockOffset()
        self.governor = RecordingGovernor(clock=self.clock, sleep=self.clock.sleep)
        streams = PrivateStreams(
            environment="demo",
            credentials=fake_capability(SIGNER),
            connect=self.venue.connect,
            budget=ConnectionBudget(self.clock),
            policy=ReconnectPolicy(rng=random.Random(7)),  # noqa: S311 - seeded test jitter
            sleep=self.clock.sleep,
            monotonic=self.clock,
            wall_ms=self.wall_ms,
            now_us=self.clock.now_us,
        )
        port = BybitTradingPort(
            environment="demo",
            credentials=fake_capability(SIGNER),
            governor=self.governor,
            transport=self.tap,
            clock_offset_ms=self.offset.read,
            private_streams=streams,
            sleep=self.clock.sleep,
            monotonic=self.clock,
            now_us=self.clock.now_us,
        )
        self.scrubber = Scrubber()
        self.port = SlGuardedPort(port)
        step = Decimal("0.001")
        self.port.limits = QtyLimits(step, step, Decimal("0.010"))
        self.port.ledger = MemoryLedger(tmp, self.scrubber, elapsed=self.clock)
        self.account = AccountRef(
            account_id=AccountId(uuid4()),
            uid="spike",
            environment="demo",
            key_ref=str(CREDENTIAL_ID),
        )
        self.watch = Watch(self.clock.sleep)

        async def reference() -> Decimal:
            return self.venue.ref

        self.runner = ArmRunner(
            port=self.port,
            account=self.account,
            tap=self.tap,
            watch=self.watch,
            offset=self.offset,
            clock=Clock(self.clock, lambda: float(self.wall_ms()), self.clock.sleep),
            links=Links(self.account.account_id, self.scrubber),
            scrubber=self.scrubber,
            reference=reference,
            cfg=cfg if cfg is not None else ArmConfig(),
            run_id="run#1",
        )

    def wall_ms(self) -> int:
        return round(self.clock.wall_s() * 1000)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        delay = {
            "/v5/order/create": self.create_delay_s,
            "/v5/position/trading-stop": self.stop_delay_s,
        }
        half = delay.get(request.url.path, 0.0) / 2
        if half:  # the venue acts (and stamps its `time`) halfway through the round trip
            await self.clock.sleep(half)
        body = json.loads(request.content) if request.url.path == "/v5/order/create" else {}
        park = bool(self.fill_late_s and body and not body["reduceOnly"])
        self.venue.resting |= park
        response = await self.venue.handle(request)
        if park:
            self.venue.resting = False
            self._later(self._fill_late(str(body["orderLinkId"])))
        while self.venue.held_back:
            self._later(self._act_late(self.venue.held_back.pop(0)))
        if half:
            await self.clock.sleep(half)
        if self.ack_delay_s and request.url.path == "/v5/order/create":
            await self.clock.sleep(self.ack_delay_s)  # filled at once, answered late
        return response

    def _later(self, work: Awaitable[None]) -> None:
        task = asyncio.ensure_future(work)
        self._late.add(task)
        task.add_done_callback(self._late.discard)

    async def _fill_late(self, link: str) -> None:
        await self.clock.sleep(self.fill_late_s)
        [order] = [o for o in self.venue.orders.values() if o.link == link]
        if self.late == "partial":
            self.venue._fill(order, self.venue.step, order.price, maker=True)
        (self.venue._match if self.late == "fill" else self.venue._cancel)(order)

    async def _act_late(self, body: dict[str, Any]) -> None:
        await self.clock.sleep(self.late_s)
        self.venue.resting = self.rest_s > 0
        self.venue.act(body)
        self.venue.resting = False
        if self.rest_s:
            await self.clock.sleep(self.rest_s)
            [order] = [o for o in self.venue.orders.values() if o.link == body["orderLinkId"]]
            self.venue._match(order)

    async def up(self) -> None:
        await self.watch.open(self.port, self.account)
        await self.clock.run_until(lambda: self.watch.live, within_s=60, what="the stream is up")

    async def drive[T](self, work: Callable[[], Awaitable[T]], within_s: float = 120) -> T:
        """Run `work` to its end on the virtual clock."""
        task = asyncio.ensure_future(work())
        await self.clock.run_until(task.done, within_s=within_s, what="the work ends")
        return task.result()
