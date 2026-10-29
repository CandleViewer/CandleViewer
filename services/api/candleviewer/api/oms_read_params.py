"""The OMS read routes' query parameters and cursors (E29-T07 #915, PR 1; 22 `listOrders`,
`listPositions`, `listExecutions`).

Each list's query string is read here, after RBAC, never by FastAPI before the route runs, so a
malformed one is the route's `400 validation_failed` naming each rule that failed (`FieldError`),
and never a probe ahead of the permission check. Unknown parameters are ignored, as on every list.
Only 22's vocabulary passes: the account ids (UUIDs, at most `MAX_ACCOUNTS`, 22 `AccountIdsQuery`),
a `Symbol`, the `OrderState` and `OrderIntent` values, a `limit` of 1 to 500 (default 100), RFC
3339 times with an offset (`from` inclusive, `to` exclusive; `from` after `to` is
`invalid_time_range`), and booleans as `true` or `false`.

A cursor is the trade-group lists' (`api.trade_group_cursor`): opaque, bound to the operation, the
caller and every filter, for one hour. Its position is the last row's time, in microseconds since
the epoch, and id (`Keyset`). A cursor that is malformed, expired, or issued to another caller or
for other filters is `CursorInvalid` here, the route's `400 invalid_cursor`.
"""

from __future__ import annotations

import re
import struct
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, get_args

from starlette.datastructures import QueryParams

from candleviewer.api.trade_group_cursor import decode_cursor, encode_cursor
from candleviewer.oms.errors import FieldError
from candleviewer.storage.repositories.oms_reads import (
    ExecutionQuery,
    Keyset,
    OrderQuery,
    PositionQuery,
)
from candleviewer.storage.repositories.orders import OrderIntent, OrderState

__all__ = [
    "DEFAULT_LIMIT", "MAX_ACCOUNTS", "MAX_LIMIT", "CursorInvalid", "Listing", "ParamsInvalid",
    "closed_pnl_query", "execution_query", "next_cursor", "order_query", "position_query",
    "read_after",
]  # fmt: skip

DEFAULT_LIMIT: Final = 100
MAX_LIMIT: Final = 500
MAX_ACCOUNTS: Final = 25
_SYMBOL: Final = re.compile(r"[A-Z0-9]{2,20}USDT")
_STATES: Final = frozenset[str](get_args(OrderState))
_INTENTS: Final = frozenset[str](get_args(OrderIntent))
_BOOLS: Final = {"true": True, "false": False}
_POSITION: Final = struct.Struct(">q16s")  # microseconds since the epoch, then the id
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_US: Final = timedelta(microseconds=1)


class ParamsInvalid(Exception):
    """A query string 22 refuses: `400` with each rule that failed (`errors`), `validation_failed`
    unless only the window is inverted (`invalid_time_range`). Names no value (C-12.6)."""

    def __init__(self, errors: Sequence[FieldError], code: str = "validation_failed") -> None:
        super().__init__(code)
        self.errors, self.code = tuple(errors), code


class CursorInvalid(Exception):
    """A cursor that is malformed, expired, or another caller's or query's: `400 invalid_cursor`."""


@dataclass(frozen=True, slots=True)
class Listing[Q]:
    """A list's filters, its page size and its cursor as sent; `binding`, the filters a cursor
    is bound to, each as text."""

    query: Q
    limit: int
    cursor: str | None
    binding: tuple[str | None, ...]


class _Reader:
    """Reads one query string, collecting each rule that failed."""

    def __init__(self, params: QueryParams) -> None:
        self.params, self.errors = params, list[FieldError]()

    def fail(self, name: str, rule: str, message: str) -> None:
        self.errors.append(FieldError(name, rule, message))

    def one(self, name: str) -> str | None:
        values = self.params.getlist(name)
        if len(values) > 1:
            self.fail(name, "single", f"Send `{name}` at most once.")
        return values[0] if values else None

    def parsed[T](self, name: str, parse: Callable[[str], T], rule: str, message: str) -> T | None:
        raw = self.one(name)
        if raw is None:
            return None
        try:
            return parse(raw)
        except ValueError:
            self.fail(name, rule, message)
            return None

    def ident(self, name: str) -> uuid.UUID | None:
        return self.parsed(name, uuid.UUID, "uuid", f"`{name}` is a UUID.")

    def flag(self, name: str, default: bool) -> bool:
        found = self.parsed(name, _bool, "boolean", f"`{name}` is `true` or `false`.")
        return default if found is None else found

    def accounts(self) -> tuple[uuid.UUID, ...]:
        raw = self.params.getlist("exchange_account_ids")
        if len(raw) > MAX_ACCOUNTS:
            self.fail("exchange_account_ids", "max_items", f"Name at most {MAX_ACCOUNTS}.")
        found: list[uuid.UUID] = []
        for value in raw:
            try:
                found.append(uuid.UUID(value))
            except ValueError:
                self.fail("exchange_account_ids", "uuid", "Each account id is a UUID.")
        return tuple(dict.fromkeys(found))

    def symbol(self) -> str | None:
        raw = self.one("symbol")
        if raw is not None and _SYMBOL.fullmatch(raw) is None:
            self.fail("symbol", "pattern", "A USDT linear perpetual symbol, such as BTCUSDT.")
            return None
        return raw

    def members(self, name: str, allowed: frozenset[str]) -> frozenset[str]:
        raw = frozenset(self.params.getlist(name))
        if not raw <= allowed:
            self.fail(name, "enum", f"Each `{name}` is one of 22's values.")
        return raw & allowed

    def window(self) -> tuple[datetime | None, datetime | None]:
        message = "An RFC 3339 time with its offset."
        since = self.parsed("from", _instant, "date_time", message)
        until = self.parsed("to", _instant, "date_time", message)
        return since, until

    def limit(self) -> int:
        message = f"An integer from 1 to {MAX_LIMIT}."
        found = self.parsed("limit", _integer, "range", message)
        if found is not None and not 1 <= found <= MAX_LIMIT:
            self.fail("limit", "range", message)
        return DEFAULT_LIMIT if found is None else found

    def done(self, since: datetime | None, until: datetime | None) -> None:
        if self.errors:
            raise ParamsInvalid(self.errors)
        if since is not None and until is not None and since > until:
            message = "`from` is after `to`."
            raise ParamsInvalid((FieldError("from", "before_to", message),), "invalid_time_range")


def _bool(raw: str) -> bool:
    if raw not in _BOOLS:
        raise ValueError(raw)
    return _BOOLS[raw]


def _integer(raw: str) -> int:
    if re.fullmatch(r"[0-9]{1,4}", raw) is None:
        raise ValueError(raw)
    return int(raw)


def _instant(raw: str) -> datetime:
    """An RFC 3339 time with an offset (`Z` too), to the microsecond; a naive one is refused."""
    found = datetime.fromisoformat(raw)
    if "T" not in raw.upper() or found.utcoffset() is None:
        raise ValueError(raw)
    return found.astimezone(UTC)


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _times(since: datetime | None, until: datetime | None) -> tuple[str | None, str | None]:
    return (
        None if since is None else since.isoformat(),
        None if until is None else until.isoformat(),
    )


def order_query(params: QueryParams) -> Listing[OrderQuery]:
    """22 `listOrders`' parameters, else `ParamsInvalid`."""
    read = _Reader(params)
    accounts, symbol = read.accounts(), read.symbol()
    states = frozenset(s for s in get_args(OrderState) if s in read.members("state", _STATES))
    intents = frozenset(i for i in get_args(OrderIntent) if i in read.members("intent", _INTENTS))
    group, open_only = read.ident("trade_group_id"), read.flag("open_only", False)
    since, until = read.window()
    limit, cursor = read.limit(), read.one("cursor")
    read.done(since, until)
    query = OrderQuery(
        accounts=accounts, symbol=symbol, states=states, intents=intents, trade_group_id=group,
        open_only=open_only, since=since, until=until,
    )  # fmt: skip
    binding = (
        ",".join(sorted(map(str, accounts))), symbol, ",".join(sorted(states)),
        ",".join(sorted(intents)), _text(group), str(open_only), *_times(since, until),
    )  # fmt: skip
    return Listing(query, limit, cursor, binding)


def execution_query(params: QueryParams) -> Listing[ExecutionQuery]:
    """22 `listExecutions`' parameters, else `ParamsInvalid`."""
    read = _Reader(params)
    accounts, symbol = read.accounts(), read.symbol()
    order, group = read.ident("order_id"), read.ident("trade_group_id")
    since, until = read.window()
    limit, cursor = read.limit(), read.one("cursor")
    read.done(since, until)
    query = ExecutionQuery(
        accounts=accounts, symbol=symbol, order_id=order, trade_group_id=group, since=since,
        until=until,
    )  # fmt: skip
    binding = (
        ",".join(sorted(map(str, accounts))), symbol, _text(order), _text(group),
        *_times(since, until),
    )  # fmt: skip
    return Listing(query, limit, cursor, binding)


def closed_pnl_query(params: QueryParams) -> Listing[ExecutionQuery]:
    """22 `listClosedPnl`'s parameters, else `ParamsInvalid`."""
    read = _Reader(params)
    accounts, symbol = read.accounts(), read.symbol()
    since, until = read.window()
    limit, cursor = read.limit(), read.one("cursor")
    read.done(since, until)
    query = ExecutionQuery(accounts=accounts, symbol=symbol, since=since, until=until)
    binding = (",".join(sorted(map(str, accounts))), symbol, *_times(since, until))
    return Listing(query, limit, cursor, binding)


def position_query(params: QueryParams) -> tuple[PositionQuery, bool]:
    """22 `listPositions`' parameters and its `aggregate` flag, else `ParamsInvalid`."""
    read = _Reader(params)
    accounts, symbol = read.accounts(), read.symbol()
    open_only, aggregate = read.flag("open_only", True), read.flag("aggregate", False)
    read.done(None, None)
    return PositionQuery(accounts=accounts, symbol=symbol, open_only=open_only), aggregate


def read_after[Q](
    listing: Listing[Q], operation: str, caller: uuid.UUID, now: int
) -> Keyset | None:
    """The page's start: None for the first page, else the cursor's `Keyset`; `CursorInvalid`
    for a cursor that is malformed, expired, or another caller's or query's (module docstring)."""
    if listing.cursor is None:
        return None
    raw = decode_cursor(listing.cursor, operation, caller, listing.binding, now)
    if raw is None or len(raw) != _POSITION.size:
        raise CursorInvalid
    micros, key = _POSITION.unpack(raw)
    try:
        return Keyset(_EPOCH + micros * _US, uuid.UUID(bytes=key))
    except OverflowError:  # a position no `datetime` holds: forged
        raise CursorInvalid from None


def next_cursor[Q](
    listing: Listing[Q], operation: str, caller: uuid.UUID, last: Keyset, now: int
) -> str:
    """The cursor of the page after `last`, bound as `read_after` reads it."""
    micros = (last.at - _EPOCH) // _US
    position = _POSITION.pack(micros, last.id.bytes)
    return encode_cursor(operation, caller, listing.binding, position, now)
