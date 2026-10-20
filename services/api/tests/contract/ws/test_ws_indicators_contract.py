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
`client_worker` indicator, a bound, `compute`, `subscription_limit` naming the cap, and
`internal_error` (retryable) when the recompute executor is busy; no `marketdata:read`."""

from __future__ import annotations

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
from candleviewer.ws_wiring import SnapshotRouter
from tests.contract.test_market_bars_contract import _SERIES, _build
from tests.contract.ws import _harness as h
from tests.unit.ws.test_subscriptions import _Bars

M1: Final = _SERIES["time", "1"]
CH: Final = "indicators.BTCUSDT.time.1"
INSTANCES: Final = [
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
        services = self.w.registry.services
        services.bars, services.series, services.indicators = _Bars(), self.store, self.engine
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
    assert rig.engine.instances("BTCUSDT", M1.spec_hash) == 2  # the old one keeps its grace


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
        assert rig.engine.instances("BTCUSDT", M1.spec_hash) == 0


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
    assert rig.engine.instances("BTCUSDT", M1.spec_hash) == 0


async def _never(*_: Any) -> list[tuple[int, BarInput]]:
    raise AssertionError("no read starts without a slot")


def test_contract_indicators_without_marketdata_read_is_forbidden() -> None:
    rig = _Rig()
    rig.w.perms = frozenset(p for p in Permission if p is not Permission.MARKETDATA_READ)
    with h.connect(rig.w) as c:
        result = _sub(c, INSTANCES[:1])
        assert (result["ok"], result["error"]["code"]) == (False, "forbidden")
