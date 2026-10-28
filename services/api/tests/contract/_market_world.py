"""E12-Q04 (#420): the fixture-backed market app the contract suite drives.

`GET /market/klines` and `GET /market/bars` composed as `create_app` composes them, error redaction
included (without it FastAPI's own 422 is no `Problem`), over recorded data only (C-13.5): the
bars the real builders make from the recorded BTCUSDT tape, as `test_market_bars_contract` builds
them (renko by the real `RenkoBarBuilder` here), and the recorded BTCUSDT 1m kline pages, as
`test_market_klines_contract` reads them. Nothing leaves the process: a `TestClient`, or
Schemathesis, calls the app.

The caller is its `Authorization` header: `Bearer reader` holds exactly the permissions both
operations' `x-rbac` names, `Bearer other` every other permission an operation of 22 names, and
no header (or any other) is no session. A support module (no `test_` prefix): pytest collects
nothing from it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from functools import cache
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api import market_response
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.bars.errors import BarSpecError
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, row_key
from candleviewer.bars.renko_builder import RenkoBarBuilder
from candleviewer.bars.rows import bar_param_for, bar_row
from candleviewer.bars.spec import from_wire
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.ingestion.kline_read import KlineReadService
from tests.contract._generated_contract import SPEC
from tests.contract.test_market_bars_contract import _NOW, _SERIES, _T0, _TAPE, _build, _tape_totals
from tests.contract.test_market_bars_contract import _P as _BARS_P
from tests.contract.test_market_klines_contract import _P as _KLINES_P
from tests.contract.test_market_klines_contract import _corpus, _Hot, _Kline
from tests.unit.bars._trades import final_bars

SYMBOL: Final = "BTCUSDT"
OPERATIONS: Final = ("getKlines", "getBars")
READER: Final[Mapping[str, str]] = {"Authorization": "Bearer reader"}
OTHER: Final[Mapping[str, str]] = {"Authorization": "Bearer other"}
NO_SESSION: Final[Mapping[str, str]] = {}
#: Recording starts at the tape's first print; `/market/bars` reads at `NOW` (an hour after its
#: last), `/market/klines` at `KLINES_NOW_US` (2023-11-16T02:00Z, after the kline corpus).
T0: Final = _T0
NOW: Final = _NOW
KLINES_NOW_US: Final = 1_700_100_000_000_000
#: The instrument catalogue's BTCUSDT answers (`rest/instruments_before.json`).
TICK: Final = Decimal("0.10")
QTY_STEP: Final = Decimal("0.001")
#: A 200 base query per operation: the whole tape (bars), the whole kline corpus (klines).
BASE: Final[Mapping[str, Mapping[str, object]]] = {"getBars": _BARS_P, "getKlines": _KLINES_P}
#: A row of getBars's param table: `| \`bar_type\` | meaning | \`example\` [/ \`example\`] |`.
_ROW: Final = re.compile(r"^\s*\|\s*`(?P<type>\w+)`\s*\|[^|\n]*\|(?P<example>[^|\n]*)\|\s*$", re.M)


def operation(op_id: str) -> tuple[str, dict[str, Any]]:
    """`(path, operation)` of the GET `op_id` in 22."""
    for path, item in SPEC["paths"].items():
        op = item.get("get")
        if isinstance(op, dict) and op.get("operationId") == op_id:
            return path, op
    raise LookupError(f"22 has no GET operation {op_id}")


def required_permissions() -> frozenset[str]:
    """The `x-rbac` permissions of both operations (they name the same ones)."""
    (perms,) = {frozenset(operation(op)[1]["x-rbac"]["permissions"]) for op in OPERATIONS}
    return perms


def other_permissions() -> frozenset[str]:
    """Every permission an operation of 22 names, but those two operations need."""
    named = {
        perm
        for item in SPEC["paths"].values()
        for op in item.values()
        if isinstance(op, dict)
        for perm in op.get("x-rbac", {}).get("permissions", ())
    }
    return frozenset(named - required_permissions() - {"*"})


def bar_type_params() -> list[tuple[str, str]]:
    """Each `(bar_type, param)` 22 documents: every `BarType` value with each example of its row
    in getBars's param table (`renko` has two). A value without a row fails here, at collection."""
    table = _ROW.finditer(operation("getBars")[1]["description"])
    rows = {m["type"]: re.findall(r"`([^`]+)`", m["example"]) for m in table}
    found: list[tuple[str, str]] = []
    for bar_type in SPEC["components"]["schemas"]["BarType"]["enum"]:
        if not rows.get(bar_type):
            raise LookupError(f"BarType {bar_type!r} has no example in getBars's param table")
        found += [(bar_type, param) for param in rows[bar_type]]
    return found


def _bars(spec: BarSpec) -> list[Bar]:
    """The tape's bars of `spec`, the trailing forming one included (`final_bars`)."""
    if spec.kind != "renko":
        return _build(spec)
    builder = RenkoBarBuilder(spec, SYMBOL, lambda _symbol: TICK)
    return final_bars(u for t in _TAPE for u in builder.on_trade(t))


@cache
def stored_rows() -> dict[str, list[dict[str, object]]]:
    """`bar_param` -> the stored rows, in key order: each documented pair `from_wire` takes (a
    builder exists for it) and the denser series of `test_market_bars_contract`."""
    specs: dict[str, BarSpec] = {}
    for bar_type, param in [*bar_type_params(), *_SERIES]:
        try:
            spec = from_wire(bar_type, param)
        except BarSpecError:  # pnf, heikin_ashi and ATR renko: no builder, nothing stored
            continue
        specs[bar_param_for(spec)] = spec
    return {
        key: sorted((bar_row(b, spec, generation=0) for b in _bars(spec)), key=row_key)
        for key, spec in specs.items()
    }


class _Rows:
    """`RowFetcher` over `stored_rows()`: the reader's range query (symbol, bar_param, start, to
    and, for a non-time cursor, the #2017 key binds; `LIMIT` inlined), evaluated as QuestDB
    would (`test_market_bars_contract._Fetch`, over this store). Down, it refuses the read."""

    def __init__(self, world: MarketWorld) -> None:
        self._world = world

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self._world.reads += 1
        if self._world.outage:
            raise ConnectionError("questdb down")
        symbol, bar_param, start, to = params[:4]
        start_us, to_us = ts_us_from_row(start), ts_us_from_row(to)
        key = None
        if len(params) == 9:
            index = -1 if "IS NULL" in sql else int(str(params[8]))
            key = (ts_us_from_row(params[4]), int(str(params[6])), index)
        rows = [
            r
            for r in stored_rows().get(str(bar_param), [])
            if r["symbol"] == symbol and start_us <= int(str(r["ts"])) < to_us
            and (key is None or row_key(r) >= key)
        ]  # fmt: skip
        return rows[: int(sql.rsplit("LIMIT ", 1)[1])]


class _CountedHot(_Hot):
    """The recorded kline pages as the hot tier, each read counted."""

    def __init__(self, world: MarketWorld) -> None:
        super().__init__(_corpus())
        self._world = world

    async def read_klines(
        self, sym: str, interval: str, rng: Any, tier: str = "auto", limit: int | None = None
    ) -> list[_Kline]:
        self._world.reads += 1
        return await super().read_klines(sym, interval, rng, tier, limit)


class Resolver:
    """The caller of a request, by its `Authorization` header (module docstring)."""

    def __init__(self) -> None:
        self._grants = {
            READER["Authorization"]: required_permissions(),
            OTHER["Authorization"]: other_permissions(),
        }

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        grant = self._grants.get(request.headers.get("authorization", ""))
        return None if grant is None else MarketDataPrincipal("e12-q04", grant)


async def _recording_started(symbol: str) -> int | None:
    return T0 if symbol == SYMBOL else None


async def _no_rebuild(*_: object) -> None: ...


def _listed(symbol: str) -> bool:
    return symbol == SYMBOL


def _qty_step(symbol: str) -> Decimal | None:
    return QTY_STEP if symbol == SYMBOL else None


class MarketWorld:
    """One app over the recorded data, with a count of its storage reads. `outage`: the stores
    are down (QuestDB refuses the bars read; the klines storage is not composed), so each route
    answers 503 `store_unavailable`."""

    def __init__(self, *, outage: bool = False) -> None:
        self.outage, self.reads = outage, 0
        resolver = Resolver()
        reader = BarReader(_Rows(self), _no_rebuild)
        klines = KlineReadService(_CountedHot(self), recording_started_at_us=_recording_started)
        self.app = FastAPI()
        install_error_redaction(self.app)
        self.app.include_router(
            make_market_bars_router(
                lambda: reader, recording_started_at_us=_recording_started,
                trade_totals=_tape_totals, principal_resolver=resolver, symbol_listed=_listed,
                qty_step=_qty_step, now_us=lambda: NOW,
            )
        )  # fmt: skip
        self.app.include_router(
            make_market_router(
                lambda: None if self.outage else _Hot([]), principal_resolver=resolver,
                read_service_provider=lambda: klines, symbol_listed=_listed,
                now_us=lambda: KLINES_NOW_US,
            )
        )  # fmt: skip
        self.client = TestClient(self.app, client=("127.0.0.1", 50000))

    def get(
        self, op_id: str, query: Mapping[str, object], headers: Mapping[str, str] = READER
    ) -> httpx.Response:
        path, _ = operation(op_id)
        resp: httpx.Response = self.client.get(path, params=dict(query), headers=dict(headers))
        return resp


@contextmanager
def response_ceiling(max_bytes: int | None) -> Iterator[None]:
    """`RESPONSE_MAX_BYTES` (SR-E12-01) lowered to `max_bytes` while inside, so a page answers
    422 `response_too_large`; `None` keeps the real ceiling."""
    with pytest.MonkeyPatch.context() as mp:
        if max_bytes is not None:
            mp.setattr(market_response, "RESPONSE_MAX_BYTES", max_bytes)
        yield
