"""E13-T02 (#426): the `indicators.*` topic against `23-ws-protocol.md` §6.1, §7.4, §8.2, §10.2
and §14.10, through the real `/ws` router, wired as `create_app` wires it with `bars_enabled`:
the series store and the indicator engine on the emit path, the engine's publisher and the
`indicators` snapshot source on the conformance world's hub, and a lease service that records.
The harness client validates every frame on receipt (§13, §14.10). Bars are the recorded BTCUSDT
tape's, built by the real time-bar builder (C-13.5).

Rows: the `sub_ok` echo and the snapshot; one `d` per close, valued as the kernel folds the
densified series, keyed `(key, generation, index)`; an amended close (`amended: true`); a
generation swap (`snap`, `generation_swap`); `history` and `meta.stale`; a `ctl` that retunes the
instances (and one refused, which changes nothing); the refusals: `invalid_options` for a
`client_worker` indicator, a bound, `compute`, `subscription_limit` naming the cap or saying the
churn bound's refusal ends with a grace (IR-31), and `internal_error` (retryable) when the
recompute executor is busy; no `marketdata:read`."""

from __future__ import annotations

import asyncio
import functools
from decimal import Decimal
from typing import Any, Final

from candleviewer.auth.generated_permissions import Permission
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series import BarSeries
from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.indicators.engine import IndicatorEngine, resolve_instances
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, bar_input
from candleviewer.ws.indicators_publish import IndicatorsPublisher, wire_value
from candleviewer.ws.indicators_source import IndicatorsSnapshotSource
from candleviewer.ws.permissions import Subscription
from candleviewer.ws_wiring import SnapshotRouter
from tests.contract.test_market_bars_contract import _SERIES, _build
from tests.contract.ws import _harness as h
from tests.unit.orderflow.indicators._engine import instances as running
from tests.unit.ws.test_subscriptions import _Bars

M1: Final = _SERIES["time", "1"]
CH: Final = "indicators.BTCUSDT.time.1"
MINUTE: Final = 60_000_000
INSTANCES: Final[list[dict[str, Any]]] = [
    {"indicator": "ema", "params": {"n": 5}},
    {"indicator": "vwap"},
    {"indicator": "atr", "params": {"n": 3}},
]


@functools.cache
def _bars() -> tuple[Bar, ...]:
    """The recorded tape's closed one-minute bars."""
    return tuple(b for b in _build(M1) if b.closed)


class _Rig:
    """The conformance world with `create_app`'s indicator wiring (module docstring)."""

    def __init__(self, *, tail: Any = None, history: Any = None, slots: int = 2) -> None:
        self.w = h.World()
        self.store = SeriesStore(tail, release_grace_s=0.0, clock=lambda: 0.0)
        self.engine = IndicatorEngine(self.store, history=history, slots=slots)
        self.engine.listen(IndicatorsPublisher(self.w.hub))
        self.router = EmitRouter([self.store, self.engine])
        self.quarantined: set[tuple[str, str]] = set()
        source = IndicatorsSnapshotSource(
            self.engine, stale=lambda symbol, spec_hash: (symbol, spec_hash) in self.quarantined
        )
        services, self.bars = self.w.registry.services, _Bars()
        services.bars, services.series, services.indicators = self.bars, self.store, self.engine
        services.snapshots = SnapshotRouter({"indicators": source})

    def close(self, b: Bar, *, generation: int = 0, amended: bool = False) -> None:
        update = BarUpdate(kind="close", bar=b, amended=amended)
        self.w.call(self.router.emit, M1, (update,), generation)


def _sub(c: h.Client, instances: list[dict[str, Any]], **opts: Any) -> dict[str, Any]:
    frame = c.sub({"ch": CH, "opts": {"instances": instances, **opts}})
    result: dict[str, Any] = frame["p"]["results"][0]
    return result


def _expected(r_index: int, bars: tuple[Bar, ...]) -> list[list[str | None]]:
    """What the kernel folds over the densified series (24 §7.4), at the real bars, on the wire."""
    r = resolve_instances(INSTANCES, M1)[r_index]
    dense = BarSeries(M1, list(bars)).densify()
    inputs: list[BarInput] = [bar_input(b) for b in dense]
    rows = compute(
        r.definition.id, inputs, r.params, source=r.kernel.sources[0], context=KernelContext()
    )
    return [
        [wire_value(v) for v in row] for row, b in zip(rows, dense, strict=True) if not b.synthetic
    ]


def test_contract_indicators_sub_ok_echoes_each_instance_and_a_d_follows_each_close() -> None:
    rig = _Rig()
    keys = [r.key for r in resolve_instances(INSTANCES, M1)]
    bars = _bars()[:30]
    with h.connect(rig.w) as c:
        result = _sub(c, INSTANCES)
        assert result["ok"] and result["effective"]["history"] == 500
        echo = result["effective"]["instances"]
        assert [e["key"] for e in echo] == keys  # every param written out, and its key (§6.1)
        assert echo[1]["params"] == {"anchor": "session"} and echo[0]["params"] == {"n": 5}
        snap = c.next_of("snap")
        assert snap["meta"]["reason"] == "initial"
        assert [i["points"] for i in snap["p"]["instances"]] == [[], [], []]
        got: dict[str, list[list[str | None]]] = {k: [] for k in keys}
        for b in bars:
            rig.close(b)
            d = c.next_of("d")
            for instance in d["p"]["instances"]:
                ((point,),) = [instance["points"]]  # one close: one point per instance
                assert (point["generation"], point["index"]) == (0, b.index)
                assert point["t_ms"] == b.open_time // 1000 and "amended" not in point
                got[instance["key"]].append(point["v"])
        assert [got[k] for k in keys] == [_expected(i, bars) for i in range(3)]


def test_contract_indicators_an_amended_close_republishes_the_changed_points() -> None:
    rig = _Rig()
    bars = _bars()[:12]
    with h.connect(rig.w) as c:
        assert _sub(c, INSTANCES[:1])["ok"]
        c.next_of("snap")
        for b in bars:
            rig.close(b)
            c.next_of("d")
        late = bars[-1].model_copy(update={"close": bars[-1].close + Decimal(7)})
        rig.close(late, amended=True)
        d = c.next_of("d")
        ((instance,),) = [d["p"]["instances"]]
        assert [(p["index"], p["amended"]) for p in instance["points"]] == [(late.index, True)]
        assert instance["points"][0]["v"] == _expected(0, (*bars[:-1], late))[-1]


def test_contract_indicators_a_generation_swap_is_a_snap_never_a_d() -> None:
    rig = _Rig()
    bars = _bars()
    with h.connect(rig.w) as c:
        assert _sub(c, INSTANCES[:1])["ok"]
        c.next_of("snap")
        for b in bars[:3]:
            rig.close(b)
            c.next_of("d")
        rig.close(bars[3].model_copy(update={"index": 0}), generation=1)  # a cold start
        snap = c.next_of("snap")
        assert snap["meta"]["reason"] == "generation_swap"
        points = snap["p"]["instances"][0]["points"]
        assert [(p["generation"], p["index"]) for p in points] == [(1, 0)]


def test_contract_indicators_history_bounds_the_snapshot_and_stale_is_disclosed() -> None:
    rig = _Rig()
    with h.connect(rig.w) as c:
        assert _sub(c, INSTANCES[:1])["ok"]
        c.next_of("snap")
        for b in _bars()[:6]:
            rig.close(b)
            c.next_of("d")
    rig.quarantined.add(("BTCUSDT", M1.spec_hash))
    with h.connect(rig.w) as c:
        assert _sub(c, INSTANCES[:1], history=3)["ok"]
        snap = c.next_of("snap")
        assert [p["index"] for p in snap["p"]["instances"][0]["points"]] == [3, 4, 5]
        assert snap["meta"]["stale"] is True


def test_contract_indicators_ctl_retunes_the_instances_and_re_snapshots() -> None:
    rig = _Rig()
    with h.connect(rig.w) as c:
        assert _sub(c, INSTANCES[:1])["ok"]
        c.next_of("snap")
        for b in _bars()[:4]:
            rig.close(b)
            c.next_of("d")
        refused = {"t": "ctl", "id": "c-1", "ch": CH, "p": {"instances": [{"indicator": "macd"}]}}
        c.send(refused)
        err = c.next_of("err")
        assert (err["p"]["code"], err["p"]["field"]) == ("invalid_options", "instances")
        sma = [{"indicator": "sma", "params": {"n": 2}}]
        c.send({"t": "ctl", "id": "c-2", "ch": CH, "p": {"instances": sma}})
        ok = c.next_of("ctl_ok")
        (key,) = [r.key for r in resolve_instances(sma, M1)]
        assert ok["p"]["resnapshot"] is True
        assert ok["p"]["effective"]["instances"] == [
            {"indicator": "sma", "params": {"n": 2}, "key": key}
        ]
        snap = c.next_of("snap")
        assert snap["meta"]["reason"] == "reconfigure"
        ((instance,),) = [snap["p"]["instances"]]
        assert instance["key"] == key and [p["index"] for p in instance["points"]] == [0, 1, 2, 3]
    assert running(rig.engine, M1) == 1  # the old one, held by this `ctl` alone: no grace


def test_contract_indicators_refusals_name_the_entry_and_never_clamp() -> None:
    rig = _Rig()
    cases = [
        ([{"indicator": "macd"}], {}, "invalid_options", "instances"),  # client_worker
        ([{"indicator": "ema", "params": {"n": 5001}}], {}, "invalid_options", "instances"),
        (INSTANCES[:1], {"compute": "server"}, "invalid_options", "opts"),  # IR-41
    ]
    with h.connect(rig.w) as c:
        for instances, opts, code, field in cases:
            frame = c.sub({"ch": CH, "opts": {"instances": instances, **opts}}, conform=False)
            (result,) = frame["p"]["results"]
            assert (result["ok"], result["error"]["code"], result["error"]["field"]) == (
                False,
                code,
                field,
            )
        assert running(rig.engine, M1) == 0


def test_contract_indicators_past_a_cap_is_subscription_limit_naming_it() -> None:
    rig = _Rig()
    eight = [{"indicator": "ema", "params": {"n": n}} for n in range(2, 10)]
    with h.connect(rig.w) as c:
        assert _sub(c, eight)["ok"]
        c.next_of("snap")
        other = c.sub(
            {"ch": "indicators.BTCUSDT.time.5", "opts": {"instances": [{"indicator": "cvd"}]}}
        )
        (result,) = other["p"]["results"]
        error = result["error"]
        assert (error["code"], error["retryable"]) == ("subscription_limit", True)
        assert error["message"] == "At most 8 server indicator instances per user."


def test_contract_indicators_churn_past_its_bound_is_a_retryable_subscription_limit() -> None:
    """IR-31 on the WS (review of the WS delivery, round 5): the instances a user holds and those
    it released that are still in their grace are bounded together (24). Eight instances on each
    of three series, subscribed and unsubscribed in turn, leave 24 in their grace; one more on a
    fourth series is `subscription_limit`, retryable, and its message says the refusal ends with
    a grace (it names no instance and no user)."""
    rig = _Rig()
    eight = [{"indicator": "ema", "params": {"n": n}} for n in range(2, 10)]
    with h.connect(rig.w) as c:
        for i, interval in enumerate(("1", "3", "5")):
            ch = f"indicators.BTCUSDT.time.{interval}"
            assert c.sub({"ch": ch, "opts": {"instances": eight}})["p"]["results"][0]["ok"]
            c.next_of("snap")
            c.send({"t": "unsub", "id": f"u-{i}", "p": {"topics": [ch]}})
            c.next_of("unsub_ok")
        frame = c.sub(
            {"ch": "indicators.BTCUSDT.time.15", "opts": {"instances": [{"indicator": "cvd"}]}}
        )
        (result,) = frame["p"]["results"]
        error = result["error"]
        assert (result["ok"], error["code"], error["retryable"]) == (
            False,
            "subscription_limit",
            True,
        )
        assert error["message"] == (
            "Server indicator instances you released in the last 30 s still count; "
            "retry once they expire."
        )


def test_contract_indicators_a_busy_recompute_executor_refuses_retryably() -> None:
    """SR-E13-04: SMA(20) with history 5 needs 25 bars and the store holds 10 from index 100, so
    a read is needed; with no slot free it is refused `internal_error` (retryable), never
    queued, and nothing is held."""
    bars = _bars()[:10]

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(0, b.model_copy(update={"index": b.index + 100})) for b in bars])

    rig = _Rig(tail=tail, history=_never, slots=0)
    with h.connect(rig.w) as c:
        result = _sub(c, [{"indicator": "sma", "params": {"n": 20}}], history=5)
        assert (result["ok"], result["error"]["code"], result["error"]["retryable"]) == (
            False,
            "internal_error",
            True,
        )
    assert running(rig.engine, M1) == 0


async def _never(*_: Any) -> list[tuple[int, BarInput]]:
    raise AssertionError("no read starts without a slot")


def test_contract_indicators_without_marketdata_read_is_forbidden() -> None:
    rig = _Rig()
    rig.w.perms = frozenset(p for p in Permission if p is not Permission.MARKETDATA_READ)
    with h.connect(rig.w) as c:
        result = _sub(c, INSTANCES[:1])
        assert (result["ok"], result["error"]["code"]) == (False, "forbidden")


def _subscription(rig: _Rig, ch: str) -> Subscription:
    """The live subscription of `ch` on the rig's one connection (read between frames)."""
    authz, _send, _close = rig.w.registry._conns[next(iter(rig.w.registry._conns))][0]
    sub = authz.named(ch, None)
    assert sub is not None
    return sub


def test_contract_indicators_a_ctl_past_the_user_cap_is_refused_and_changes_nothing() -> None:
    """§6.1: a `ctl` that changes instances is refused as a `sub` is, with an `err`, and changes
    nothing (SR-E13-03 on the second path that admits server computations). Seven instances on
    one series and one on another: retuning the one to eight new ones is `subscription_limit`
    naming the user cap; retuning it to one other is the legal control."""
    rig = _Rig()
    three = "indicators.BTCUSDT.time.3"
    with h.connect(rig.w) as c:
        assert _sub(c, [{"indicator": "ema", "params": {"n": n}} for n in range(2, 9)])["ok"]
        c.next_of("snap")
        frame = c.sub({"ch": three, "opts": {"instances": [{"indicator": "cvd"}]}})
        assert frame["p"]["results"][0]["ok"]
        c.next_of("snap")
        sub = _subscription(rig, three)
        keys, echo, held = (
            sub.indicator_keys,
            sub.effective["instances"],
            set(rig.engine._leases._held),
        )
        eight = [{"indicator": "ema", "params": {"n": n}} for n in range(20, 28)]
        c.send({"t": "ctl", "id": "c-1", "ch": three, "p": {"instances": eight}})
        err = c.next_of("err")
        assert (err["id"], err["p"]["code"]) == ("c-1", "subscription_limit")
        assert err["p"]["message"] == "At most 8 server indicator instances per user."
        assert (sub.indicator_keys, sub.effective["instances"]) == (keys, echo)
        assert set(rig.engine._leases._held) == held
        one = [{"indicator": "cvd", "params": {"anchor": "utc_day"}}]
        c.send({"t": "ctl", "id": "c-2", "ch": three, "p": {"instances": one}})
        ok = c.next_of("ctl_ok")
        assert ok["id"] == "c-2"  # no `ctl_ok` went out for the refused one
        assert [f["id"] for f in c.seen if f["t"] == "ctl_ok"] == ["c-2"]
        assert sub.indicator_keys != keys


def test_contract_indicators_a_ctl_needing_a_read_with_no_free_slot_changes_nothing() -> None:
    """SR-E13-04 on the `ctl` path: a new instance that needs a stored-bar read with no slot free
    is `internal_error` (retryable, never queued) and the subscription keeps its instances."""
    bars = _bars()[:10]

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(0, b.model_copy(update={"index": b.index + 100})) for b in bars])

    rig = _Rig(tail=tail, history=_never, slots=0)
    with h.connect(rig.w) as c:
        assert _sub(c, [{"indicator": "ema", "params": {"n": 2}}], history=5)["ok"]  # no read
        c.next_of("snap")
        sub = _subscription(rig, CH)
        keys, echo, held = (
            sub.indicator_keys,
            sub.effective["instances"],
            set(rig.engine._leases._held),
        )
        sma = [{"indicator": "sma", "params": {"n": 20}}]  # 25 bars: a read the store needs
        c.send({"t": "ctl", "id": "c-1", "ch": CH, "p": {"instances": sma}})
        err = c.next_of("err")
        assert (err["id"], err["p"]["code"], err["p"]["retryable"]) == (
            "c-1",
            "internal_error",
            True,
        )
        assert (sub.indicator_keys, sub.effective["instances"]) == (keys, echo)
        assert set(rig.engine._leases._held) == held and running(rig.engine, M1) == 1


class _Gate:
    """A `HistoryRead` that returns `rows` once `release` runs on the app's loop."""

    def __init__(self, rows: list[tuple[int, BarInput]]) -> None:
        self.rows = rows
        self.event: asyncio.Event | None = None

    def _event(self) -> asyncio.Event:
        self.event = self.event or asyncio.Event()  # made on the app's loop, by either side
        return self.event

    async def read(self, *_: Any) -> list[tuple[int, BarInput]]:
        await self._event().wait()
        return self.rows

    async def release(self) -> None:
        self._event().set()


def test_contract_indicators_a_snap_waits_for_its_instance_s_stored_read() -> None:
    """23 §16: an instance primed from stored bars sends its `snap` once that read ends (the
    engine's `ready` flushes it), never before. SMA(20) with history 5 needs 25 bars, the store
    holds 10 from index 100: the read brings 85..99, and the snap holds 105..109."""
    bars = [b.model_copy(update={"index": b.index + 100}) for b in _bars()[:10]]
    first = bars[0]
    older = [
        first.model_copy(update={"index": 85 + k, "open_time": first.open_time - (15 - k) * MINUTE})
        for k in range(15)
    ]

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(0, b) for b in bars])

    gate = _Gate([(b.index, bar_input(b)) for b in older])
    rig = _Rig(tail=tail, history=gate.read)
    sma = [{"indicator": "sma", "params": {"n": 20}}]
    with h.connect(rig.w) as c:
        assert _sub(c, sma, history=5)["ok"]
        c.send({"t": "ping", "id": "p-1"})
        before = []
        while (frame := c.recv())["t"] != "pong":
            before.append(frame["t"])
        assert "snap" not in before  # the read is held: the snapshot waits
        rig.w.call(gate.release)
        snap = c.next_of("snap")
        ((instance,),) = [snap["p"]["instances"]]
        assert [p["index"] for p in instance["points"]] == list(range(105, 110))
        (r,) = resolve_instances(sma, M1)
        dense = BarSeries(M1, [*older, *bars]).densify()
        rows = compute("sma", [bar_input(b) for b in dense], r.params, source="close")
        want = [
            [wire_value(v) for v in row]
            for row, b in zip(rows, dense, strict=True)
            if not b.synthetic
        ]
        assert [p["v"] for p in instance["points"]] == want[-5:]


def test_contract_indicators_a_series_no_builder_serves_is_refused_and_holds_nothing() -> None:
    """SR-E12-03 bounds the series of `indicators.*` as it bounds `bars.*`: `time.7` names no
    interval, so the `sub` is `invalid_topic_format` and nothing is held."""
    rig = _Rig()
    with h.connect(rig.w) as c:
        frame = c.sub({"ch": "indicators.BTCUSDT.time.7", "opts": {"instances": INSTANCES[:1]}})
        (result,) = frame["p"]["results"]
        assert (result["ok"], result["error"]["code"]) == (False, "invalid_topic_format")
    assert rig.engine._leases._held == {} and rig.engine._instances == {}
    assert rig.bars.registered == []  # no builder lease either
