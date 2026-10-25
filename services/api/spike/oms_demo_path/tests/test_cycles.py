# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""`cycles`, offline end to end (#843 A4 brief items 4, 6, 7, 8): through the real composition
(M2 over the in-memory store, the audit writer on its own WAL), the real port and private stream
behind the recording seams, and the corpus venue. Also its pure logic against `FakeTradingPort`.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import signal
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import (
    AccountRef,
    AmendOrderRequest,
    Execution,
    OrderAck,
    PlaceOrderRequest,
    Position,
    PrivateEvent,
    PrivateStreamStatus,
    Wallet,
)
from spike.oms_demo_path import cycles, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.harness import Harness, PublicReads
from spike.oms_demo_path.offline import (
    OFFLINE_UID,
    Corpus,
    CorpusVenue,
    OfflineStack,
    default_corpus,
    offline_stack,
)
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.safety import GuardedPort, Shutdown
from spike.oms_demo_path.scrub import Scrubber


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 4, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


def _venue(**options: Any) -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()), **options)


@pytest.fixture
def stacks(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[OfflineStack]]:
    """The offline stack each run builds (its account and key ids), kept for the leak scan."""
    seen: list[OfflineStack] = []
    original = offline_stack

    async def keep(*args: Any, **kwargs: Any) -> OfflineStack:
        stack = await original(*args, **kwargs)
        seen.append(stack)
        return stack

    monkeypatch.setattr(run, "offline_stack", keep)
    yield seen


def _summary(out: Path) -> dict[str, Any]:
    return dict(run.summary_of(out))


def _every_output(out: Path) -> str:
    texts = []
    for path in sorted(out.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            texts.append((gzip.decompress(raw) if path.suffix == ".gz" else raw).decode())
    return "\n".join(texts)


async def test_offline_cycles_place_fill_amend_cancel_and_close_flat(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    venue = _venue()
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 0
    s = _summary(tmp_path / "out")
    assert s["cycles"]["outcomes"] == {"filled": 2, "partial": 2}
    assert s["cycles"]["actions"] == {"amend": 4, "cancel": 2, "close": 4, "drive": 4, "place": 4}
    shutdown = s["shutdown"]
    assert (shutdown["reason"], shutdown["armed"], shutdown["action"]) == (
        "completed",
        True,
        "scoped flatten",
    )
    assert (shutdown["cancelled"], shutdown["flatten_orders"], shutdown["flat"]) == (0, 0, True)
    assert shutdown["own_net_qty"] == shutdown["own_net_after"] == "0"
    assert shutdown["errors"] == [] and s["outcome"] == "completed"
    assert venue.size == 0
    private = s["private"]
    assert private["parity"]["rest_only"] == private["parity"]["stream_only"] == 0
    assert private["parity"]["both"] == venue.fills == 8
    assert private["ordering"]["execution_after_order"] == 0
    assert private["transitions"]["partially_filled->partially_filled_canceled"] == 2
    assert s["safety"] == {"openers": 4, "openers_with_native_stop": 4, "closes_reduce_only": 4}
    assert s["audit"]["buffer_depth"] == 0 and s["audit"]["written"] > 0
    assert s["outputs"]["refused_by_scrub"] == 0
    assert set(s["rtt_ms"]) >= {"create", "amend", "cancel", "executions"}


async def test_every_opener_carries_its_native_stop_and_every_close_reduces(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    venue = _venue()
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 0
    openers = [b for b in venue.creates if not b["reduceOnly"]]
    closes = [b for b in venue.creates if b["reduceOnly"]]
    assert len(openers) == len(closes) == 4
    for body in openers:
        assert Decimal(body["stopLoss"]) > 0 and body["slTriggerBy"] == "MarkPrice"
        below = Decimal(body["stopLoss"]) < Decimal(body["price"])
        assert below == (body["side"] == "Buy")
        assert body["symbol"] == "BTCUSDT" and Decimal(body["qty"]) == Decimal("0.002")
    for body in closes:
        assert body["orderType"] == "Market" and "stopLoss" not in body


async def test_no_identifier_reaches_any_output_file(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    venue = _venue()
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 0
    text = _every_output(tmp_path / "out")
    [stack] = stacks
    identifiers = {str(stack.account_id), stack.key_ref, OFFLINE_UID, *venue.links, *venue.orders}
    identifiers |= {row["execId"] for row in venue.executions}
    assert len(identifiers) > 20
    assert not [i for i in identifiers if i in text]
    assert "order#1" in text and "link#1" in text  # the per-run tokens stand in for them


async def test_the_counters_count_what_the_venue_withholds_or_reorders(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    venue = _venue(drop_every=2, reorder_every=3)
    cfg = _cfg(tmp_path / "out", cycles=6, drop_every=2, reorder_every=3)
    assert await run.run(cfg, venue=venue) == 0
    s = _summary(tmp_path / "out")
    assert venue.dropped >= 2 and venue.reordered >= 1
    assert s["private"]["parity"]["rest_only"] == venue.dropped
    assert s["private"]["parity"]["stream_only"] == 0
    assert s["private"]["ordering"]["execution_after_order"] == venue.reordered
    assert s["offline_venue"]["withheld_from_stream"] == venue.dropped


async def test_an_unhandled_error_cancels_and_closes_the_runs_own_before_exit(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(h: Harness, link: str) -> None:
        raise RuntimeError("mid-cycle")

    monkeypatch.setattr(cycles, "read_order", boom)
    venue = _venue()
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 1
    s = _summary(tmp_path / "out")
    assert s["error"] == "RuntimeError" and s["outcome"] == "error"
    shutdown = s["shutdown"]
    assert shutdown["reason"] == "error:RuntimeError"
    assert shutdown["cancelled"] == 1  # the partly filled entry still resting
    assert shutdown["own_net_qty"] == shutdown["closed_qty"] == "0.001"
    assert shutdown["flatten_orders"] == 1 and shutdown["flat"] is True
    assert venue.size == 0
    assert all(o.status not in ("New", "PartiallyFilled") for o in venue.orders.values())


def test_sigterm_ends_the_run_and_the_flatten_runs(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    venue = _venue()
    original = cycles.one_cycle

    async def then_signal(*args: Any, **kwargs: Any) -> str:
        outcome = await original(*args, **kwargs)
        os.kill(os.getpid(), signal.SIGTERM)
        return outcome

    cycles.one_cycle = then_signal  # restored below
    try:
        code = asyncio.run(run.run(_cfg(tmp_path / "out", cycles=5), venue=venue))
    finally:
        cycles.one_cycle = original
    assert code == 0
    s = _summary(tmp_path / "out")
    assert s["cycles"]["completed"] == 1
    assert s["shutdown"]["reason"] == "signal:SIGTERM" and s["outcome"] == "stopped"
    assert s["shutdown"]["flat"] is True and s["shutdown"]["action"] == "scoped flatten"


# -- the same logic against FakeTradingPort ----------------------------------------------------


class _Book(FakeTradingPort):
    """The fake with a touch: an amend that joins it fills one step, a reduce-only market close
    flattens; each fill is pushed on the private stream as the venue would."""

    def __init__(self, account: AccountRef, touch: Decimal) -> None:
        super().__init__(now_us=lambda: 1_790_000_000_000_000)
        self.account, self.touch = account, touch
        self.n = 0
        self.held = Decimal(0)
        self.push(_status(account, "resyncing", "connected"))

    async def amend_order(self, req: AmendOrderRequest) -> OrderAck:
        ack = await super().amend_order(req)
        [order] = [
            o
            for o in await self.open_orders(req.account)
            if o.exchange_order_id == req.exchange_order_id
        ]
        joins = req.price is not None and (
            req.price >= self.touch if order.side == "buy" else req.price <= self.touch
        )
        if joins and order.filled_qty == 0:
            step = Decimal("0.001")
            filled = order.model_copy(
                update={
                    "state": "partially_filled",
                    "filled_qty": step,
                    "leaves_qty": order.qty - step,
                }
            )
            self.seed_order(filled, uid=req.account.uid)
            self.held = step
            self._fill(order.exchange_order_id, order.order_link_id, order.side, step)
            self.push(
                PrivateEvent(
                    kind="order",
                    account_id=order.account_id,
                    payload=filled,
                    ts_event=1,
                    ts_ingest=2,
                )
            )
        return ack

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        ack = await super().place_order(req)
        if req.reduce_only and ack.exchange_order_id is not None:
            self._fill(ack.exchange_order_id, req.order_link_id, req.side, req.qty)
            self.held = Decimal(0)
        self._position()
        return ack

    def _fill(self, order_id: str, link: str, side: Any, qty: Decimal) -> None:
        self.n += 1
        execution = Execution(
            exec_id=f"fake-exec-{self.n:04d}",
            exchange_order_id=order_id,
            order_link_id=link,
            account_id=self.account.account_id,
            symbol="BTCUSDT",
            side=side,
            price=self.touch,
            qty=qty,
            fee=Decimal("0.01"),
            fee_rate=Decimal("0.0002"),
            fee_currency="USDT",
            is_maker=True,
            exec_type="trade",
            closed_pnl=None,
            ts_exec=1,
            ts_ingest=2,
            seq=self.n,
        )
        self.seed_execution(execution)
        self.push(
            PrivateEvent(
                kind="execution",
                account_id=self.account.account_id,
                payload=execution,
                ts_event=1,
                ts_ingest=2,
            )
        )

    def _position(self) -> None:
        position = Position(
            account_id=self.account.account_id,
            symbol="BTCUSDT",
            position_idx=0,
            side="buy" if self.held else None,
            qty=self.held,
            avg_entry_price=None,
            mark_price=None,
            liq_price=None,
            leverage=Decimal(10),
            unrealised_pnl=Decimal(0),
            cum_realised_pnl=Decimal(0),
            take_profit=None,
            stop_loss=None,
            trailing_stop_distance=None,
            updated_at=1,
        )
        self.seed_position(position)
        self.push(
            PrivateEvent(
                kind="position",
                account_id=self.account.account_id,
                payload=position,
                ts_event=1,
                ts_ingest=2,
            )
        )


def _status(account: AccountRef, state: Any, reason: Any) -> PrivateStreamStatus:
    return PrivateStreamStatus(
        account_id=account.account_id, state=state, reason=reason, epoch=1, ts=1
    )


async def test_the_cycle_logic_against_the_fake_trading_port(tmp_path: Path) -> None:
    account = AccountRef(
        account_id=AccountId(uuid4()), uid="spike", environment="demo", key_ref=str(uuid4())
    )
    venue = _venue()
    fake = _Book(account, venue.ref)
    scrubber = Scrubber()
    h = Harness(
        port=GuardedPort(fake),
        account=account,
        public=PublicReads(venue.get_public, lambda: 1_790_000_000_000_000),
        outputs=RunOutputs(tmp_path / "out", scrubber),
        scrubber=scrubber,
        shutdown=Shutdown(),
    )
    fake.set_wallet(_wallet(account))
    result = await cycles.run_cycles(h, _cfg(tmp_path, cycles=2, side="buy", fill_mode="join"))
    assert result["outcomes"] == {"partial": 2}
    creates = [c.request for c in fake.calls if c.method == "place_order"]
    assert all(isinstance(r, PlaceOrderRequest) for r in creates)
    openers = [r for r in creates if isinstance(r, PlaceOrderRequest) and not r.reduce_only]
    closes = [r for r in creates if isinstance(r, PlaceOrderRequest) and r.reduce_only]
    assert len(openers) == len(closes) == 2
    assert all(
        r.stop_loss is not None and r.price is not None and r.stop_loss < r.price for r in openers
    )
    assert all(r.order_type == "market" and r.qty == Decimal("0.001") for r in closes)
    assert [c.method for c in fake.calls].count("cancel_order") == 2


def _wallet(account: AccountRef) -> Wallet:
    return Wallet(
        account_id=account.account_id,
        equity=Decimal(50_000),
        wallet_balance=Decimal(50_000),
        available_to_withdraw=None,
        available_margin=Decimal(50_000),
        used_margin=Decimal(0),
        unrealised_pnl=Decimal(0),
        cum_realised_pnl=Decimal(0),
        account_im_rate=Decimal(0),
        account_mm_rate=Decimal(0),
        updated_at=1_790_000_000_000_000,
    )


@pytest.mark.parametrize(
    ("side", "mode"), [("buy", "join"), ("sell", "join"), ("buy", "cross"), ("sell", "cross")]
)
def test_prices_keep_the_stop_beyond_the_entry_and_the_drive_at_the_touch(
    side: Any, mode: Any
) -> None:
    cfg = _cfg(Path("/nonexistent"))
    ref, tick = Decimal("63110.00"), Decimal("0.10")
    away, further, stop = cycles.prices(ref, side, cfg, tick)
    drive = cycles.drive_price(ref, side, mode, cfg, tick)
    buy = side == "buy"
    assert (stop < further < away < ref) if buy else (stop > further > away > ref)
    assert all(p % tick == 0 for p in (away, further, stop, drive))
    if mode == "join":
        assert drive == (ref if buy else ref + tick)
    else:
        assert (drive > ref + tick) if buy else (drive < ref)
    assert (stop < drive) if buy else (stop > drive)


def test_sides_and_fill_modes_alternate() -> None:
    assert [cycles.side_of("alternate", n) for n in range(4)] == ["buy", "sell", "buy", "sell"]
    assert [cycles.fill_mode_of("alternate", n) for n in range(4)] == [
        "join",
        "join",
        "cross",
        "cross",
    ]
    assert cycles.side_of("sell", 0) == "sell" and cycles.fill_mode_of("cross", 0) == "cross"


def test_decimal_output_is_plain() -> None:  # the venue's decimal text, never an exponent
    assert json.dumps(str(Decimal("0.001"))) == '"0.001"'


async def test_three_venue_failures_in_a_row_end_the_run_flat(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unanswered(h: Harness, link: str) -> None:
        raise TransportError("the venue did not answer")

    monkeypatch.setattr(cycles, "read_order", unanswered)
    venue = _venue()
    assert await run.run(_cfg(tmp_path / "out", cycles=6), venue=venue) == 1
    s = _summary(tmp_path / "out")
    assert s["cycles"]["errors"] == {"TransportError": 3}
    assert s["cycles"]["completed"] == 0
    assert s["shutdown"]["reason"] == "error:consecutive_failures"
    assert s["shutdown"]["flat"] is True and venue.size == 0
    assert all(o.status not in ("New", "PartiallyFilled") for o in venue.orders.values())


async def test_a_refused_create_is_a_rejected_cycle(
    tmp_path: Path, stacks: list[OfflineStack], monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    monkeypatch.setattr(venue, "_order_create", lambda _b, _p: venue.corpus.rest("error_10002"))
    assert await run.run(_cfg(tmp_path / "out", cycles=2), venue=venue) == 0
    s = _summary(tmp_path / "out")
    assert s["cycles"]["outcomes"] == {"rejected": 2}
    assert s["error_codes"] == {"10002": 4}  # each create re-signed once (the client's retry)
    assert s["safety"]["openers"] == 2


async def test_the_offset_is_measured_again_every_offset_every_cycles(
    tmp_path: Path, stacks: list[OfflineStack]
) -> None:
    cfg = _cfg(tmp_path / "out", cycles=3, offset_every=2, fill_mode="cross")
    assert await run.run(cfg, venue=_venue()) == 0
    events = (tmp_path / "out" / "events.jsonl").read_text().splitlines()
    clocks = [json.loads(e) for e in events if '"kind":"clock"' in e]
    assert len(clocks) == 2 and all(c["samples"] == 5 for c in clocks)
    assert _summary(tmp_path / "out")["clock"]["samples"] == 10
