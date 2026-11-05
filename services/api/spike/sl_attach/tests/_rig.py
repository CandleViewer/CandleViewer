"""The offline rig: the real `BybitTradingPort` and private stream over #843's corpus venue, on a
virtual clock, behind the harness's `Tap` and `SlGuardedPort`. No network (the session guard in
`conftest.py`). The venue is #843's `CorpusVenue` plus the one route S1 needs, `trading-stop`,
answered in the corpus's `trading-trading-stop-reply` shape (S2 moves it into the harness).
"""

from __future__ import annotations

import asyncio
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
from spike.oms_demo_path.offline import Corpus, CorpusVenue, default_corpus, patched
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
    before the venue acts on it, `create_after` after it has (an open outcome that filled);
    `close_answers` answers a reduce-only close unacted, `close_unfilled` acks one unfilled."""

    def __init__(self, corpus: Corpus, **options: Any) -> None:
        super().__init__(corpus, **options)
        self.stop_writes: list[dict[str, Any]] = []
        self.stop_answers: list[dict[str, Any]] = []
        self.create_answers: list[dict[str, Any]] = []
        self.create_after: list[dict[str, Any]] = []
        self.close_answers: list[dict[str, Any]] = []
        self.close_unfilled = False

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
        if closing and self.close_unfilled:
            self.creates.append(body)
            link = str(body["orderLinkId"])
            return self._ok("trading-create-reply", orderId=str(uuid4()), orderLinkId=link)
        reply = super()._order_create(body, params)
        return self.create_after.pop(0) if self.create_after and not closing else reply

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
        response = await self.venue.handle(request)
        if half:
            await self.clock.sleep(half)
        if self.ack_delay_s and request.url.path == "/v5/order/create":
            await self.clock.sleep(self.ack_delay_s)  # filled at once, answered late
        return response

    async def up(self) -> None:
        await self.watch.open(self.port, self.account)
        await self.clock.run_until(lambda: self.watch.live, within_s=60, what="the stream is up")

    async def drive[T](self, work: Callable[[], Awaitable[T]], within_s: float = 120) -> T:
        """Run `work` to its end on the virtual clock."""
        task = asyncio.ensure_future(work())
        await self.clock.run_until(task.done, within_s=within_s, what="the work ends")
        return task.result()
