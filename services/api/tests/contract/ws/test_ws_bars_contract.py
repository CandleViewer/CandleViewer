"""#399 (E12-T06) D5: the `bars.*` topic against `23-ws-protocol.md` §3.4, §6.1, §7, §8.2 and §16.4,
through the real `/ws` router, wired as `create_app` wires it: a series store hydrated by a
`BarReader` over fake storage (the one reader the REST route also reads through), the publisher and
the snapshot source on the conformance world's hub, and a lease service that records. The harness
client validates every frame on receipt, under `cv.v1.json` and `cv.v1.msgpack`. Stored rows and
emissions come from the recorded BTCUSDT tape (C-13.5), built by the real builders.

Rows: the snapshot against REST (§6.1); the forming flag and one close per bar; a client resync
after a lost delta; a generation swap (C14); the structured fallback of a binary subscription, of a
snapshot and of deltas (C15, C17, C19); the scales of each kind-4 frame (C16); a dotted `param`;
no `marketdata:read`, at subscribe and mid-stream."""

from __future__ import annotations

import functools
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Final, Literal

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.market import MarketDataPrincipal
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarReader, row_key
from candleviewer.bars.rows import bar_param_for, bar_row
from candleviewer.bars.series_store import SeriesStore
from candleviewer.bars.spec import from_wire
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws_wiring import SnapshotRouter
from tests.contract.test_market_bars_contract import (
    _NOW,
    _SERIES,
    _STORE,
    _T0,
    _TAPE,
    _build,
    _tape_totals,
)
from tests.contract.ws import _harness as h
from tests.unit.ws._seq_support import USER
from tests.unit.ws.test_subscriptions import _Bars

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
#: The fields kind 4 has no slot for (§3.4): a client ignores them on a binary subscription (C19).
_STRUCTURED_ONLY: Final = frozenset({"close_t_ms", "min_delta", "max_delta"})
_DECIMALS: Final = ("o", "h", "l", "c", "v", "turnover", "delta", "min_delta", "max_delta")
_MINUTE: Final = ("time", "1")
CH: Final = "bars.BTCUSDT.time.1"


class _Storage:
    """`RowFetcher` over stored rows: the reader's range query (REST) and its newest-first tail
    query (the WS store's hydration), as the real SQL answers them for one symbol."""

    def __init__(self, rows: dict[str, list[dict[str, object]]]) -> None:
        self.rows = {bar_param: list(stored) for bar_param, stored in rows.items()}

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        symbol, bar_param, start = params[:3]
        limit = int(sql.rsplit("LIMIT ", 1)[1])
        rows = [
            r
            for r in self.rows.get(str(bar_param), [])
            if r["symbol"] == symbol and int(str(r["ts"])) >= ts_us_from_row(start)
        ]
        if "DESC LIMIT" in sql:  # the tail: bar-keyed rows, newest first
            return sorted(rows, key=row_key, reverse=True)[:limit]
        end = ts_us_from_row(params[3])
        return sorted((r for r in rows if int(str(r["ts"])) < end), key=row_key)[:limit]


class _Allow:
    def resolve(self, request: Request) -> MarketDataPrincipal:
        return MarketDataPrincipal("u1", frozenset({"marketdata:read"}))


async def _started(symbol: str) -> int:
    return _T0


async def _no_rebuild(*_: object) -> None: ...


class _Rig:
    """The conformance world with the bars wiring of `create_app` over `rows` (`bar_param` ->
    stored rows). `scales` is the instrument catalogue's answer (`None`: symbol not listed)."""

    def __init__(self, rows: dict[str, list[dict[str, object]]]) -> None:
        self.w = h.World()
        self.scales: tuple[int, int] | None = (1, 3)
        self.reader = BarReader(_Storage(rows), _no_rebuild, now_us=lambda: _NOW)
        self.store = SeriesStore(self.reader.read_tail, release_grace_s=0.0, clock=lambda: 0.0)
        publisher = BarsPublisher(self.w.hub, lambda _s: self.scales, swap_reason="generation_swap")
        self.router = EmitRouter([self.store, publisher])
        self.leases = _Bars()
        source = BarsSnapshotSource(
            self.store, lambda _s: self.scales, seed=publisher.note_generation
        )
        services = self.w.registry.services
        services.bars, services.series = self.leases, self.store
        services.snapshots = SnapshotRouter({"bars": source})

    def emit(self, spec: BarSpec, *updates: BarUpdate, generation: int = 0) -> None:
        self.w.call(self.router.emit, spec, updates, generation)

    def rest(self, bar_type: str, param: str, **query: object) -> list[dict[str, Any]]:
        """`GET /market/bars` over the same reader (a non-time kind also needs the tape's trade
        totals, SR-E12-02): the bars of one 200 response."""
        app = FastAPI()
        app.include_router(
            make_market_bars_router(
                lambda: self.reader,
                recording_started_at_us=_started,
                trade_totals=_tape_totals,
                principal_resolver=_Allow(),
                symbol_listed=lambda symbol: symbol == "BTCUSDT",
                now_us=lambda: _NOW,
            )
        )
        params = {"symbol": "BTCUSDT", "bar_type": bar_type, "param": param, "limit": 5000}
        response = TestClient(app).get("/market/bars", params={**params, "to": _iso(_NOW), **query})
        assert response.status_code == 200, response.text
        bars: list[dict[str, Any]] = response.json()["bars"]
        return bars


class _Series:
    """A reference `bars` client (§7.1, §8.2; C2, C5, C14, C15, C17, C19): a `snap` replaces the
    whole series, a `d` upserts by `(generation, index)` (a closed bar only yields to an amended
    close), a gap in `s` discards the series for a `resync`, and a binary subscription ignores
    what kind 4 cannot carry whichever encoding a frame came in."""

    def __init__(self, *, binary: bool) -> None:
        self.binary, self.last = binary, 0
        self.bars: dict[tuple[int, int], dict[str, Any]] = {}

    def apply(self, frame: dict[str, Any]) -> bool:
        if frame["t"] == "snap":
            self.bars = {}
        elif frame["s"] != self.last + 1:
            self.bars = {}
            return False
        self.last = frame["s"]
        for item in h.structured_of(frame)["bars"]:
            if self.binary:
                item = {k: v for k, v in item.items() if k not in _STRUCTURED_ONLY}
            key = (item["generation"], item["index"])
            held = self.bars.get(key)
            if held is None or not held["confirm"] or (item["confirm"] and item.get("amended")):
                self.bars[key] = {k: v for k, v in item.items() if k != "amended"}
        return True


def _iso(us: int) -> str:
    return (_EPOCH + timedelta(microseconds=us)).isoformat().replace("+00:00", "Z")


def _ms(iso: str) -> int:
    return (datetime.fromisoformat(iso) - _EPOCH) // timedelta(milliseconds=1)


@functools.cache
def _closed(bar_type: str, param: str) -> list[Bar]:
    """The tape's closed bars, the ones `_STORE` holds as rows (`_build` also returns the forming
    bar a non-time builder ends with)."""
    return [b for b in _build(_SERIES[bar_type, param]) if b.closed]


@functools.cache
def _long_minute() -> list[dict[str, object]]:
    """540 stored one-minute rows, so that `history=500` cuts: the tape's 180 bars three times, each
    copy 180 minutes and 180 indexes after the one before it, the last at the tape's own times."""
    spec, bars = _SERIES[_MINUTE], _closed(*_MINUTE)
    rows: list[dict[str, object]] = []
    for copy in range(3):
        back_us = (2 - copy) * 180 * 60_000_000
        for b in bars:
            moved = {"index": b.index + 180 * copy, "open_time": b.open_time - back_us}
            moved["close_time"] = b.close_time - back_us
            rows.append(bar_row(b.model_copy(update=moved), spec, generation=0))
    return rows


def _up(kind: Literal["open", "update", "close"], bar: Bar, *, amended: bool = False) -> BarUpdate:
    return BarUpdate(
        kind=kind, bar=bar.model_copy(update={"closed": kind == "close"}), amended=amended
    )


def _rest_item(bar: dict[str, Any], bar_type: str, *, flow: bool) -> dict[str, Any]:
    """A REST bar in the §14.3 item form, decimals as `Decimal`: what a snapshot item must equal."""
    item: dict[str, Any] = {
        "generation": bar["generation"],
        "index": bar["index"],
        "t_ms": _ms(bar["t"]),
        "trades": bar["trades"],
        "confirm": bar["confirm"],
    }
    if bar_type != "time":
        item["close_t_ms"] = _ms(bar["close_time"])
    for name in _DECIMALS[: 6 + 3 * flow]:
        item[name] = Decimal(bar[name])
    return item


def _wire_item(item: dict[str, Any]) -> dict[str, Any]:
    return {k: Decimal(v) if k in _DECIMALS else v for k, v in item.items()}


@pytest.mark.parametrize("flow", [False, True], ids=["plain", "include_delta"])
@pytest.mark.parametrize("mode", h.MODES)
@pytest.mark.parametrize("history", [3, 500])
@pytest.mark.parametrize(("bar_type", "param"), [_MINUTE, ("tick", "100"), ("range", "20")])
def test_contract_bars_snapshot_equals_rest_for_the_same_window(
    bar_type: str, param: str, history: int, mode: str, flow: bool
) -> None:
    """§6.1: the snapshot is the last `history` bars, oldest to newest as REST orders them. REST
    is asked for every field; `include_delta` decides which of them the snapshot carries. 3 cuts
    every series; 500 cuts the 540 one-minute rows and takes the tape's 5 and 8 whole."""
    rows, spec = {**_STORE, "1m": _long_minute()}, from_wire(bar_type, param)
    rig, first = _Rig(rows), int(str(rows[bar_param_for(spec)][0]["ts"]))  # the first stored bar
    rest = {"include_delta": "true"}
    stored = rig.rest(bar_type, param, **rest, **{"from": _iso(first)})
    window = stored[-history:]
    assert len(window) == min(history, len(stored)) >= 3
    assert rig.rest(bar_type, param, **rest, **{"from": window[0]["t"]}) == window
    opts = {"history": history, "include_delta": flow, "encoding": mode}
    with h.connect(rig.w) as c:
        results = c.sub({"ch": f"bars.BTCUSDT.{bar_type}.{param}", "opts": opts})["p"]["results"]
        assert results[0]["ok"]
        snap = c.next_of("snap")
    want = [_rest_item(b, bar_type, flow=flow) for b in window]
    if mode == "binary":
        # Kind 4 has no `close_t_ms`, `min_delta` or `max_delta`, its `delta` is 0 unless sent, and
        # its `turnover` is rounded half-even to the frame's `qty_scale` (§3.4).
        scale = Decimal(1).scaleb(-h.cvwb_part(snap).qty_scale)
        want = [{k: v for k, v in w.items() if k not in _STRUCTURED_ONLY} for w in want]
        for w in want:
            w["turnover"] = w["turnover"].quantize(scale, ROUND_HALF_EVEN)
            w.setdefault("delta", Decimal(0))
    assert [_wire_item(i) for i in h.structured_of(snap)["bars"]] == want
    assert snap["meta"]["spec_hash"] == spec.spec_hash


@pytest.mark.parametrize("mode", h.MODES)
def test_contract_bars_forming_bar_is_unconfirmed_in_every_frame_and_confirmed_exactly_once(
    mode: str,
) -> None:
    """The recorded tape through the real builder and emit router: each bar's frames read
    `confirm: false` until its close, which is delivered once; none follows it."""
    spec, builder, rig = _SERIES[_MINUTE], TimeBarBuilder(_SERIES[_MINUTE], "BTCUSDT"), _Rig({})
    emissions = [[*builder.on_trade(t), *builder.on_clock(t.ts_event)] for t in _TAPE]
    emissions.append([*builder.on_clock(_TAPE[-1].ts_event + 60_000_000)])  # the last boundary
    seen: dict[int, list[bool]] = {}
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": mode}})
        snap = c.next_of("snap")
        assert h.structured_of(snap)["bars"] == []  # no tape yet: bars come as they form
        for updates in filter(None, emissions):
            rig.emit(spec, *updates)
            for item in h.structured_of(c.next_of("d"))["bars"]:
                seen.setdefault(item["index"], []).append(item["confirm"])
    assert sorted(seen) == [r["index"] for r in _STORE["1m"]]  # every bar of the tape arrived
    assert all(f[0] is False and f == [False] * (len(f) - 1) + [True] for f in seen.values())


@pytest.mark.parametrize("mode", h.MODES)
def test_contract_bars_a_client_that_lost_a_delta_resyncs_to_a_snapshot_holding_every_bar(
    mode: str,
) -> None:
    """§7.1, §7.5: the client sees `s` skip, discards its series and asks; the `snap` replaces it
    and holds the bar whose close was in the lost frame, and the deltas go on from its `s`."""
    spec, bars = _SERIES[_MINUTE], _closed(*_MINUTE)
    rig, mine = _Rig({"1m": _STORE["1m"][:3]}), _Series(binary=mode == "binary")
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": mode}})
        assert mine.apply(c.next_of("snap")) and sorted(mine.bars) == [(0, 0), (0, 1), (0, 2)]
        rig.emit(spec, _up("open", bars[3]))
        assert mine.apply(c.next_of("d"))  # s 2
        rig.emit(spec, _up("close", bars[3]))
        assert c.next_of("d")["s"] == 3  # lost in transit: never applied
        rig.emit(spec, _up("open", bars[4]))
        assert not mine.apply(c.next_of("d")) and mine.bars == {}  # s 4: a gap, nothing patched
        resync = {"reason": "sequence_gap", "last_seq": mine.last}
        c.send({"t": "resync", "id": "r", "ch": CH, "p": resync})
        snap = c.next_of("snap")
        meta = snap["meta"]
        assert (snap["s"], meta["reason"], meta["previous_seq"]) == (5, "client_resync", 4)
        assert mine.apply(snap)
        held = {(0, i): True for i in range(4)} | {(0, 4): False}  # the lost close, the forming bar
        assert {key: bar["confirm"] for key, bar in mine.bars.items()} == held
        rig.emit(spec, _up("update", bars[4]))
        assert mine.apply(c.next_of("d")) and mine.last == 6  # the deltas go on from its `s`


@pytest.mark.parametrize("mode", h.MODES)
def test_contract_bars_a_generation_change_is_a_swap_snapshot_never_a_delta(mode: str) -> None:
    """§7.4, §8.2, §16.4 (C14): a change of generation, up or down, re-snapshots the subscriber
    instead of sending a `d`; the client replaces its whole series, never merging generations."""
    spec, bars = _SERIES[_MINUTE], _closed(*_MINUTE)
    rig, mine = _Rig({"1m": _STORE["1m"][:3]}), _Series(binary=mode == "binary")
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": mode}})
        assert mine.apply(c.next_of("snap")) and sorted(mine.bars) == [(0, 0), (0, 1), (0, 2)]
        rig.emit(spec, _up("open", bars[3]))
        assert mine.apply(c.next_of("d"))  # s 2
        # up, then back down: each snapshot takes the next `s`
        for generation, seq in [(1, 3), (0, 4)]:
            rig.emit(spec, _up("open", bars[0]), generation=generation)  # index 0 again
            swap = c.recv()  # the first frame the emission causes: a `snap`, not a `d`
            meta = swap["meta"]
            assert (swap["t"], swap["s"], meta["previous_seq"]) == ("snap", seq, seq - 1)
            assert meta["reason"] == "generation_swap" and mine.apply(swap)
            assert sorted(mine.bars) == [(generation, 0)]  # replaced: nothing of the old series
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"  # and no `d` followed either snapshot


def test_contract_bars_structured_fallback_on_a_binary_sub_keeps_s_contiguous_c15_c17() -> None:
    """§3.4, §6.1 (C15, C17, C19): an amended close, a value outside its field and unknown scales
    each go structured, `s` runs on across both encodings, and the client applies every frame."""
    spec, bars = _SERIES[_MINUTE], _closed(*_MINUTE)
    amended = bars[10].model_copy(update={"close": Decimal("63000.5")})
    huge = bars[11].model_copy(update={"open": Decimal("1E+19")})  # outside kind 4's i64
    steps = [  # (the catalogue's scales, the update)
        ((1, 3), _up("close", bars[10])),
        ((1, 3), _up("close", amended, amended=True)),  # kind 4 has no amended bit
        ((1, 3), _up("close", huge)),
        (None, _up("close", bars[12])),
        ((1, 3), _up("close", bars[13])),
    ]
    rig, mine, frames = _Rig({"1m": _STORE["1m"][:10]}), _Series(binary=True), []
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": "binary", "include_delta": True}})
        assert mine.apply(c.next_of("snap"))
        for scales, update in steps:
            rig.scales = scales  # the catalogue's answer for this emission
            rig.emit(spec, update)
            frames.append(c.next_of("d"))
            assert mine.apply(frames[-1])
    assert [(f["e"], f["s"]) for f in frames] == [
        (c.binary_e, 2), ("j", 3), ("j", 4), ("j", 5), (c.binary_e, 6)
    ]  # fmt: skip
    assert (mine.bars[0, 10]["c"], mine.bars[0, 11]["o"]) == ("63000.5", "10000000000000000000")
    assert len({frozenset(mine.bars[0, i]) for i in range(10, 14)}) == 1  # one shape, any encoding


def test_contract_bars_unknown_scales_send_the_snapshot_structured_then_d_is_kind_4() -> None:
    """§3.4, §6.1 (C15): a snapshot kind 4 cannot carry goes whole structured and `sub_ok` still
    says binary; once the scales are known the next `d` is kind 4, `s` runs on, and the client
    applies both."""
    spec, bars = _SERIES[_MINUTE], _closed(*_MINUTE)
    rig, mine = _Rig({"1m": _STORE["1m"][:3]}), _Series(binary=True)
    rig.scales = None
    with h.connect(rig.w) as c:
        (result,) = c.sub({"ch": CH, "opts": {"encoding": "binary"}})["p"]["results"]
        assert result["effective"]["encoding"] == "binary"
        snap = c.next_of("snap")
        assert (snap["e"], snap["s"]) == ("j", 1) and mine.apply(snap)
        rig.scales = (1, 3)
        rig.emit(spec, _up("close", bars[3]))
        d = c.next_of("d")
        assert (d["e"], d["s"]) == (c.binary_e, 2) and mine.apply(d)
    assert sorted(mine.bars) == [(0, 0), (0, 1), (0, 2), (0, 3)]


def test_contract_bars_each_kind_4_frame_carries_the_scales_its_own_bars_need() -> None:
    """§3.4 (C16): a delta finer than the snapshot has its own header, and read with the
    snapshot's scales its price would be wrong."""
    spec, rig = _SERIES[_MINUTE], _Rig({"1m": _STORE["1m"][:3]})
    bar = _closed(*_MINUTE)[3].model_copy(update={"open": Decimal("63120.15")})
    with h.connect(rig.w) as c:
        c.sub({"ch": CH, "opts": {"encoding": "binary"}})
        snap = h.cvwb_part(c.next_of("snap"))
        rig.emit(spec, _up("close", bar))
        d = c.next_of("d")
    frame = h.cvwb_part(d)
    assert (snap.price_scale, frame.price_scale) == (1, 2)
    assert h.structured_of(d)["bars"][0]["o"] == "63120.15"
    assert Decimal(frame.records[0][3]).scaleb(-snap.price_scale) != Decimal("63120.15")


def test_contract_bars_a_dotted_param_is_refused_and_no_builder_is_registered() -> None:
    rig = _Rig({})
    with h.connect(rig.w) as c:
        results = c.sub("bars.BTCUSDT.tick.500", "bars.BTCUSDT.tick.500.extra")["p"]["results"]
        valid, dotted = results
        assert (valid["ok"], dotted["ok"]) == (True, False)
        assert dotted["error"]["code"] == "invalid_topic_format"
        assert rig.store.series_count() == 1  # the one valid series; the dotted one took no hold
    assert [hash_ for hash_, *_ in rig.leases.registered] == [from_wire("tick", "500").spec_hash]


def test_contract_bars_without_marketdata_read_the_sub_is_refused_and_no_frame_follows() -> None:
    rig, spec = _Rig({}), _SERIES[_MINUTE]
    rig.w.perms = h.ALL_PERMS - {Permission.MARKETDATA_READ}
    with h.connect(rig.w) as c:
        (res,) = c.sub(CH)["p"]["results"]
        assert (res["ok"], res["error"]["code"]) == (False, "forbidden")
        rig.emit(spec, _up("open", _closed(*_MINUTE)[0]))  # the series has a producer
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"  # a frame for the refused subscription would come first
    assert (rig.leases.registered, rig.store.series_count()) == ([], 0)


def test_contract_bars_a_session_losing_marketdata_read_stops_receiving_bars() -> None:
    rig, spec, bar = _Rig({}), _SERIES[_MINUTE], _closed(*_MINUTE)[0]
    with h.connect(rig.w) as c:
        c.sub(CH)
        c.next_of("snap")
        rig.emit(spec, _up("open", bar))
        assert c.next_of("d")["s"] == 2
        rig.w.perms = h.ALL_PERMS - {Permission.MARKETDATA_READ}
        rig.w.call(rig.w.registry.roles_changed, USER)
        revoked = c.next_validated("revoked")
        assert (revoked["ch"], revoked["p"]["reason"]) == (CH, "permission_revoked")
        rig.emit(spec, _up("update", bar))
        c.send({"t": "ping", "id": "p"})
        c.next_of("pong")
        later = c.seen[[f["t"] for f in c.seen].index("revoked") :]
        assert [f["t"] for f in later if f["t"] in {"snap", "d"}] == []
    assert len(rig.leases.released) == len(rig.leases.registered) == 1
