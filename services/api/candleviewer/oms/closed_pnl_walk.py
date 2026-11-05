"""The closed-PnL walk (E29-S06 #981 slice 5a; 24 Sec.8.13 step 3).

`walk` reads one key's stored fills, the key being (account, symbol, the `position_idx` of the
fill's order row), from its last flat the venue confirmed, and gives each fill that closes its `c`,
the shares it takes of the entry value and of the opening fees, its fee's closing share, and the
position's average entry, `opened_at` and the trade groups its opening fills' orders name. It is
pure: no I/O, no log and no clock. Nothing imports it yet: the composition slice reads its inputs
(21 Sec.13.1 rows 57 and 58), composes a record's figures from its closes and logs.

- **Start.** The latest confirmed flat dated before `anchor`, the first stored fill of the
  record's order. With none the walk has no start and gives nothing, never the key's first fill.
- **Fills.** In `(exec_ts, exec_id)` order. A fill opens when the walk is flat or holds its
  side, adding its size, size x price and fee. A fill of the other side closes
  `c = min(exec_qty, open size)`, which a `closedSize` it states must equal, and takes
  `c / open size` of the entry value and of the opening fees; its remainder opens the other side,
  and its fee is split between the two pro rata by size.
- **Flats.** A confirmed flat comes after every fill dated at or before it, and each one the
  walk crosses drops what it holds.
- **Unreadable fills.** A fill of the other side with no closed PnL, one larger than the open size
  that states no `closedSize`, and, in hedge mode, a fill with no order row: until the walk next
  goes flat, each close gives its `c` and closing fee share only. The walk goes flat at a
  confirmed flat, after a fill that leaves it no size, or where a fill it reads closes all it
  holds; the remainder of a fill it cannot read opens unreadable. The first, a REST-recovered
  fill, leaves the walk sure of its count of sizes, so its closes stay `sizes_sure`; the other
  two put that count in doubt until the walk next goes flat, and a fill of the first kind does
  not lift the doubt.
- **Disagreement.** A stated `closedSize` the walk disagrees with, above 0 on a fill that
  opens or other than `c` on one of the other side: until a confirmed flat after it, never one
  of the walk's own count, each close is `disagreeing`, unreadable and not `sizes_sure`, its
  record has no local figures, and `c` stays `min(exec_qty, open size)` whatever the fill states.
- **Finality.** The composition decides it per record from the flags of that record's closes,
  never from `clean`, which speaks for the whole walk: a span after them does not touch them.
- **Bounds (C-2.18).** A walk handed more fills or flats than its `WalkBudget` is `capped`: it
  gives nothing, never a part, and is never `clean`. Its caller reads one row past each budget,
  so a capped walk knows more are stored, and logs.
- **Rounding.** Every sum, difference and product is exact, and a division alone rounds, at its
  80th digit, so the shares a position's closes take sum to what it held to the last digit, and
  nothing is quantized. The composition quantizes each local figure once, `ROUND_HALF_UP` to
  8 dp (24 Sec.1.5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Context, Decimal, localcontext
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

from candleviewer.storage.repositories.closed_pnl import WalkFill

#: Exact for every sum, difference and product the walk takes: from `numeric(38,18)` values and
#: 80-digit quotients, they span about 200 digits.
_EXACT: Final = Context(prec=400)
#: A division rounds at its 80th digit, as the sync's merge does.
_WIDE: Final = Context(prec=80)
_ZERO: Final = Decimal(0)
_NO_GROUPS: Final[Mapping[UUID, UUID]] = MappingProxyType({})
_Mode = Literal["read", "no_pnl", "unreadable", "disagreeing"]  # each graver than the last


@dataclass(frozen=True, slots=True)
class WalkBudget:
    """The most fills and the most flats one walk takes (C-2.18)."""

    fills: int
    flats: int

    def __post_init__(self) -> None:
        if self.fills < 1 or self.flats < 1:
            raise ValueError("a walk's budget is at least one fill and one flat")


@dataclass(frozen=True, slots=True, kw_only=True)
class WalkClose:
    """A fill that closes: `closed` is its `c` and `closing_fee` its fee's closing share. The
    entry value and the opening fees it takes, the position's average entry and `opened_at` are
    None while it is `unreadable`; a `disagreeing` close is unreadable too, and its record has no
    local figures. `sizes_sure` when the walk trusts the open size it counts, and so the close's
    `c`: a fill with no closed PnL leaves it trusted (module docstring). `groups` are the trade
    groups the position's opening fills' orders name."""

    fill: WalkFill
    closed: Decimal
    closing_fee: Decimal
    entry_value: Decimal | None
    opening_fees: Decimal | None
    #: At this close; a record's is sum(entry_value) / sum(closed) of its closes, never their mean.
    avg_entry: Decimal | None
    opened_at: datetime | None
    groups: frozenset[UUID]
    unreadable: bool
    sizes_sure: bool
    disagreeing: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Walk:
    """`start` is the confirmed flat the walk starts at, None with no start or when `capped`, and
    `open_size` what it holds at its end. `clean` when it has a start, stays within its budget and
    reads every fill it walks, none unreadable and none disagreeing. With no `start`, capped or
    not, it gives no closes and its `open_size` means nothing: read `capped` and `start` first."""

    start: datetime | None
    closes: tuple[WalkClose, ...] = ()
    open_size: Decimal = _ZERO
    capped: bool = False
    clean: bool = False


@dataclass(slots=True)
class _Held:
    """What the walk holds, and whether it reads it."""

    side: str | None = None
    size: Decimal = _ZERO
    value: Decimal = _ZERO
    fees: Decimal = _ZERO
    opened_at: datetime | None = None
    groups: set[UUID] = field(default_factory=set)
    mode: _Mode = "read"

    def drop(self, mode: _Mode = "read") -> None:
        """A flat of the walk: the size, entry value, opening fees, `opened_at` and groups go."""
        self.side, self.size, self.value, self.fees = None, _ZERO, _ZERO, _ZERO
        self.opened_at, self.groups, self.mode = None, set(), mode


def walk(
    fills: Sequence[WalkFill],
    flats: Sequence[datetime],
    *,
    anchor: datetime,
    position_idx: int,
    hedged: bool,
    budget: WalkBudget,
    order_groups: Mapping[UUID, UUID] = _NO_GROUPS,
) -> Walk:
    """The walk of the key at `position_idx`: `fills` are its stored trade fills (row 58),
    `flats` its confirmed flats (row 57), `anchor` the time of the record's order's first stored
    fill, `hedged` whether the account holds the symbol in hedge mode (a key at `position_idx` 1
    or 2 is), and `order_groups` the trade group each order row's leg names, by the row's id."""
    if position_idx not in (0, 1, 2):
        raise ValueError("cpr_posidx: position_idx is 0, 1 or 2")
    if len(fills) > budget.fills or len(flats) > budget.flats:
        return Walk(start=None, capped=True)
    if len({fill.exec_id for fill in fills}) < len(fills):
        raise ValueError("a walk reads each fill once")
    start = max((at for at in flats if at < anchor), default=None)
    if start is None:
        return Walk(start=None)
    keyed = sorted(
        (f for f in fills if f.exec_ts > start and _on_key(f, position_idx)),
        key=lambda f: (f.exec_ts, f.exec_id),
    )
    ahead = iter(sorted(at for at in flats if at > start))
    flat, held, clean, hedge = next(ahead, None), _Held(), True, hedged or position_idx != 0
    closes: list[WalkClose] = []
    with localcontext(_EXACT):
        for fill in keyed:
            while flat is not None and flat < fill.exec_ts:  # after the fills at or before it
                held.drop()
                flat = next(ahead, None)
            orphan = hedge and fill.order_id is None
            clean = _step(held, fill, orphan, order_groups, closes) and clean
        if flat is not None:
            held.drop()
    return Walk(start=start, closes=tuple(closes), open_size=held.size, clean=clean)


def _on_key(fill: WalkFill, position_idx: int) -> bool:
    """The key's fills: its order row's `position_idx` is the key's, or it has no order row."""
    return fill.order_id is None or fill.order_position_idx == position_idx


def _step(
    held: _Held,
    fill: WalkFill,
    orphan: bool,
    order_groups: Mapping[UUID, UUID],
    closes: list[WalkClose],
) -> bool:
    """One fill, opening or closing (module docstring): whether the walk read it."""
    qty, stated = fill.exec_qty, fill.closed_size
    if held.size == 0 or fill.side == held.side:
        read = _enter(held, unreadable=orphan, disagrees=stated is not None and stated > 0)
        _open(held, fill, qty, fill.exec_fee, order_groups)
        return read
    c = min(qty, held.size)
    unreadable = orphan or (qty > held.size and stated is None)
    no_pnl, disagrees = fill.closed_pnl is None, stated is not None and stated != c
    read = _enter(held, unreadable=unreadable, disagrees=disagrees, no_pnl=no_pnl)
    value, fees = _share(held.value, c, held.size), _share(held.fees, c, held.size)
    closing_fee, known = _share(fill.exec_fee, c, qty), held.mode == "read"
    closes.append(
        WalkClose(
            fill=fill,
            closed=c,
            closing_fee=closing_fee,
            entry_value=value if known else None,
            opening_fees=fees if known else None,
            avg_entry=_WIDE.divide(held.value, held.size) if known else None,
            opened_at=held.opened_at if known else None,
            groups=frozenset(held.groups),
            unreadable=not known,
            sizes_sure=held.mode in ("read", "no_pnl"),
            disagreeing=held.mode == "disagreeing",
        )
    )
    held.size, held.value, held.fees = held.size - c, held.value - value, held.fees - fees
    rest = qty - c
    if held.size == 0:  # its own flat: it ends an unreadable span, unless this fill carries it
        keep = held.mode == "disagreeing" or (not read and rest > 0)  # never a disagreement
        held.drop(held.mode if keep else "read")
    if rest > 0:
        _open(held, fill, rest, fill.exec_fee - closing_fee, order_groups)
    return read


def _enter(held: _Held, *, unreadable: bool, disagrees: bool, no_pnl: bool = False) -> bool:
    """The disagreement span on a disagreeing `closedSize`, else the unreadable span on a fill that
    puts the walk's count of sizes in doubt, else the span of a fill with no closed PnL, which
    leaves it sure; a span gives way only to a graver one. Whether the walk read the fill."""
    if disagrees:
        held.mode = "disagreeing"
    elif unreadable and held.mode in ("read", "no_pnl"):
        held.mode = "unreadable"
    elif no_pnl and held.mode == "read":
        held.mode = "no_pnl"
    return not (unreadable or disagrees or no_pnl)


def _open(
    held: _Held, fill: WalkFill, size: Decimal, fee: Decimal, order_groups: Mapping[UUID, UUID]
) -> None:
    """`size` of the fill opens the position on its side, or adds to it, with `fee`."""
    if held.size == 0:
        held.side, held.opened_at = fill.side, fill.exec_ts
    held.size, held.value = held.size + size, held.value + size * fill.exec_price
    held.fees += fee
    if fill.order_id is not None and (group := order_groups.get(fill.order_id)) is not None:
        held.groups.add(group)


def _share(amount: Decimal, part: Decimal, whole: Decimal) -> Decimal:
    """`part / whole` of `amount`, and all of it for the whole, so a position's shares sum to it."""
    return amount if part == whole else _WIDE.divide(amount * part, whole)
