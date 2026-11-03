"""#2014 BI-1: N non-time bars that share one open time survive every path, keyed by index.

Storage and REST (the DDL dedup key, `BarReader` and its keyset paging), the WS snapshot
(`BarsSnapshotSource`, both encodings) and the WS deltas (`BarsPublisher` into `CoalescingQueue`,
structured and kind-4). The builders are the real ones: one volume print spanning N thresholds, or
2N tick prints at one microsecond, close N bars at one `open_time`; the open remainder is the
(N+1)th, the forming bar, which every WS check re-emits mid-window.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarReader, row_key
from candleviewer.bars.rows import bar_row, row_checksum
from candleviewer.bars.series_store import SeriesStore
from candleviewer.bars.spec import to_wire
from candleviewer.bars.writer import BarWriter
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.binary import BARS, Frame, decode, encode
from candleviewer.ws.coalescing import CoalescingQueue
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws.topics import effective_options, parse_topic
from tests.unit.bars._trades import SYM, final_bars, trade
from tests.unit.bars.test_bars_key_by_index import _DedupStore, _sched
from tests.unit.ws._seq_support import Conn, Source

T0 = 1_700_000_000_000_000
VOL, TICK = (
    BarSpec(kind="volume", volume_threshold=Decimal("1500")),
    BarSpec(kind="tick", tick_count=2),
)
Series = tuple[BarSpec, list[list[BarUpdate]]]  # the spec and one emission per print

_N = st.integers(min_value=2, max_value=20)
_GEN = st.integers(min_value=0, max_value=2)
_KIND = st.sampled_from(["volume", "tick"])
#: A drawn trade size: at most 3 dp, so `Decimal(repr(float))` in rows.py round-trips it exactly.
_SIZE = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1499.999"), places=3)


def _series(kind: str, n: int, size: Decimal) -> Series:
    """N closed bars at one open time, then a forming bar, as the builder emits them. `size` is
    the forming bar's volume (volume kind: one print of N thresholds plus `size`) or every
    tick print's quantity."""
    if kind == "volume":
        vol = VolumeBarBuilder(VOL, SYM)
        return VOL, [list(vol.on_trade(trade(T0, qty=n * 1500 + size)))]
    tick = TickBarBuilder(TICK, SYM)
    return TICK, [list(tick.on_trade(trade(T0, qty=size, seq=i))) for i in range(2 * n + 1)]


def _bars(emissions: list[list[BarUpdate]]) -> list[Bar]:
    return final_bars(u for ems in emissions for u in ems)


def _checked(kind: str, n: int, size: Decimal) -> tuple[BarSpec, list[list[BarUpdate]], list[Bar]]:
    spec, emissions = _series(kind, n, size)
    bars = _bars(emissions)
    assert len(bars) == n + 1 and sum(b.closed for b in bars) == n  # the setup is what is claimed
    assert len({b.open_time for b in bars}) == 1  # one open time: only (generation, index) differ
    assert [b.index for b in bars] == sorted({b.index for b in bars})
    return spec, emissions, bars


def _distinct_keys(items: list[dict[str, Any]], gen: int, want: list[int]) -> None:
    keys = [(b["generation"], b["index"]) for b in items]
    assert len(set(keys)) == len(keys) and keys == [(gen, i) for i in want]


# -- (a) storage and REST -------------------------------------------------------------------


class _QueryStore(_DedupStore):
    """A `fetch` that evaluates the reader's own query on the stored rows: the symbol/param and
    `ts >= $3 AND ts < $4` window, the #2017 keyset predicate (`_KEY_FROM`, or `_KEY_FROM_NULL`
    when the SQL carries `IS NULL`) expanded over the bound args, `ORDER BY ts, generation,
    "index"` (NULL index first) and `LIMIT`. `_DedupStore.fetch` ignores all of it.

    Real-QuestDB evidence for the same predicate and paging: tests/integration/storage/
    test_questdb_bars_keyset.py::test_same_ts_renko_bricks_page_by_key_on_real_questdb.
    """

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        assert 'ORDER BY ts, generation, "index"' in sql and len(params) in (4, 9)
        symbol, param, lo, hi = params[:4]
        rows = [
            r
            for r in self.rows.values()
            if r["symbol"] == symbol
            and r["bar_param"] == param
            and ts_us_from_row(lo) <= ts_us_from_row(r["ts"]) < ts_us_from_row(hi)
        ]
        if len(params) == 9:  # (ts > $5 OR (ts = $6 AND (gen > $7 OR (gen = $8 AND idx >= $9))))
            ts5, ts6, gen7, gen8, idx9 = (
                ts_us_from_row(params[4]),
                ts_us_from_row(params[5]),
                *(int(str(p)) for p in params[6:]),
            )
            null_ok = "IS NULL" in sql

            def keep(r: dict[str, object]) -> bool:
                ts, gen, idx = ts_us_from_row(r["ts"]), int(str(r["generation"])), r["index"]
                idx_ok = (idx is None and null_ok) or (idx is not None and int(str(idx)) >= idx9)
                return ts > ts5 or (ts == ts6 and (gen > gen7 or (gen == gen8 and idx_ok)))

            rows = [r for r in rows if keep(r)]
        rows.sort(key=lambda r: (ts_us_from_row(r["ts"]), *row_key(r)[1:]))
        return rows[: int(sql.rsplit("LIMIT ", 1)[1])]


@settings(max_examples=40, deadline=None, derandomize=True)
@given(kind=_KIND, n=_N, gen=_GEN, size=_SIZE, data=st.data())
def test_same_open_time_bars_round_trip_storage_and_page_by_key(
    kind: str, n: int, gen: int, size: Decimal, data: st.DataObject
) -> None:
    spec, _, bars = _checked(kind, n, size)
    closed = [b for b in bars if b.closed]
    limit = data.draw(st.integers(min_value=1, max_value=n - 1))  # page size strictly below N

    async def run() -> tuple[int, list[dict[str, object]], list[list[object]]]:
        store = _QueryStore()
        writer = BarWriter(store, batch_rows=3)
        await writer.start()
        await writer.submit(closed, spec, generation=gen)
        assert await writer.stop() == 0
        stored = len(store.rows)
        for dts in (-1, 1):  # decoys just outside the [T0, T0 + 1) window, same key columns
            for b in closed[:2]:
                row = {**bar_row(b, spec, generation=gen), "ts": T0 + dts}
                row["row_checksum"] = row_checksum(row)
                store.rows[(row["ts"], SYM, row["bar_param"], gen, b.index)] = row
        reader = BarReader(store, _sched)
        page = await reader.read_bars(SYM, spec, T0, T0 + 1, 100)
        pages, key = [], None
        for _ in range(2 * n + 2):  # keyset paging: `limit + 1` rows, the extra one is the cursor
            part = await reader.read_bars(SYM, spec, T0, T0 + 1, limit + 1, at_key=key)
            nxt = part.next_key
            pages.append([r["index"] for r in part.rows if nxt is None or row_key(r) < nxt])
            if (key := nxt) is None:
                break
        else:
            raise AssertionError("paging did not terminate")
        return stored, page.rows, pages

    stored, rows, pages = asyncio.run(run())
    want = [b.index for b in closed]
    assert stored == n  # (ts, symbol, bar_param) alone would have collapsed them to one
    assert [r["index"] for r in rows] == want and {r["generation"] for r in rows} == {gen}
    assert sum(Decimal(repr(r["volume"])) for r in rows) == sum(b.volume for b in closed)  # BI-1
    assert [i for p in pages for i in p] == want  # no skip and no repeat at any page size < N
    assert all(len(p) <= limit for p in pages) and len(pages) > 1


@settings(max_examples=20, deadline=None, derandomize=True)
@given(n=_N, gen=_GEN, size=_SIZE)
def test_a_rewrite_of_the_same_bars_upserts_and_another_generation_keeps_both(
    n: int, gen: int, size: Decimal
) -> None:
    """The DDL key is `(ts, symbol, bar_param, generation, index)`: a replay is idempotent and a
    rebuild's generation never overwrites the pinned one."""
    spec, _, bars = _checked("volume", n, size)
    closed = [b for b in bars if b.closed]

    async def run() -> int:
        store = _DedupStore()
        writer = BarWriter(store, batch_rows=5)
        await writer.start()
        for g in (gen, gen, gen + 1):
            await writer.submit(closed, spec, generation=g)
        assert await writer.stop() == 0
        return len(store.rows)

    assert asyncio.run(run()) == 2 * n
    rows = [bar_row(b, spec, generation=gen) for b in closed]
    assert len({r["row_checksum"] for r in rows}) == n and all(
        r["row_checksum"] == row_checksum(r) for r in rows
    )


# -- (b) WS snapshot ------------------------------------------------------------------------


def _channel(spec: BarSpec) -> str:
    bar_type, param = to_wire(spec)
    return f"bars.{SYM}.{bar_type}.{param}"


def _sub(spec: BarSpec, **opts: Any) -> Subscription:
    topic = parse_topic(_channel(spec))
    return Subscription("s_01", topic, opts, effective_options(topic, opts))


def _binary_items(frames: tuple[Frame, ...]) -> list[dict[str, Any]]:
    """The records as a client reads them: encoded to CVWB bytes, decoded, then section 14 items."""
    return [b for f in frames for b in structured(decode(encode(f)))["bars"]]


async def _seeded(spec: BarSpec, emissions: list[list[BarUpdate]], gen: int) -> SeriesStore:
    store = SeriesStore()
    await store.ensure(SYM, spec)
    for updates in emissions:
        await store.emit(BarEmission(spec, gen, updates))
    return store


@settings(max_examples=30, deadline=None, derandomize=True)
@given(kind=_KIND, n=_N, gen=_GEN, size=_SIZE)
def test_snapshot_of_same_open_time_bars_has_distinct_generation_index_in_both_encodings(
    kind: str, n: int, gen: int, size: Decimal
) -> None:
    spec, emissions, bars = _checked(kind, n, size)
    store = asyncio.run(_seeded(spec, emissions, gen))
    src = BarsSnapshotSource(store, lambda _s: (1, 3))
    want = [b.index for b in bars]
    plain = src.build(_sub(spec, encoding="structured"))
    flow = src.build(_sub(spec, encoding="binary"))
    assert plain is not None and flow is not None
    _distinct_keys(plain.structured["bars"], gen, want)
    assert [b["confirm"] for b in plain.structured["bars"]] == [True] * n + [False]
    assert flow.parts and all(p.body_kind == BARS for p in flow.parts)
    _distinct_keys(_binary_items(flow.parts), gen, want)
    assert sum(Decimal(b["v"]) for b in plain.structured["bars"]) == sum(b.volume for b in bars)


# -- (c) WS deltas --------------------------------------------------------------------------


class _Taps:
    """A publisher over a real hub whose `publish` also feeds one `CoalescingQueue("bars")` per
    subscription encoding, the way the pipeline's pacer windows do."""

    def __init__(self, spec: BarSpec) -> None:
        src = Source()
        src.bodies["bars"] = SnapshotBody(
            {"symbol": SYM, "bar_type": to_wire(spec)[0], "param": to_wire(spec)[1], "bars": []},
            (Frame(BARS),),
        )
        self.hub = SequencingHub()
        self.subs: dict[str, Subscription] = {}
        self.queues = {e: CoalescingQueue("bars") for e in ("structured", "binary")}
        for enc in self.queues:
            conn = Conn(src)
            self.hub.register(conn.authz, conn.emitter)
            _, self.subs[enc] = conn.sub({"ch": _channel(spec), "opts": {"encoding": enc}})
        self.pub = BarsPublisher(self.hub, lambda _s: (1, 3), swap_reason="generation_swap")
        real: Callable[..., Any] = self.hub.publish

        def publish(ch: str, body: Any = None, *, select: Any = None, **kw: Any) -> Any:
            for enc, sub in self.subs.items():
                if select is None or select(sub):
                    self.queues[enc].offer(body, kw.get("part"), meta=kw.get("meta"))
            return real(ch, body, select=select, **kw)

        self.hub.publish = publish  # type: ignore[method-assign]  # test tap on one instance


@settings(max_examples=30, deadline=None, derandomize=True)
@given(kind=_KIND, n=_N, gen=_GEN, size=_SIZE)
def test_deltas_of_same_open_time_bars_coalesce_to_n_keys_with_a_mid_window_reemit(
    kind: str, n: int, gen: int, size: Decimal
) -> None:
    spec, emissions, bars = _checked(kind, n, size)
    taps = _Taps(spec)
    forming = bars[-1]

    async def run() -> None:
        for updates in emissions:
            await taps.pub.emit(BarEmission(spec, gen, updates))
        # a mid-window re-emit of the forming bar: same key, later state, never a new key
        again = BarUpdate(kind="update", bar=forming.model_copy(update={"trade_count": 99}))
        await taps.pub.emit(BarEmission(spec, gen, (again,)))

    asyncio.run(run())
    want = [b.index for b in bars]
    [structured_frame] = taps.queues["structured"].take()
    _distinct_keys(structured_frame.body["bars"], gen, want)
    assert structured_frame.body["bars"][-1]["trades"] == 99
    assert [b["confirm"] for b in structured_frame.body["bars"]] == [True] * n + [False]
    [binary_frame] = taps.queues["binary"].take()
    assert binary_frame.part is not None and binary_frame.part.body_kind == BARS
    assert len(binary_frame.part.records) == n + 1
    _distinct_keys(_binary_items((binary_frame.part,)), gen, want)
