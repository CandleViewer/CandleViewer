"""The account-fixture overlays' list rows, read as the adapter reads them (E27, #5286).

The pack's three overlays (`packages/fixtures/accounts`) seed the rows of `position/list`,
`order/realtime`, `order/history` and `execution/list`. This file serves each overlay through the
pack's resolver at the pack's reference `now` and pins that every row it seeds:

- names every field the adapter's row model requires (`PositionRow`, `OrderRow`, `ExecutionRow`)
  and no field that model does not know;
- carries fixed venue times at or before the reply that serves it (the resolver re-times the
  reply's `time` and no row field), with `createdTime` at or before `updatedTime`;
- is read by the real trading port into the neutral `Position`, `Order` and `Execution`, and by
  the exposure read behind the consequence route.

The row models stay strict: a position row without one of its required fields is refused. The
venue is an `httpx.MockTransport` over the pack's own replies (C-13.5); nothing leaves the process.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import pytest

from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.exchange.bybit.trading import BybitTradingPort
from candleviewer.exposure_wiring import PortReader
from tests._account_fixtures import OVERLAY, load, manifest, scenario_names
from tests.unit.exchange.bybit._trading import DAY_US, Venue, account, make_port

#: The pack's reference `now` (its `time` values): every row time sits at or before it.
NOW: Final = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
NOW_MS: Final = 1_792_141_200_000
NOW_US: Final = NOW_MS * 1000

POSITION_OVERLAY: Final = "open_position_btcusdt_5x_sl"
ORDERS_OVERLAY: Final = "working_orders_2"
HISTORY_OVERLAY: Final = "history_round_trip"
POSITION_LIST: Final = "GET /v5/position/list"

type RowModel = type[tp.PositionRow] | type[tp.OrderRow] | type[tp.ExecutionRow]

#: Each list read an overlay seeds, with the adapter's model of one of its rows.
ROW_MODELS: Final[Mapping[str, RowModel]] = {
    POSITION_LIST: tp.PositionRow,
    "GET /v5/order/realtime": tp.OrderRow,
    "GET /v5/order/history": tp.OrderRow,
    "GET /v5/execution/list": tp.ExecutionRow,
}
#: The calls an overlay answers with a refusal: they list no row.
REFUSALS: Final = frozenset(
    {
        "POST /v5/position/switch-mode",
        "POST /v5/position/switch-isolated",
        "POST /v5/account/set-margin-mode",
    }
)
#: The venue times a row can carry.
TIME_FIELDS: Final = ("createdTime", "updatedTime", "execTime")

OVERLAYS: Final = [name for name in scenario_names() if manifest(name).get("origin") == OVERLAY]
#: Each (overlay, call) whose reply lists rows a model reads.
PAIRS: Final = [
    (name, call) for name in OVERLAYS for call in manifest(name)["rest"] if call in ROW_MODELS
]

ACCOUNT: Final = ExchangeAccount(
    id=UUID(int=500),
    env=ExchangeEnv.DEMO,
    kind=AccountKind.MAIN,
    exchange_uid="1000001",
    label="fx-demo",
    created_at=NOW,
    updated_at=NOW,
)
KEY_ID: Final = UUID(int=1)


def _path(call: str) -> str:
    return call.split(" ", 1)[1]


def _pair_id(pair: tuple[str, str]) -> str:
    overlay, call = pair
    return f"{overlay}-{_path(call).removeprefix('/v5/').replace('/', '-')}"


PAIR_IDS: Final = [_pair_id(pair) for pair in PAIRS]


def _served(overlays: Sequence[str], call: str) -> dict[str, Any]:
    """The reply the pack serves for `call` with `overlays` seeded: a fresh dict on every call."""
    method, path = call.split(" ", 1)
    body: dict[str, Any] = (
        load("compliant", now=NOW, overlays=overlays).reply(method, path, body=None).body
    )
    return body


def _rows(reply: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = reply["result"]["list"]
    return rows


def _pair_rows(overlay: str, call: str) -> list[dict[str, Any]]:
    rows = _rows(_served([overlay], call))
    assert rows, f"{overlay}: {call} lists no row"
    return rows


def _label(row: Mapping[str, Any]) -> str:
    return str(row.get("execId") or row.get("orderId") or row.get("symbol"))


def _required(model: RowModel) -> set[str]:
    """The names the venue writes for the fields `model` requires (an alias, else the field's)."""
    return {f.alias or name for name, f in model.model_fields.items() if f.is_required()}


def _known(model: RowModel) -> set[str]:
    """Every name `model` reads or lists as documented: the drift metric's own rule."""
    return {f.alias or name for name, f in model.model_fields.items()} | set(model.documented)


def _venue(*overlays: str) -> Venue:
    """A venue that answers each read the overlays seed with the pack's own reply."""
    reads = {call for name in overlays for call in manifest(name)["rest"]} - REFUSALS
    venue = Venue()
    for call in sorted(reads):
        venue.on(_path(call), _served(overlays, call))
    return venue


class _Surface:
    """The adapter surface `PortReader` takes: `exposure_port` hands out the one real port."""

    exposure_probe_error = staticmethod(ExchangeBybitService.exposure_probe_error)

    def __init__(self, port: BybitTradingPort) -> None:
        self._port = port

    def exposure_port(
        self,
        env: str,
        *,
        on_failure: Callable[[Exception], None],
        clock_offset_ms: Callable[[], int | None] | None = None,
    ) -> BybitTradingPort:
        return self._port


# -- the rows the pack serves, against the adapter's models --------------------------------------


def test_there_is_an_overlay_row_to_check() -> None:
    assert OVERLAYS
    assert PAIRS
    assert all(_rows(_served([overlay], call)) for overlay, call in PAIRS)


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_an_overlay_stubs_only_calls_this_file_reads_or_refusals(overlay: str) -> None:
    unread = set(manifest(overlay)["rest"]) - ROW_MODELS.keys() - REFUSALS
    assert not unread, f"{overlay} stubs {sorted(unread)}: give each a row model here"


@pytest.mark.parametrize(("overlay", "call"), PAIRS, ids=PAIR_IDS)
def test_an_overlay_row_carries_every_field_its_model_requires(overlay: str, call: str) -> None:
    required = _required(ROW_MODELS[call])
    for row in _pair_rows(overlay, call):
        missing = required - row.keys()
        assert not missing, f"{overlay} {call} row {_label(row)} lacks {sorted(missing)}"


@pytest.mark.parametrize(("overlay", "call"), PAIRS, ids=PAIR_IDS)
def test_an_overlay_row_names_no_field_the_model_does_not_know(overlay: str, call: str) -> None:
    known = _known(ROW_MODELS[call])
    for row in _pair_rows(overlay, call):
        unknown = row.keys() - known
        assert not unknown, f"{overlay} {call} row {_label(row)} names {sorted(unknown)}"


@pytest.mark.parametrize(("overlay", "call"), PAIRS, ids=PAIR_IDS)
def test_an_overlay_row_never_dates_itself_after_its_reply(overlay: str, call: str) -> None:
    reply = _served([overlay], call)
    assert reply["time"] == NOW_MS
    rows = _rows(reply)
    assert rows, f"{overlay}: {call} lists no row"
    for row in rows:
        times = {name: int(row[name]) for name in TIME_FIELDS if name in row}
        where = f"{overlay} {call} row {_label(row)}"
        assert times, f"{where} carries none of {TIME_FIELDS}"
        late = sorted(name for name, millis in times.items() if millis > reply["time"])
        assert not late, f"{where} dates {late} after its reply"
        if {"createdTime", "updatedTime"} <= times.keys():
            assert times["createdTime"] <= times["updatedTime"], f"{where} updates before it exists"


# -- the rows through the real trading port and the exposure read --------------------------------


async def test_the_port_reads_the_position_overlay() -> None:
    [row] = _rows(_served([POSITION_OVERLAY], POSITION_LIST))

    [position] = await make_port(_venue(POSITION_OVERLAY)).positions(account())

    assert position.symbol == "BTCUSDT"
    assert position.side == "buy"
    assert position.qty == Decimal("0.001")
    assert position.leverage == Decimal(5)
    # A long's native stop-loss sits below its entry (C-2.6).
    assert position.stop_loss == Decimal(row["stopLoss"])
    assert position.avg_entry_price is not None
    assert position.stop_loss is not None
    assert position.stop_loss < position.avg_entry_price
    assert position.cum_realised_pnl == Decimal(row["cumRealisedPnl"])
    # The row's time is in milliseconds; the neutral model counts microseconds.
    assert position.updated_at == int(row["updatedTime"]) * 1000


async def test_the_port_reads_the_working_order_overlay() -> None:
    rows = _rows(_served([ORDERS_OVERLAY], "GET /v5/order/realtime"))

    orders = await make_port(_venue(ORDERS_OVERLAY)).open_orders(account())

    assert len(orders) == 2
    assert [o.exchange_order_id for o in orders] == [row["orderId"] for row in rows]
    assert {(o.symbol, o.side, o.order_type, o.state) for o in orders} == {
        ("BTCUSDT", "buy", "limit", "new")
    }
    assert [o.stop_loss for o in orders] == [Decimal(row["stopLoss"]) for row in rows]
    for order in orders:
        # Each resting buy opens a position, so it carries a native stop below its price (C-2.6).
        assert order.stop_loss is not None
        assert order.price is not None
        assert order.stop_loss < order.price
        assert order.updated_at is not None
        assert order.created_at <= order.updated_at


async def test_the_port_reads_the_history_overlay() -> None:
    port = make_port(_venue(HISTORY_OVERLAY))

    orders = await port.order_history(account())
    fills = await port.executions(account(), NOW_US - DAY_US, NOW_US)

    assert [(o.side, o.order_type, o.state, o.reduce_only) for o in orders] == [
        ("buy", "market", "filled", False),
        ("sell", "market", "filled", True),
    ]
    opening, closing = orders
    assert opening.stop_loss is not None
    assert opening.avg_fill_price is not None
    assert opening.stop_loss < opening.avg_fill_price
    assert closing.stop_loss is None
    assert [fill.exec_type for fill in fills] == ["trade", "trade"]
    assert {fill.fee_rate for fill in fills} == {Decimal("0.00055")}
    assert [fill.exchange_order_id for fill in fills] == [o.exchange_order_id for o in orders]


async def test_the_exposure_read_sees_the_seeded_position_and_orders() -> None:
    surface = _Surface(make_port(_venue(POSITION_OVERLAY, ORDERS_OVERLAY)))

    exposure = await PortReader(surface, "demo", lambda: None).read(ACCOUNT, KEY_ID)

    [position] = exposure.positions
    assert position.symbol == "BTCUSDT"
    assert position.side == "long"
    assert position.size == Decimal("0.001")
    assert position.leverage == Decimal(5)
    assert position.native_stop_present
    assert exposure.working_orders == 2


# -- the models stay strict ----------------------------------------------------------------------


async def test_a_position_row_without_a_required_field_is_refused() -> None:
    path = _path(POSITION_LIST)
    served = _served([POSITION_OVERLAY], POSITION_LIST)
    [position] = await make_port(Venue().on(path, served)).positions(account())
    assert position.symbol == "BTCUSDT"  # the row as the pack serves it reads

    stripped = _served([POSITION_OVERLAY], POSITION_LIST)
    del _rows(stripped)[0]["cumRealisedPnl"]
    with pytest.raises(UnknownStateError):
        await make_port(Venue().on(path, stripped)).positions(account())
