"""E17-Q02 book-channel helpers: what a client holds of one `book.*` channel (§7.1, §7.3), and the
recorded stream that feeds a burst.

`Replica` is a client's reconstruction of a channel from the frames it received, by the §7.1
obligations: a `snap` replaces both sides, a `d` patches them (a size of 0 removes the level), and
a `d` whose `s` is not the last `s` + 1 is a gap, after which nothing is applied until the next
`snap`. It reads structured frames (`e: "j"`). A book subscription defaults to binary
(`ws/topics.py`), so a test that replays one subscribes with `structured`. `BookTap` is a client's
`on_data` for a channel too long to keep as frames: a `Replica` and the disclosure of each `d`.

`Loop` is the book publisher the gateway does not have yet (#604), for a stream of any length. The
`Stack`'s own `book_step` sorts the book's levels four times an update (about 0.5 ms) and ends with
the recording (5 399 updates), so it cannot carry thousands of updates a second. A `Loop` replays
one stretch of the recording, precomputed once: each recorded update that moves the depth-50 window
becomes one body, the `window_delta` from the window before it to the window after it, and a last
body, the bridge, takes the window and the book back to where they began. So the stream has no end,
and every body is a true transition of the server's book, which `publish` keeps in step: what a
snapshot would build equals what a client following the deltas holds.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, NamedTuple

from candleviewer.ws.sequencing import SequencingHub, window_delta
from tests._corpus import frames
from tests.chaos.ws._server import DEPTH, SYM
from tests.unit.ws._seq_support import Book, Source, validate

Topic = dict[str, Any]
Levels = list[list[str]]
Window = tuple[dict[str, str], dict[str, str]]  # bids and asks, price -> size: `Book.top`'s
#: The recorded book (BTCUSDT: the corpus holds one usable book), and the updates a lap replays.
RECORDED = "ws/orderbook_BTCUSDT.jsonl"
LAP = 1000


def structured(ch: str) -> Topic:
    """A topic entry whose frames a `Replica` can read: the default encoding of a book is binary."""
    return {"ch": ch, "opts": {"encoding": "structured"}}


@dataclass
class Replica:
    """One channel as a client rebuilds it. `last` is the `s` of the last frame applied, None
    before the first `snap` and after a gap; `gaps` counts the `d` frames refused for one."""

    bids: dict[str, str] = field(default_factory=dict)
    asks: dict[str, str] = field(default_factory=dict)
    last: int | None = None
    gaps: int = 0

    def feed(self, frame: dict[str, Any]) -> None:
        t, e = frame["t"], frame.get("e")
        assert t in {"snap", "d"} and e == "j", f"a replica reads structured data, got {t} e={e}"
        if t == "snap":
            assert frame["s"] is not None, "a chunked snapshot: the replica cannot assemble chunks"
            self.bids = {p: s for p, s in frame["p"]["bids"]}
            self.asks = {p: s for p, s in frame["p"]["asks"]}
            self.last = frame["s"]
        elif self.last is None or frame["s"] != self.last + 1:
            self.gaps += 1
            self.last = None
        else:
            self.last = frame["s"]
            for side, levels in ((self.bids, frame["p"]["bids"]), (self.asks, frame["p"]["asks"])):
                for price, size in levels:
                    if Decimal(size) == 0:
                        side.pop(price, None)
                    else:
                        side[price] = size

    def matches(self, book: Book, depth: int) -> bool:
        """Both sides equal the server book's best `depth` levels (the window §7.3 keeps exact)."""
        return (self.bids, self.asks) == book.top(depth)


def replay(received: Iterable[dict[str, Any]], ch: str) -> Replica:
    """The replica that `ch`'s data frames leave, in the order the client received them (what a
    `Client` kept in `frames`; control frames and other channels are skipped)."""
    replica = Replica()
    for frame in received:
        if frame.get("ch") == ch and frame["t"] in {"snap", "d"}:
            replica.feed(frame)
    return replica


class Delta(NamedTuple):
    """One `d` of a book channel as the wire has it: its `s`, `coalesced`, and `coalesced_count`
    (None where the frame has none: it carries one update)."""

    s: int
    coalesced: bool
    coalesced_count: int | None


@dataclass
class BookTap:
    """A client's `on_data` for one structured book channel: the `Replica` every `snap` and `d`
    feeds, the disclosure of each `d` (schema-validated), and `updates`, how many source updates
    they carry (a merged window counts as many as it merged)."""

    replica: Replica = field(default_factory=Replica)
    deltas: list[Delta] = field(default_factory=list)
    updates: int = 0

    def __call__(self, frame: dict[str, Any], _text: str | bytes) -> None:
        self.replica.feed(frame)
        if frame["t"] == "d":
            validate(frame)
            body = frame["p"]
            merged = body.get("coalesced_count")
            self.deltas.append(Delta(frame["s"], body["coalesced"], merged))
            self.updates += merged or 1


@dataclass(frozen=True, slots=True)
class _Step:
    """One update of a lap: the window delta that is published, and the raw levels the server's
    book takes with it."""

    body: dict[str, Any]
    bids: Levels
    asks: Levels


@dataclass(frozen=True, slots=True)
class _Lap:
    opening: Window  # the full book the lap starts from
    steps: tuple[_Step, ...]  # `k` recorded updates, then the bridge


@functools.cache
def _recorded() -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """The recording, parsed once: the opening snapshot's data, then each delta's, in order (the
    file holds a second snapshot, a reset, that is not one)."""
    records = [json.loads(f) for f in frames(RECORDED)]
    return records[0]["data"], tuple(r["data"] for r in records[1:] if r["type"] == "delta")


def _body(sym: str, before: Window, after: Window) -> dict[str, Any]:
    """The §7.3 delta that takes a depth window from `before` to `after`."""
    bids, asks = (window_delta(a, b) for a, b in zip(before, after, strict=True))
    return {"symbol": sym, "bids": bids, "asks": asks}


@functools.cache
def _lap(sym: str, start: int, k: int) -> _Lap:
    """`k` updates of the recording from its `start`-th delta, then the bridge, built once per
    process however many `Loop`s replay it (a burst and its control). A delta that moves no level
    of the window is no update (as in the bench feeder): the server's book takes its levels with
    the next one."""
    first, deltas = _recorded()
    book = Book(sym)
    book.apply(first["b"], first["a"])
    for data in deltas[:start]:
        book.apply(data["b"], data["a"])
    opening = (dict(book.bids), dict(book.asks))
    opened = window = book.top(DEPTH)
    steps: list[_Step] = []
    held: tuple[Levels, Levels] = ([], [])  # raw levels of the deltas since the last update
    for data in deltas[start:]:
        book.apply(data["b"], data["a"])
        held[0].extend(data["b"])
        held[1].extend(data["a"])
        after = book.top(DEPTH)
        body = _body(sym, window, after)
        if body["bids"] or body["asks"]:
            steps.append(_Step(body, *held))
            held, window = ([], []), after
            if len(steps) == k:
                break
    assert len(steps) == k, f"the recording has {len(steps)} window updates from delta {start}"
    bridge = _Step(
        _body(sym, window, opened),
        window_delta(book.bids, opening[0]),  # the book, not the window: the lap ends as it began
        window_delta(book.asks, opening[1]),
    )
    return _Lap(opening, (*steps, bridge))


class Loop:
    """The stream of one symbol (module docstring): `k` recorded updates from the recording's
    `start`-th delta, the bridge, and again. Making it puts `source`'s book of `sym` where the lap
    begins; `publish` is the book publisher's part, one update a call."""

    def __init__(self, source: Source, sym: str = SYM, start: int = 0, k: int = LAP) -> None:
        lap = _lap(sym, start, k)
        self.source, self.ch = source, f"book.{sym}.{DEPTH}"
        self.opening, self._steps = lap.opening, lap.steps
        self.book = source.books.setdefault(sym, Book(sym))
        self.book.bids, self.book.asks = dict(lap.opening[0]), dict(lap.opening[1])
        self.published = 0

    def __len__(self) -> int:
        """Updates in a lap: the recorded ones and the bridge."""
        return len(self._steps)

    def publish(self, hub: SequencingHub) -> int:
        """The next update: the server's book takes its levels, then `hub` gets the window delta;
        the subscriptions that took it."""
        step = self._steps[self.published % len(self._steps)]
        self.published += 1
        self.book.apply(step.bids, step.asks)
        self.source.gen += 1  # the shared snapshot cache must not serve the pre-update book
        return hub.publish(self.ch, step.body)
