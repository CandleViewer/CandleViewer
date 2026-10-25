# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The harness's safety checks (#843 A4 brief item 6), each proven offline. Written red first."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import (
    AccountRef,
    AmendOrderRequest,
    CancelOrderRequest,
    Execution,
    Order,
    OrderAck,
    PlaceOrderRequest,
    Position,
)
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS, SIGNED_REST_BASES
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.oms.order_link import OrderLinkIdParts, OrderPurpose
from candleviewer.settings import Environment, Settings
from spike.oms_demo_path import safety
from spike.oms_demo_path.config import CONFIRMATION, RunConfig
from spike.oms_demo_path.harness import Links
from spike.oms_demo_path.scrub import Scrubber
from tests._corpus import rest

ACCOUNT = AccountRef(
    account_id=AccountId(uuid4()), uid="spike", environment="demo", key_ref=str(uuid4())
)
LIMITS = safety.QtyLimits(min_qty=Decimal("0.001"), step=Decimal("0.001"), max_qty=Decimal("0.002"))


def link(purpose: OrderPurpose = "entry") -> str:
    parts = OrderLinkIdParts.generate(
        mode="exchange",
        environment="demo",
        group_id=GroupId(uuid4()),
        account_id=ACCOUNT.account_id,
        seq=0,
        purpose=purpose,
    )
    return parts.value


def opener(**overrides: object) -> PlaceOrderRequest:
    fields: dict[str, object] = {
        "account": ACCOUNT,
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": Decimal("0.002"),
        "price": Decimal("60000"),
        "order_link_id": link(),
        "stop_loss": Decimal("58000"),
    }
    return PlaceOrderRequest.model_validate(fields | overrides)


def close(qty: str = "0.002", **overrides: object) -> PlaceOrderRequest:
    fields: dict[str, object] = {
        "account": ACCOUNT,
        "symbol": "BTCUSDT",
        "side": "sell",
        "order_type": "market",
        "qty": Decimal(qty),
        "order_link_id": link("flatten"),
        "reduce_only": True,
        "lane": "critical",
    }
    return PlaceOrderRequest.model_validate(fields | overrides)


def guarded(fake: FakeTradingPort | None = None) -> tuple[safety.GuardedPort, FakeTradingPort]:
    port = fake if fake is not None else FakeTradingPort()
    guard = safety.GuardedPort(port)
    guard.limits = LIMITS
    return guard, port


def position(qty: str, side: str | None = "buy") -> Position:
    return Position.model_validate(
        {
            "account_id": ACCOUNT.account_id,
            "symbol": "BTCUSDT",
            "position_idx": 0,
            "side": side,
            "qty": Decimal(qty),
            "avg_entry_price": None,
            "mark_price": None,
            "liq_price": None,
            "leverage": Decimal(10),
            "unrealised_pnl": Decimal(0),
            "cum_realised_pnl": Decimal(0),
            "take_profit": None,
            "stop_loss": Decimal("58000"),
            "trailing_stop_distance": None,
            "updated_at": 1_790_000_000_000_000,
        }
    )


def open_order(link_id: str | None = None, order_id: str = "venue-order-1") -> Order:
    return Order.model_validate(
        {
            "order_link_id": link() if link_id is None else link_id,
            "exchange_order_id": order_id,
            "account_id": ACCOUNT.account_id,
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "qty": Decimal("0.002"),
            "price": Decimal("60000"),
            "state": "new",
            "filled_qty": Decimal(0),
            "leaves_qty": Decimal("0.002"),
            "avg_fill_price": None,
            "created_at": 1_790_000_000_000_000,
            "terminal_at": None,
        }
    )


# -- the environment, the allow-list and the operator's consent --------------------------------


@pytest.mark.parametrize("environment", ["live", "testnet"])
def test_check_environment_refuses_every_environment_but_demo(environment: str) -> None:
    settings = Settings(_env_file=None, environment=Environment(environment))  # type: ignore[call-arg]
    with pytest.raises(safety.Refused, match="demo"):
        safety.check_environment(settings)


def test_check_environment_admits_demo() -> None:
    safety.check_environment(Settings(_env_file=None, environment=Environment.DEMO))  # type: ignore[call-arg]


def test_check_venue_urls_admits_the_adapters_demo_tables() -> None:
    safety.check_venue_urls(SIGNED_REST_BASES, PRIVATE_WS_URLS)


@pytest.mark.parametrize(
    ("rest_base", "ws_url"),
    [
        ("https://api.bybit.com", PRIVATE_WS_URLS["demo"]),
        (SIGNED_REST_BASES["demo"], "wss://stream.bybit.com/v5/private"),
    ],
)
def test_check_venue_urls_refuses_a_demo_entry_that_is_not_the_pinned_host(
    rest_base: str, ws_url: str
) -> None:
    with pytest.raises(safety.Refused, match="allow-list"):
        safety.check_venue_urls({"demo": rest_base}, {"demo": ws_url})


def _online(**fields: object) -> RunConfig:
    base: dict[str, object] = {
        "mode": "cycles",
        "out": Path("/nonexistent/out"),
        "online": True,
        "understood": True,
        "account_id": uuid4(),
        "key_ref": str(uuid4()),
    }
    return RunConfig(**(base | fields))  # type: ignore[arg-type]


NOW_MS = int(time.time() * 1000)
DAY_MS = 86_400_000


def test_check_online_args_admits_a_complete_demo_run() -> None:
    safety.check_online_args(_online(), now_ms=NOW_MS)
    safety.check_online_args(_online(mode="retention", since_ms=NOW_MS - 8 * DAY_MS), now_ms=NOW_MS)


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"understood": False}, "--i-understand-this-places-demo-orders"),
        ({"account_id": None}, "--account-id"),
        ({"key_ref": None}, "--key-ref"),
        ({"key_ref": "not-an-api-keys-id"}, "--key-ref"),
        ({"cycles": 199}, "200 cycles"),
        ({"min_hours": 3.5}, "4"),
        ({"qty_multiple": 3}, "--max-qty-multiple"),
        ({"max_qty_multiple": 11, "qty_multiple": 2}, "ceiling"),
        ({"mode": "retention", "since_ms": None}, "--since-ms"),
        ({"mode": "retention", "since_ms": NOW_MS - DAY_MS}, "day 8"),
        ({"mode": "retention", "since_ms": NOW_MS + DAY_MS}, "day 8"),
    ],
)
def test_check_online_args_refuses_an_incomplete_run(fields: dict[str, object], match: str) -> None:
    with pytest.raises(safety.Refused, match=match):
        safety.check_online_args(_online(**fields), now_ms=NOW_MS)


def test_confirm_admits_only_the_exact_phrase() -> None:
    safety.confirm(lambda _prompt: CONFIRMATION)
    for typed in ("", "yes", CONFIRMATION.lower(), CONFIRMATION + " "):

        def answer(_prompt: str, typed: str = typed) -> str:
            return typed

        with pytest.raises(safety.Refused, match="confirmation"):
            safety.confirm(answer)


# -- symbol, size and the native stop on every opener (C-2.6) ----------------------------------


@pytest.mark.parametrize("symbol", ["ETHUSDT", "BTCUSDC", "btcusdt", "BTCUSDT "])
def test_check_symbol_refuses_any_symbol_but_btcusdt(symbol: str) -> None:
    with pytest.raises(safety.Refused, match="BTCUSDT"):
        safety.check_symbol(symbol)


async def test_guarded_port_refuses_another_symbol_before_anything_is_sent() -> None:
    guard, fake = guarded()
    with pytest.raises(safety.Refused, match="BTCUSDT"):
        await guard.place_order(opener(symbol="ETHUSDT"))
    with pytest.raises(safety.Refused, match="BTCUSDT"):
        await guard.cancel_order(
            CancelOrderRequest(account=ACCOUNT, symbol="ETHUSDT", order_link_id=link())
        )
    assert fake.calls == []


async def test_guarded_port_refuses_an_order_above_the_size_cap_or_off_the_step() -> None:
    guard, fake = guarded()
    for qty in ("0.003", "0.0015", "0.0005"):
        with pytest.raises(safety.Refused, match="size"):
            await guard.place_order(opener(qty=Decimal(qty)))
    with pytest.raises(safety.Refused, match="size"):
        await guard.amend_order(
            AmendOrderRequest(
                account=ACCOUNT, symbol="BTCUSDT", order_link_id=link(), qty=Decimal("0.004")
            )
        )
    assert fake.calls == []


async def test_guarded_port_refuses_every_order_until_its_limits_are_set() -> None:
    fake = FakeTradingPort()
    with pytest.raises(safety.Refused, match="limits"):
        await safety.GuardedPort(fake).place_order(opener())
    assert fake.calls == []


async def test_guarded_port_refuses_an_opener_without_a_native_stop() -> None:
    guard, fake = guarded()
    with pytest.raises(safety.Refused, match=r"C-2\.6"):
        await guard.place_order(opener(stop_loss=None))
    assert fake.calls == []


@pytest.mark.parametrize(
    ("side", "stop"), [("buy", "60000"), ("buy", "61000"), ("sell", "60000"), ("sell", "59000")]
)
async def test_guarded_port_refuses_a_stop_on_the_wrong_side_of_the_entry(
    side: str, stop: str
) -> None:
    guard, fake = guarded()
    with pytest.raises(safety.Refused, match="protective side"):
        await guard.place_order(opener(side=side, stop_loss=Decimal(stop)))
    assert fake.calls == []


async def test_guarded_port_sends_an_opener_carrying_its_stop_and_counts_it() -> None:
    guard, fake = guarded()
    ack = await guard.place_order(opener())
    assert ack.ok
    [call] = fake.calls
    assert isinstance(call.request, PlaceOrderRequest)
    assert call.request.stop_loss == Decimal("58000")
    assert not call.request.reduce_only
    assert (guard.openers, guard.closes) == (1, 0)


async def test_guarded_port_refuses_a_close_that_could_open_or_carries_a_stop() -> None:
    guard, fake = guarded()
    with pytest.raises(safety.Refused, match="reduce-only"):
        await guard.place_order(close(stop_loss=Decimal("70000")))
    with pytest.raises(safety.Refused, match="market"):
        await guard.place_order(close(order_type="limit", price=Decimal("60000")))
    assert fake.calls == []
    await guard.place_order(close())
    assert (guard.openers, guard.closes) == (0, 1)


async def test_guarded_port_refuses_an_amend_that_removes_the_stop() -> None:
    guard, fake = guarded()
    with pytest.raises(safety.Refused, match=r"C-2\.6"):
        await guard.amend_order(
            AmendOrderRequest(
                account=ACCOUNT, symbol="BTCUSDT", order_link_id=link(), stop_loss=Decimal(0)
            )
        )
    assert fake.calls == []


async def test_guarded_port_exposes_no_withdrawal_or_transfer_or_stop_write() -> None:
    guard, _ = guarded()
    for name in (
        "cancel_all",
        "set_trading_stop",
        "set_leverage",
        "place_batch",
        "withdraw",
        "transfer",
    ):
        assert not hasattr(guard, name)


def test_qty_limits_of_the_corpus_btcusdt_row_cap_at_the_max_multiple() -> None:
    rows = rest("rest/instruments_before.json")["result"]["list"]
    [row] = [r for r in rows if r["symbol"] == "BTCUSDT"]
    instrument = parse_instrument(row, fetched_at_us=0)
    limits, qty = safety.QtyLimits.of(instrument, multiple=2, max_multiple=2)
    assert (limits.min_qty, limits.step, limits.max_qty, qty) == (
        Decimal("0.001"),
        Decimal("0.001"),
        Decimal("0.002"),
        Decimal("0.002"),
    )


# -- the flat-book preflight -----------------------------------------------------------------------


def test_check_flat_refuses_an_open_order_or_a_position() -> None:
    with pytest.raises(safety.Refused, match="open order"):
        safety.check_flat([open_order()], [])
    with pytest.raises(safety.Refused, match="position"):
        safety.check_flat([], [position("0.001")])
    safety.check_flat([], [position("0", side=None)])


# -- the audit WAL: never the stack's (brief item 2) -----------------------------------------------


def _check(wal: Path, *, stack: Path, mountinfo: str = "") -> Path:
    return safety.check_audit_dir(
        str(wal), stack_wal=str(stack), stack_volume="cv-audit-data", mountinfo=mountinfo
    )


def test_check_audit_dir_admits_a_fresh_directory_and_marks_it(tmp_path: Path) -> None:
    wal = tmp_path / "spike-audit" / "spike" / "audit.wal"
    directory = _check(wal, stack=tmp_path / "stack" / "audit.wal")
    assert directory == wal.parent
    assert (directory / safety.WAL_MARKER).is_file()
    assert oct(directory.stat().st_mode & 0o777) == "0o700"
    assert _check(wal, stack=tmp_path / "stack" / "audit.wal") == directory  # its own: again


def test_check_audit_dir_refuses_the_stacks_path(tmp_path: Path) -> None:
    stack = tmp_path / "audit" / "audit.wal"
    with pytest.raises(safety.Refused, match="stack's audit WAL"):
        _check(stack, stack=stack)
    with pytest.raises(safety.Refused, match="stack's audit WAL"):
        _check(tmp_path / "audit" / "other.wal", stack=stack)


def test_check_audit_dir_refuses_a_directory_or_parent_holding_lane(tmp_path: Path) -> None:
    for holder in ("audit/spike", "audit"):
        root = tmp_path / holder.replace("/", "-")
        wal = root / "audit" / "spike" / "audit.wal"
        (root / holder / "lane").mkdir(parents=True)
        with pytest.raises(safety.Refused, match="lane/"):
            _check(wal, stack=tmp_path / "stack" / "audit.wal")


def test_check_audit_dir_refuses_another_writers_wal(tmp_path: Path) -> None:
    mine = tmp_path / "a" / "spike" / "audit.wal"
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"")
    with pytest.raises(safety.Refused, match="did not create"):
        _check(mine, stack=tmp_path / "stack" / "audit.wal")
    beside = tmp_path / "b" / "spike" / "audit.wal"
    beside.parent.mkdir(parents=True)
    (beside.parent.parent / "audit.wal").write_bytes(b"")
    with pytest.raises(safety.Refused, match="another writer"):
        _check(beside, stack=tmp_path / "stack" / "audit.wal")


def test_check_audit_dir_refuses_a_directory_on_the_stacks_volume(tmp_path: Path) -> None:
    wal = tmp_path / "spike" / "audit.wal"
    mountinfo = "\n".join(
        [
            "22 1 0:21 / / rw,relatime - overlay overlay rw",
            f"35 22 8:1 /var/lib/docker/volumes/cv-demo_cv-audit-data/_data {tmp_path} rw - ext4 "
            "/dev/sda1 rw",
        ]
    )
    with pytest.raises(safety.Refused, match="volume"):
        _check(wal, stack=Path("/var/lib/candleviewer/audit/audit.wal"), mountinfo=mountinfo)
    own = mountinfo.replace("cv-audit-data", "cv-spike-audit")
    _check(wal, stack=Path("/var/lib/candleviewer/audit/audit.wal"), mountinfo=own)


def test_check_audit_dir_refuses_a_relative_path(tmp_path: Path) -> None:
    with pytest.raises(safety.Refused, match="absolute"):
        _check(Path("var/audit/audit.wal"), stack=tmp_path / "audit.wal")


# -- the run's scope and its flatten: only what the run placed and opened (ruling R1C-02 (b)) ----

NOW_US = 1_790_000_000_000_000


def scoped() -> tuple[Links, safety.RunScope]:
    links = Links(ACCOUNT.account_id, Scrubber())
    scope = safety.RunScope(links.prefix, ACCOUNT.account_id)
    scope.start_us = NOW_US - 60_000_000
    return links, scope


def execution(link_id: str, side: str, qty: str, n: int) -> Execution:
    return Execution.model_validate(
        {
            "exec_id": f"exec-{n:04d}",
            "exchange_order_id": f"venue-fill-{n}",
            "order_link_id": link_id,
            "account_id": ACCOUNT.account_id,
            "symbol": "BTCUSDT",
            "side": side,
            "price": Decimal("60000"),
            "qty": Decimal(qty),
            "fee": Decimal("0.01"),
            "fee_rate": Decimal("0.0002"),
            "fee_currency": "USDT",
            "is_maker": True,
            "exec_type": "trade",
            "closed_pnl": None,
            "ts_exec": NOW_US,
            "ts_ingest": NOW_US,
            "seq": n,
        }
    )


class _Venue(FakeTradingPort):
    """A fake with one one-way BTCUSDT position (signed `held`): a reduce-only close fills
    against it and is listed, as the venue's would; `lists_closes=False` accepts a close and
    never lists its fill (a slow execution list)."""

    def __init__(self, held: str = "0", *, lists_closes: bool = True) -> None:
        super().__init__(now_us=lambda: NOW_US)
        self.held = Decimal(held)
        self.lists_closes = lists_closes
        self.n = 100
        self._show()

    def _show(self) -> None:
        side = None if self.held == 0 else ("buy" if self.held > 0 else "sell")
        self.seed_position(position(str(abs(self.held)), side=side))

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        ack = await super().place_order(req)
        closing = (self.held > 0) == (req.side == "sell") and self.held != 0
        if req.reduce_only and closing and self.lists_closes and ack.exchange_order_id:
            qty = min(req.qty, abs(self.held))
            self.n += 1
            self.seed_execution(execution(req.order_link_id, req.side, str(qty), self.n))
            self.held += qty if req.side == "buy" else -qty
            self._show()
            done = self._open.pop(ack.exchange_order_id)  # a market close: filled, not resting
            self._history[ack.exchange_order_id] = done.model_copy(
                update={"state": "filled", "filled_qty": qty, "leaves_qty": Decimal(0)}
            )
        return ack


async def _flatten(
    guard: safety.GuardedPort, scope: safety.RunScope, links: Links, **options: object
) -> dict[str, object]:
    return await safety.flatten(
        guard,
        ACCOUNT,
        scope,
        links.flatten,
        venue_now_us=lambda: NOW_US + 60_000_000,
        sleep=_no_sleep,
        **options,  # type: ignore[arg-type]  # the keyword options of `flatten`
    )


async def test_flatten_cancels_only_the_runs_own_orders_and_closes_only_its_own_net() -> None:
    links, scope = scoped()
    fake = _Venue("0.005")  # the run's 0.002 and a foreign 0.003, netted as on the venue
    guard, _ = guarded(fake)
    guard.scope = scope
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    fake.seed_execution(execution(link(), "buy", "0.003", 2))  # a foreign fill
    own, foreign = open_order(links.new(), "venue-own"), open_order(link(), "venue-foreign")
    for order in (own, foreign):
        fake.seed_order(order, uid=ACCOUNT.uid)
    report = await _flatten(guard, scope, links)
    cancels = [c.request for c in fake.calls if c.method == "cancel_order"]
    assert [c.order_link_id for c in cancels if isinstance(c, CancelOrderRequest)] == [
        own.order_link_id
    ]
    assert "cancel_all" not in [c.method for c in fake.calls]
    assert [o.exchange_order_id for o in await fake.open_orders(ACCOUNT)] == ["venue-foreign"]
    closes = [c.request for c in fake.calls if c.method == "place_order"]
    assert len(closes) == 1 and isinstance(closes[0], PlaceOrderRequest)
    assert (closes[0].reduce_only, closes[0].side, closes[0].qty) == (
        True,
        "sell",
        Decimal("0.002"),
    )
    assert fake.held == Decimal("0.003")  # the foreign position, untouched
    assert report["flat"] is True and report["errors"] == []
    assert (report["cancelled"], report["own_net_qty"], report["closed_qty"]) == (
        1,
        "0.002",
        "0.002",
    )
    assert report["not_ours_left"] == {"open_orders": 1, "venue_position_less_own_net": "0.003"}


async def test_flatten_never_closes_more_than_the_run_opened() -> None:
    links, scope = scoped()
    fake = _Venue("0.004")
    guard, _ = guarded(fake)
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    fake.seed_execution(execution(links.flatten(), "sell", "0.001", 2))  # its own earlier close
    first = await _flatten(guard, scope, links)
    again = await _flatten(guard, scope, links)
    assert (first["own_net_qty"], first["closed_qty"], fake.held) == (
        "0.001",
        "0.001",
        Decimal("0.003"),
    )
    assert (again["own_net_qty"], again["flatten_orders"], again["flat"]) == ("0", 0, True)


async def test_flatten_counts_a_close_sent_but_not_yet_listed_and_never_closes_twice() -> None:
    links, scope = scoped()
    fake = _Venue("0.002", lists_closes=False)
    guard, _ = guarded(fake)
    guard.scope = scope
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    report = await _flatten(guard, scope, links)
    assert [c.method for c in fake.calls].count("place_order") == 1
    assert report["flat"] is False and report["flatten_orders"] == 1


async def test_flatten_leaves_a_net_the_venue_no_longer_holds() -> None:
    links, scope = scoped()
    fake = _Venue("0")  # its native stop closed it: the venue holds nothing
    guard, _ = guarded(fake)
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    report = await _flatten(guard, scope, links)
    assert "place_order" not in [c.method for c in fake.calls]
    assert report["errors"] == ["net_not_held"] and report["flat"] is False


async def test_flatten_records_a_failed_read_by_class_and_still_closes() -> None:
    links, scope = scoped()
    fake = _Venue("0.002")
    guard, _ = guarded(fake)
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    fake.script("open_orders", RuntimeError("venue down"))
    fake.script("positions", RuntimeError("venue down"))
    report = await _flatten(guard, scope, links)
    assert report["errors"] == ["open_orders:RuntimeError", "read:RuntimeError"]
    assert report["flat"] is True and fake.held == 0


async def test_flatten_stops_at_its_deadline() -> None:
    links, scope = scoped()
    fake = _Venue("0.002")
    guard, _ = guarded(fake)
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    ticks = iter([0.0, 0.0, 41.0, 41.0, 41.0])
    report = await _flatten(guard, scope, links, monotonic=lambda: next(ticks))
    errors = report["errors"]
    assert isinstance(errors, list) and "deadline" in errors and report["flat"] is False
    assert "place_order" not in [c.method for c in fake.calls]


async def test_flatten_stops_at_its_deadline_before_any_cancel() -> None:
    links, scope = scoped()
    fake = _Venue("0")
    guard, _ = guarded(fake)
    fake.seed_order(open_order(links.new(), "venue-own"), uid=ACCOUNT.uid)
    ticks = iter([0.0, 41.0, 41.0])
    report = await _flatten(guard, scope, links, monotonic=lambda: next(ticks))
    assert report["errors"] == ["deadline", "deadline"] and report["flat"] is False
    assert [c.method for c in fake.calls] == []


async def test_flatten_records_a_cancel_and_a_close_that_raise_and_tries_again() -> None:
    links, scope = scoped()
    fake = _Venue("0.002")
    guard, _ = guarded(fake)
    guard.scope = scope
    fake.seed_order(open_order(links.new(), "venue-own"), uid=ACCOUNT.uid)
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    fake.script("cancel_order", RuntimeError("venue down"))
    fake.script("place_order", RuntimeError("venue down"))
    report = await _flatten(guard, scope, links)
    assert report["errors"] == ["cancel:RuntimeError", "close:RuntimeError"]
    assert (report["cancelled"], report["flatten_orders"], report["flat"]) == (1, 1, True)
    assert fake.held == 0 and await fake.open_orders(ACCOUNT) == []


async def test_a_close_the_flatten_cancels_no_longer_counts_as_pending() -> None:
    links, scope = scoped()
    fake = _Venue("0.002", lists_closes=False)
    guard, _ = guarded(fake)
    guard.scope = scope
    fake.seed_execution(execution(links.new(), "buy", "0.002", 1))
    await _flatten(guard, scope, links)  # its close rests unfilled, pending
    assert scope.unconfirmed() == Decimal("0.002")
    fake.lists_closes = True
    report = await _flatten(guard, scope, links)  # cancels that close, then closes again
    assert report["cancelled"] == 1 and report["flatten_orders"] == 1 and report["flat"] is True
    assert scope.unconfirmed() == 0 and fake.held == 0


async def test_guarded_port_refuses_an_amend_or_a_cancel_of_another_order() -> None:
    _, scope = scoped()
    guard, fake = guarded()
    guard.scope = scope
    with pytest.raises(safety.Refused, match="its own"):
        await guard.cancel_order(
            CancelOrderRequest(account=ACCOUNT, symbol="BTCUSDT", order_link_id=link())
        )
    with pytest.raises(safety.Refused, match="its own"):
        await guard.amend_order(
            AmendOrderRequest(
                account=ACCOUNT, symbol="BTCUSDT", order_link_id=link(), price=Decimal(1)
            )
        )
    assert fake.calls == []


def test_the_run_scope_owns_its_prefix_records_no_identifier_and_adopts_a_failed_runs() -> None:
    links, scope = scoped()
    mine, theirs = links.new(), link()
    assert scope.owns(mine) and not scope.owns(theirs) and not scope.owns(None)
    assert not scope.owns("ext-" + "0" * 32)
    record = scope.record()
    assert record["account_digest"] == safety.digest(str(ACCOUNT.account_id))
    assert mine[: safety.LINK_PREFIX_LEN] not in str(record) and str(ACCOUNT.account_id) not in str(
        record
    )
    later, other = scoped()
    other.start_us = NOW_US
    other.adopt(record)
    assert other.owns(mine) and other.owns(later.new()) and other.start_us == NOW_US - 60_000_000
    with pytest.raises(safety.Refused, match="no run scope"):
        other.adopt({"link_prefix_digests": [], "window_start_ms": 1})


def test_links_carry_one_prefix_and_keep_the_last_numbers_for_the_flatten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spike.oms_demo_path import harness

    links = Links(ACCOUNT.account_id, Scrubber())
    values = [links.new(), links.flatten(), links.new()]
    assert len(set(values)) == 3 and {v[: safety.LINK_PREFIX_LEN] for v in values} == {links.prefix}
    monkeypatch.setattr(harness, "FLATTEN_RESERVE", 3843 - 2)  # three numbers used: none left
    with pytest.raises(safety.Refused, match="space is spent"):
        links.new()
    assert links.flatten().startswith(links.prefix)


async def test_shutdown_trips_once_on_a_real_sigterm() -> None:
    shutdown = safety.Shutdown()
    remove = shutdown.install(asyncio.get_running_loop())
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        async with asyncio.timeout(5):
            await shutdown.event.wait()
        shutdown.trip("error:Later")
    finally:
        remove()
    assert shutdown.reason == "signal:SIGTERM"


async def test_shutdown_pause_returns_early_once_tripped() -> None:
    shutdown = safety.Shutdown()
    assert await shutdown.pause(0.0) is False
    shutdown.trip("signal:SIGINT")
    async with asyncio.timeout(5):
        assert await shutdown.pause(3600.0) is True


async def _no_sleep(_seconds: float) -> None:
    return None


def test_cancel_request_shape_is_unchanged() -> None:  # the guard forwards it as built
    req = CancelOrderRequest(account=ACCOUNT, symbol="BTCUSDT", exchange_order_id="x")
    assert req.symbol == "BTCUSDT"


@pytest.mark.parametrize("name", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "http_proxy"])
def test_check_no_proxy_refuses_a_proxy_the_client_would_mount(name: str) -> None:
    with pytest.raises(safety.Refused, match="proxy"):
        safety.check_no_proxy({name: "http://127.0.0.1:3128"})
    safety.check_no_proxy({name: "", "NO_PROXY": "*", "PATH": "/usr/bin"})
