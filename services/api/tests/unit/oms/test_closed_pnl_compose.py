"""The closed-PnL composition (E29-S06 #981 slice 5b; 24 Sec.8.13 steps 1 to 6 and "Provisional,
settled and final", the orchestrator's rulings Q2 to Q4 of 2026-11-04 23:45Z), over the sync tests'
in-memory store. Fills are `n` seconds after `START`, the key's confirmed flat; the worked example's
figures are the docs-transcribed record's (24 Sec.8.13 "A worked example")."""

from __future__ import annotations

import ast
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.oms import closed_pnl_compose as mod
from candleviewer.oms import closed_pnl_walk
from candleviewer.oms.closed_pnl_compose import ClosedPnlComposer, Composed, is_final, settles
from candleviewer.oms.closed_pnl_sync import venue_record
from candleviewer.oms.closed_pnl_walk import Walk, WalkBudget, WalkClose
from candleviewer.oms.errors import OmsNotReady
from candleviewer.storage.repositories.closed_pnl import WalkFill, record_id
from candleviewer.storage.repositories.orders import OrderSide, OrderState
from tests.unit.exchange.bybit._trading import ACCOUNT_A
from tests.unit.oms.submit_rig import Instruments, instrument
from tests.unit.oms.test_closed_pnl_sync import Store, _record

START = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)  # the key's confirmed flat
OPEN, CLOSE, OTHER = UUID(int=0xA), UUID(int=0xB), UUID(int=0xC)  # order rows
G1, G2 = UUID(int=0x61), UUID(int=0x62)  # trade groups
N = Decimal


def at(n: float) -> datetime:
    return START + timedelta(seconds=n)


def order(store: Store, oid: UUID, side: str, *, state: str = "filled", idx: int = 0) -> None:
    store.orders[f"x-{oid.int}"], store.keys[oid] = (oid, state), ("ETHUSDT", side, idx)


def fill(
    store: Store, n: float, oid: UUID | None, side: OrderSide, qty: str, price: str, *,
    fee: str = "0",
    closed: str | None = None, pnl: str | None = "0", group: UUID | None = None, idx: int = 0,
) -> None:  # fmt: skip
    """The `n`-th fill: `closed` its stated `closedSize`, `pnl` its closed PnL, `group` the group
    its order row's leg names; `oid` None for a fill with no order row."""
    store.fills.append(("ETHUSDT", WalkFill(
        exec_id=f"e{n:07.3f}", exec_ts=at(n), order_id=oid, side=side, exec_type="Trade",
        exec_qty=N(qty), exec_price=N(price), exec_fee=N(fee),
        closed_pnl=None if pnl is None else N(pnl),
        closed_size=None if closed is None else N(closed),
        order_position_idx=None if oid is None else idx,
        order_exchange_id=None if oid is None else f"x-{oid.int}", order_group_id=group,
    )))  # fmt: skip


def book(*, flats: tuple[datetime, ...] = (START,)) -> Store:
    """A long of 2 opened by OPEN (on G1) and closed by CLOSE, all stream fills, both filled."""
    store = Store(flats={("ETHUSDT", 0): flats})
    order(store, OPEN, "Buy")
    order(store, CLOSE, "Sell")
    fill(store, 1, OPEN, "Buy", "2", "100", fee="0.12", closed="0", group=G1)
    fill(store, 2, CLOSE, "Sell", "2", "103", fee="0.1236", closed="2", pnl="6")
    return store


def composer(store: Store, **kw: Any) -> ClosedPnlComposer:
    listed = Instruments(listed={"ETHUSDT": instrument(symbol="ETHUSDT")})  # 480 min apart
    return ClosedPnlComposer(store=store, instruments=kw.pop("instruments", listed), **kw)


async def compose(store: Store, *orders: UUID, finalize: bool = False, **kw: Any) -> Composed:
    """The one record the step composes."""
    [one] = await composer(store, **kw).begin(ACCOUNT_A).compose(orders, finalize=finalize)
    return one


def figures(c: Composed) -> tuple[Decimal | None, ...]:
    return c.row.gross_pnl, c.row.fee_pnl, c.row.funding_pnl, c.local_net


async def test_the_worked_example_composes_the_records_figures_and_its_provisional_item() -> None:
    """24 Sec.8.13: a long of 3 (entry value 3584.9255) closed by one order's 4 fills, every fill
    a taker's at 0.0006, no settlement while held: `local_net` is the record's `closedPnl`."""
    store = Store(flats={("ETHUSDT", 0): (START,)})
    order(store, OPEN, "Buy")
    order(store, CLOSE, "Sell")
    for n, (price, fee) in enumerate((("1194.9", "0.71694"), ("1195", "0.717"),
                                      ("1195.0255", "0.7170153")), 1):  # fmt: skip
        fill(store, n, OPEN, "Buy", "1", price, fee=fee, closed="0", group=G1)
    for n, (qty, price, fee, pnl) in enumerate((
        ("1", "1180.5", "0.7083", "-14.47516667"), ("1", "1180.6", "0.70836", "-14.37516667"),
        ("0.5", "1180.69", "0.354207", "-7.142583335"),
        ("0.5", "1180.7", "0.35421", "-7.137583325"),
    ), 4):  # fmt: skip
        fill(store, n, CLOSE, "Sell", qty, price, fee=fee, closed=qty, pnl=pnl)
    c = await compose(store, CLOSE)
    assert figures(c) == (N("-43.1305"), N("-4.2760323"), N(0), N("-47.4065323"))
    assert c.local_net == N(_record().closed_pnl)
    row = c.row
    assert (row.qty, row.avg_entry_price, row.avg_exit_price) == (
        N(3), N("1194.975166666666666667"), N("1180.598333333333333333"),
    )  # fmt: skip
    assert (row.side, row.position_idx, row.trade_group_id) == ("long", 0, G1)
    assert (row.opened_at, row.closed_at, row.settled_at, c.final) == (at(1), at(7), None, False)


@pytest.mark.parametrize(
    ("fees", "fee_pnl"),
    [(("0.12", "0.1236"), "-0.2436"), (("-0.02", "-0.0206"), "0.0406")],
    ids=["taker fees paid", "maker rebates"],
)
async def test_a_fee_paid_is_negative_and_a_rebate_positive(
    fees: tuple[str, str], fee_pnl: str
) -> None:
    store = Store(flats={("ETHUSDT", 0): (START,)})
    order(store, OPEN, "Buy")
    order(store, CLOSE, "Sell")
    fill(store, 1, OPEN, "Buy", "2", "100", fee=fees[0], closed="0")
    fill(store, 2, CLOSE, "Sell", "2", "103", fee=fees[1], closed="2", pnl="6")
    assert figures(await compose(store, CLOSE)) == (N(6), N(fee_pnl), N(0), 6 + N(fee_pnl))


@pytest.mark.parametrize(
    ("minutes", "opened", "closed", "settled"),
    [
        (480, "07:59:59", "08:00:00", True),  # the close at a settlement: ends included
        (480, "08:00:00", "08:00:01", True),  # the open at a settlement
        (480, "08:00:01", "15:59:59", False),
        (240, "08:00:01", "12:00:00", True),
        (60, "10:00:01", "10:59:59.999999", False),
        (60, "23:30:00", "00:15:00", True),  # 00:00 UTC of the next day
    ],
)
def test_funding_settles_when_a_settlement_falls_in_the_held_window_ends_included(
    minutes: int, opened: str, closed: str, settled: bool
) -> None:
    """24 Sec.8.13 step 5: settlements `funding_interval_min` apart from 00:00 UTC."""
    day = START.date().isoformat()
    a, b = (datetime.fromisoformat(f"{day}T{t}+00:00") for t in (opened, closed))
    assert settles(a, b if b > a else b + timedelta(days=1), minutes) is settled


@pytest.mark.parametrize(
    "instruments",
    [Instruments(refuse=OmsNotReady()), Instruments(listed={}),
     Instruments(listed={"ETHUSDT": instrument(symbol="ETHUSDT", funding_interval_min=0)})],
    ids=["cache not ready", "no instrument", "interval out of range"],
)  # fmt: skip
async def test_an_unknown_funding_interval_leaves_funding_and_local_net_absent_never_0(
    instruments: Instruments,
) -> None:
    assert figures(await compose(book(), CLOSE, instruments=instruments)) == (
        N(6), N("-0.2436"), None, None,
    )  # fmt: skip


async def test_a_settlement_while_held_leaves_funding_pending_and_local_net_absent() -> None:
    store = book()
    store.fills[1] = ("ETHUSDT", replace(store.fills[1][1], exec_ts=START.replace(hour=16)))
    assert figures(await compose(store, CLOSE)) == (N(6), N("-0.2436"), None, None)


async def test_each_figure_is_quantized_once_half_up_to_8_dp_and_local_net_sums_them() -> None:
    """The orchestrator's rounding ruling: exact, then `ROUND_HALF_UP` to 8 dp once; a half at
    the 9th place goes up, where `ROUND_HALF_EVEN` would keep it."""
    store = Store(flats={("ETHUSDT", 0): (START,)})
    order(store, OPEN, "Buy")
    order(store, CLOSE, "Sell")
    fill(store, 1, OPEN, "Buy", "1", "100", fee="0.000000015", closed="0")
    fill(store, 2, CLOSE, "Sell", "1", "100", fee="0.00000001", closed="1", pnl="0.000000125")
    assert figures(await compose(store, CLOSE)) == (
        N("0.00000013"), N("-0.00000003"), N(0), N("0.00000010"),
    )  # fmt: skip


async def test_the_fee_is_negated_exactly_so_it_is_rounded_once() -> None:
    """A fee whose digits past the 8th place are a 4 and a run of 9s, as a share's 80-digit
    quotient can be, rounds down to 8 dp; negating it in a 28-digit context first rounds it up."""
    store = Store(flats={("ETHUSDT", 0): (START,)})
    order(store, OPEN, "Buy")
    order(store, CLOSE, "Sell")
    fill(store, 1, OPEN, "Buy", "1", "100", closed="0")
    fee = "0.123456784999999999999999999995"
    fill(store, 2, CLOSE, "Sell", "1", "101", fee=fee, closed="1", pnl="1")
    assert figures(await compose(store, CLOSE)) == (
        N(1), N("-0.12345678"), N(0), N("0.87654322"),
    )  # fmt: skip


async def test_a_reversal_composes_the_size_it_closes_never_the_fills_exec_qty() -> None:
    """24 Sec.8.13 "Provisional": a sell of 3 against a long of 2 closes `c` = 2, takes 2/3 of its
    fee as its closing share and opens a short of 1 with the rest, which its record never holds."""
    store = book()
    store.fills.pop()
    fill(store, 2, CLOSE, "Sell", "3", "103", fee="0.1854", closed="2", pnl="6")
    c = await compose(store, CLOSE)
    assert (c.row.qty, c.closed, c.row.avg_exit_price) == (N(2), N(2), N(103))
    assert figures(c) == (N(6), N("-0.2436"), N(0), N("5.7564"))


@pytest.mark.parametrize(
    ("groups", "flats", "group"),
    [
        ((G1,), (START,), G1),
        ((G1, None), (START,), G1),  # an adopted order on no leg names none
        ((G1, G2), (START,), None),  # two tickets pool one position: several, NULL
        ((None,), (START,), None),
        ((G1,), (), None),  # no walk start: NULL, never the closing side's group
    ],
    ids=["one", "one and an adopted order", "several", "none", "no start"],
)
async def test_the_record_stores_the_one_group_its_opening_fills_orders_name(
    groups: tuple[UUID | None, ...], flats: tuple[datetime, ...], group: UUID | None
) -> None:
    store = book(flats=flats)
    store.fills.pop()  # the close, re-added after the openers on its own leg's group G2
    for n, opener in enumerate(groups[1:], 2):
        order(store, OTHER, "Buy")
        fill(store, n, OTHER, "Buy", "1", "100", closed="0", group=opener)
    store.fills[0] = ("ETHUSDT", replace(store.fills[0][1], order_group_id=groups[0]))
    fill(store, 5, CLOSE, "Sell", str(len(groups) + 1), "103", closed=str(len(groups) + 1),
         pnl="6", group=G2)  # fmt: skip
    assert (await compose(store, CLOSE)).row.trade_group_id == group


@pytest.mark.parametrize(
    ("flats", "closed", "held", "item"),
    [
        ((START,), "0", False, None),  # an opening order: no stored fill of it closes
        ((), "2", False, "no figures"),  # a stated close with no walk start: an item, none
        ((), None, False, None),  # a REST-recovered close with no start waits for its record
        ((), None, True, "no figures"),  # its record read, the composition loses its figures
    ],
    ids=["opening order", "stated close, no start", "REST close, no start", "record held"],
)
async def test_an_item_is_written_for_an_order_whose_stored_fill_closes_or_whose_record_is_held(
    flats: tuple[datetime, ...], closed: str | None, held: bool, item: str | None
) -> None:
    store = book(flats=flats)
    store.fills.pop()
    fill(store, 2, CLOSE, "Sell" if closed != "0" else "Buy", "2", "103", closed=closed, pnl="6")
    if held:
        await store.settle(venue_record(_record(exchange_order_id=f"x-{CLOSE.int}")))
    done = await composer(store).begin(ACCOUNT_A).compose([CLOSE])
    assert [(figures(c), c.row.trade_group_id, c.row.opened_at) for c in done] == (
        [] if item is None else [((None, None, None, None), None, None)]
    )  # fmt: skip
    if item is not None and not held:
        assert (done[0].row.qty, done[0].row.closed_at, done[0].row.position_idx) == (
            None,
            at(2),
            0,
        )


async def test_a_settled_records_venue_columns_survive_a_recompose_and_the_walk_stays() -> None:
    store = book()
    await compose(store, CLOSE)
    await store.settle(venue_record(_record(exchange_order_id=f"x-{CLOSE.int}", qty=N(2))))
    c = await compose(store, CLOSE)
    venue = venue_record(_record())
    assert (c.row.qty, c.row.closed_pnl, c.row.closed_at) == (
        N(2),
        venue.closed_pnl,
        venue.closed_at,
    )
    assert (c.row.opened_at, c.row.trade_group_id, c.row.gross_pnl) == (at(1), G1, N(6))


@pytest.mark.parametrize(
    ("case", "final"),
    [("as built", True), ("unsettled", False), ("already final", False), ("order open", False),
     ("no walk", False), ("no start", False), ("capped", False), ("no close", False),
     ("size in doubt", False), ("short of its qty", False), ("walk not clean", True)],
)  # fmt: skip
async def test_the_final_rule_reads_the_records_own_closes_never_the_walks_clean(
    case: str, final: bool
) -> None:
    """Q4 option 3: terminal, settled, a start, not capped, each close `sizes_sure` and their `c`
    the record's `qty`; a walk whose span after the record's closes is unreadable is not clean."""
    store = book()
    await store.settle(venue_record(_record(exchange_order_id=f"x-{CLOSE.int}", qty=N(2))))
    row = store.rows[record_id(ACCOUNT_A, f"x-{CLOSE.int}")]
    close = WalkClose(
        fill=store.fills[1][1], closed=N(2), closing_fee=N(0), entry_value=N(200),
        opening_fees=N(0), avg_entry=N(100), opened_at=at(1), groups=frozenset(),
        unreadable=False, sizes_sure=True, disagreeing=False,
    )  # fmt: skip
    state: OrderState = "filled"
    closes: tuple[WalkClose, ...] = (close,)
    walked: Walk | None = Walk(start=START, closes=closes, clean=True)
    match case:
        case "unsettled" | "already final":
            row = (
                replace(row, settled_at=None)
                if case == "unsettled"
                else replace(row, final_at=at(9))
            )
        case "order open":
            state = "partially_filled"
        case "no walk" | "no start" | "capped" | "walk not clean":
            walked = {"no walk": None, "no start": Walk(start=None, closes=closes),
                      "capped": Walk(start=START, closes=closes, capped=True),
                      "walk not clean": Walk(start=START, closes=closes)}[case]  # fmt: skip
        case "no close":
            closes = ()
        case "size in doubt" | "short of its qty":
            closes = (replace(close, **({"sizes_sure": False} if case == "size in doubt"
                                        else {"closed": N("1.5")})),)  # fmt: skip
    assert is_final(row, state, walked, closes) is final


@pytest.mark.parametrize(
    ("qty", "closed", "pnl", "final"),
    [("2", None, None, True), ("3", None, "6", False), ("2", "1.5", "6", False)],
    ids=["REST-recovered: no closedSize, no closed PnL", "larger than the open size, no closedSize",
         "a closedSize the walk disagrees with"],
)  # fmt: skip
async def test_the_walks_c_completes_the_final_rule_only_where_it_is_sure_of_its_count(
    qty: str, closed: str | None, pnl: str | None, final: bool
) -> None:
    """24 Sec.8.13: a REST-recovered close is final once settled, with no local figures (step
    1); a close whose count the walk doubts never is, though its `c` is the record's `qty`; a
    disagreeing one has no figures, an unreadable one its gross alone."""
    store = book()
    store.fills.pop()
    fill(store, 2, CLOSE, "Sell", qty, "103", closed=closed, pnl=pnl)
    await store.settle(venue_record(_record(exchange_order_id=f"x-{CLOSE.int}", qty=N(2))))
    assert not (await compose(store, CLOSE)).final  # the step before the read never finalizes
    c = await compose(store, CLOSE, finalize=True)
    stamped = store.rows[c.row.id].final_at is not None
    assert (c.final, stamped, c.closed, c.row.fee_pnl) == (final, final, N(2), None)
    assert c.row.gross_pnl == (6 if qty == "3" else None)


async def test_a_capped_walk_composes_no_figure_is_never_final_and_warns_with_ids_alone() -> None:
    store = book()
    await store.settle(venue_record(_record(exchange_order_id=f"x-{CLOSE.int}", qty=N(2))))
    with capture_logs() as logs:
        c = await compose(store, CLOSE, finalize=True, budget=WalkBudget(fills=1, flats=4))
    assert figures(c) == (None, None, None, None) and not c.final and c.closed is None
    assert (c.row.trade_group_id, c.row.opened_at) == (None, None)
    rid = str(record_id(ACCOUNT_A, f"x-{CLOSE.int}"))
    assert logs == [{"event": "closed_pnl_walk_capped", "log_level": "warning",
                     "account_id": str(ACCOUNT_A), "record_id": rid}]  # fmt: skip


async def test_a_spent_wall_budget_composes_nothing_more_and_warns_per_closing_order() -> None:
    store = book()
    with capture_logs() as logs:
        done = await composer(store, wall_s=0.0).begin(ACCOUNT_A).compose([CLOSE, OPEN])
    assert done == () and (store.calls["walk_fills"], store.calls["compose"]) == (0, 0)
    rid = str(record_id(ACCOUNT_A, f"x-{CLOSE.int}"))  # the opening order names no record
    assert [(e["event"], e["account_id"], e["record_id"]) for e in logs] == [
        ("closed_pnl_compose_budget_spent", str(ACCOUNT_A), rid),
    ]  # fmt: skip


async def test_a_step_takes_at_most_compose_limit_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "COMPOSE_LIMIT", 1)
    with capture_logs() as logs:
        done = await composer(book()).begin(ACCOUNT_A).compose([CLOSE, OPEN], ["x-99"])
    assert [c.row.exchange_order_id for c in done] == [f"x-{CLOSE.int}"]
    assert [(e["event"], e["left"]) for e in logs] == [("closed_pnl_compose_limited", 2)]


async def test_the_walk_runs_on_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.18: 500 fills take milliseconds, more than the loop may spend."""
    threads, real = list[int](), closed_pnl_walk.walk

    def walked(*args: Any, **kw: Any) -> Walk:
        threads.append(threading.get_ident())
        return real(*args, **kw)

    monkeypatch.setattr(mod, "walk", walked)
    await compose(book(), CLOSE)
    assert threads and threading.get_ident() not in threads


async def test_a_pass_walks_a_key_once_for_both_steps_and_again_for_a_later_fill() -> None:
    """Q3: the orders of a key sharing a start share a walk, which the settled step reuses; a
    fill past its end is walked again. A confirmed flat splits the key's walk into independent
    pieces: each order composes alike alone or together."""
    store = Store(flats={("ETHUSDT", 0): (START, at(2.5))})
    for oid, side in ((OPEN, "Buy"), (CLOSE, "Sell"), (OTHER, "Sell")):
        order(store, oid, side)
    fill(store, 1, OPEN, "Buy", "2", "100", closed="0")
    fill(store, 2, CLOSE, "Sell", "2", "103", closed="2", pnl="6")
    fill(store, 3, OPEN, "Buy", "1", "100", closed="0")
    fill(store, 4, OTHER, "Sell", "1", "104", closed="1", pnl="4")
    alone = [figures(await compose(store, oid)) for oid in (CLOSE, OTHER)]
    store.calls.clear()
    composing = composer(store).begin(ACCOUNT_A)
    first = await composing.compose([CLOSE, OTHER])
    assert sorted(figures(c) for c in first) == sorted(alone) and store.calls["walk_fills"] == 2
    await composing.compose([CLOSE, OTHER], finalize=True)
    assert store.calls["walk_fills"] == 2  # reused
    fill(store, 5, OTHER, "Sell", "0.5", "105", closed="0.5", pnl="2")
    fill(store, 4.5, OPEN, "Buy", "0.5", "100", closed="0")
    [later] = await composing.compose([OTHER])
    assert store.calls["walk_fills"] == 3 and (later.closed, later.row.gross_pnl) == (
        N("1.5"),
        N(6),
    )


def test_no_cap_path_reads_a_composed_figure() -> None:
    """The cap sums the venue's settled records alone (S4, `DayRiskFigures`): neither its module
    nor `risk/` names the composition, the closed-PnL store or a local figure."""
    root = Path(mod.__file__).resolve().parents[1]
    local = {"ClosedPnlComposer", "ComposePass", "ClosedPnlStore", "SqlAlchemyClosedPnlStore",
             "gross_pnl", "fee_pnl", "funding_pnl", "local_net", "closed_pnl_records"}  # fmt: skip
    for path in (root / "oms" / "day_figures.py", *sorted((root / "risk").rglob("*.py"))):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        named |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not named & local, path
