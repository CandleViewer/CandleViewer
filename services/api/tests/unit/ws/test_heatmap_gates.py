"""E21-T02 (#605; 23 §6.1, §10.2, §16.2): the `heatmap.*` gates at `sub` and `ctl`, in order: a
replay one while no replay producer serves it (`unknown_topic`), depth 500 while
`heatmap_depth_500` is off (`invalid_topic_format`), and the G-02 spec caps
(`subscription_limit`); a `ctl` of the bucket re-snapshots on a new spec lease; saturation holds
a heatmap to one frame a second with `degraded_topics` (§8.3). The composition root serves the
family from the order-flow publisher. G-04 holds by construction: every connection runs on the
byte budget (#2409 removed `CV_WS_BACKPRESSURE_ENABLED`, whose off state refused the family)."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.bus.bus import Bus
from candleviewer.orderbook_wiring import BookStream
from candleviewer.orderflow.heatmap import HeatmapSpec, HeatmapTopic
from candleviewer.ws.binary import HEATMAP_COLUMN, decode, encode
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.pacing import DEGRADED_THROTTLE_MS
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import PENDING_ADAPTERS, IngestionUpstreamSink, heatmap_part
from tests.unit.ws.test_app_wiring import _settings
from tests.unit.ws.test_pacing import _conn as _paced
from tests.unit.ws.test_pacing import _sub as _paced_sub

RS = "bb000000-0000-4000-8000-000000000001"
CH = "heatmap.BTCUSDT"


class _Sink:
    def __init__(self) -> None:
        self.opened: list[Any] = []

    async def open(self, key: Any) -> None:
        self.opened.append(key)

    async def drop(self, key: Any) -> None:
        return None


class _Hub:
    def publish(self, ch: str, body: Any = None, **kw: Any) -> int:
        return 0

    def flush_pending(self, match: Any = None) -> int:
        return 0


def _topic() -> HeatmapTopic:
    return HeatmapTopic(
        _Hub(), engine=lambda _s: None, steps=lambda _s: (Decimal("0.1"), Decimal("0.001")),
        part=heatmap_part, body=SnapshotBody, bus=Bus(), env="live", queue_bytes=8_388_608,
        queue_frames=2_000, clock_ms=lambda: 1_700_000_000_000.0,
    )  # fmt: skip


def _conn(
    topic: HeatmapTopic | None = None, user: int = 1, **services: Any
) -> tuple[ConnectionAuthz, _Sink]:
    sink = _Sink()
    principal = PrincipalSnapshot(
        uuid.UUID(int=user), frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ})
    )
    svc = SubscriptionServices(upstream=UpstreamRefs(sink), heatmap=topic, **services)
    return ConnectionAuthz(principal, svc), sink


def _sub(conn: ConnectionAuthz, *topics: dict[str, Any], **body: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    frame = {"t": "sub", "id": "s", "p": {"topics": list(topics), **body}}
    asyncio.run(handle_sub(conn, frame, send, now_ms=1))
    results: list[dict[str, Any]] = sent[0]["p"]["results"]
    return results


def _hm(symbol: str = "BTCUSDT", **opts: Any) -> dict[str, Any]:
    return {"ch": f"heatmap.{symbol}", "opts": opts}


def _code(result: dict[str, Any]) -> str | None:
    return None if result["ok"] else str(result["error"]["code"])


# -- G-04 ----------------------------------------------------------------------------------------


def test_heatmap_is_served_on_the_byte_budget() -> None:
    topic = _topic()
    conn, sink = _conn(topic)
    (ok,) = _sub(conn, _hm(time_bucket_ms=100))
    assert _code(ok) is None
    [sub] = conn.by_id.values()
    assert sub.heatmap_lease is not None
    assert sub.heatmap_lease.spec == HeatmapSpec("BTCUSDT", 200, 1, 100)
    assert [k[1] for k in sink.opened] == ["heatmap"]
    assert topic.build(sub) is None  # pending until the symbol's book is live (no engine here)
    assert conn.unsubscribe(CH) is not None and topic._symbols == {}


# -- depth 200 vs 500 ----------------------------------------------------------------------------


def test_heatmap_depth_500_is_refused_while_heatmap_depth_500_is_off() -> None:
    """D-row (#604 BQ-9): depth 500 is `invalid_topic_format` while the flag is off; depth 200
    is served."""
    conn, _ = _conn(_topic())
    deep, normal = _sub(conn, _hm(depth=500), _hm("ETHUSDT", depth=200))
    assert (_code(deep), _code(normal)) == ("invalid_topic_format", None)


@pytest.mark.parametrize("depth", [200, 500])
def test_a_replay_heatmap_is_unknown_topic(depth: int) -> None:
    """No replay producer serves `heatmap` yet, so a replay `sub` is refused
    `unknown_topic` (§10.2 "topic not served"), never left `snapshot_pending` for good."""
    topic = _topic()
    conn, sink = _conn(topic, depth_500=True)
    (refused,) = _sub(conn, _hm(depth=depth), replay_session_id=RS)
    assert _code(refused) == "unknown_topic"
    assert conn.by_id == {} and sink.opened == [] and topic._symbols == {}


def test_heatmap_depth_500_is_served_with_heatmap_depth_500_on() -> None:
    topic = _topic()
    conn, _ = _conn(topic, depth_500=True)
    assert _code(_sub(conn, _hm(depth=500))[0]) is None
    assert [s.depth for s in topic._symbols["BTCUSDT"].specs] == [500]


# -- G-02 ----------------------------------------------------------------------------------------


def test_the_fifth_spec_of_a_symbol_is_subscription_limit_across_users() -> None:
    """G-02 (23 §16.2): four specs a symbol, every user together; the fifth is refused before it
    is pending, naming the cap and never another user's specs; the same spec is shared."""
    topic = _topic()
    for user, g in enumerate((1, 2, 5, 10), start=1):  # one `heatmap.BTCUSDT` per connection
        assert _code(_sub(_conn(topic, user=user)[0], _hm(price_grouping=g))[0]) is None
    second, _ = _conn(topic, user=9)
    assert _code(_sub(second, _hm(price_grouping=2))[0]) is None  # shared: no new spec
    third, _ = _conn(topic, user=10)
    (refused,) = _sub(third, _hm(price_grouping=20, time_bucket_ms=100))
    assert _code(refused) == "subscription_limit"
    assert "4 heatmap specs per symbol" in refused["error"]["message"]
    assert third.by_id == {} and len(topic._symbols["BTCUSDT"].specs) == 4


def test_a_ctl_of_the_bucket_resnapshots_on_a_new_spec() -> None:
    """Gherkin "Bucket change re-snapshots": `ctl { time_bucket_ms: 500 }` answers resnapshot
    true, marks the subscription pending (the gateway then sends its fresh `snap`, §5.4) and
    moves its lease to the new spec, whose snapshot it gets."""
    topic = _topic()
    conn, _ = _conn(topic)
    _sub(conn, _hm(time_bucket_ms=100))
    [sub] = conn.by_id.values()
    sub.snapshot_pending = False
    echoed, resnapshot, same = conn.ctl(CH, {"time_bucket_ms": 500})
    assert (echoed["time_bucket_ms"], resnapshot, same is sub) == (500, True, True)
    assert sub.snapshot_pending and sub.pending_reason == "reconfigure"
    assert sub.heatmap_lease is not None and sub.heatmap_lease.spec.time_bucket_ms == 500
    assert list(topic._symbols["BTCUSDT"].specs) == [sub.heatmap_lease.spec]
    assert topic.build(sub) is None  # the new spec's snapshot waits for the live book


def test_a_ctl_past_a_cap_or_to_depth_500_changes_nothing() -> None:
    topic = _topic()
    for user, g in enumerate((2, 5, 10), start=2):
        _sub(_conn(topic, user=user)[0], _hm(price_grouping=g))
    conn, _ = _conn(topic)
    _sub(conn, _hm(price_grouping=1))
    _sub(_conn(topic, user=9)[0], _hm(price_grouping=1))  # a second lease: 1 is not freed
    sub = conn.find(CH)
    assert sub is not None
    held = sub.heatmap_lease
    with pytest.raises(Exception, match="4 heatmap specs") as cap:
        conn.ctl(CH, {"time_bucket_ms": 1000})
    assert getattr(cap.value, "code", None) == "subscription_limit"
    with pytest.raises(Exception, match="depth 500") as deep:
        conn.ctl(CH, {"depth": 500})
    assert getattr(deep.value, "code", None) == "invalid_topic_format"
    assert sub.heatmap_lease == held


# -- D-row: saturation ---------------------------------------------------------------------------


def test_saturation_degrades_heatmap_to_1000ms_with_degraded_topics() -> None:
    """D-row (§8.3): a `saturated` connection holds `heatmap` to one frame a second and names the
    topic in the notice's `degraded_topics` (the pacer's own rule, `pacing.py`)."""
    conn, pacer = _paced()
    heatmap = _paced_sub(conn, CH, time_bucket_ms=100)
    book = _paced_sub(conn, "book.BTCUSDT.50")
    notice = pacer.classify(70.0, [heatmap, book], now=100.0)
    assert notice is not None
    assert notice["applied"]["degraded_topics"] == [CH]
    assert pacer.throttle_ms(heatmap) == DEGRADED_THROTTLE_MS


# -- the composition root ------------------------------------------------------------------------


def test_create_app_serves_heatmap_from_its_publisher() -> None:
    app = create_app(_settings())
    services = app.state.ws_registry.services
    topic = services.snapshots._sources["heatmap"]
    assert isinstance(topic, HeatmapTopic) and topic is services.heatmap
    assert topic in app.state.ws_runtime.feeds and "heatmap" not in PENDING_ADAPTERS
    assert not hasattr(services, "heatmap_off")  # G-04: no gate left to close (#2409)


class _Stream(BookStream):
    def __init__(self) -> None:  # no ingestion: only the demand calls are seen
        self.calls: list[tuple[Any, ...]] = []

    def acquire(self, consumer: str, symbol: str) -> None:
        self.calls.append(("acquire", consumer, symbol))

    def release(self, consumer: str, symbol: str) -> None:
        self.calls.append(("release", consumer, symbol))


async def test_a_heatmap_reference_holds_the_symbols_book() -> None:
    stream = _Stream()
    sink = IngestionUpstreamSink(lambda family: stream if family in ("book", "heatmap") else None)
    await sink.open(("BTCUSDT", "heatmap", ()))
    await sink.drop(("BTCUSDT", "heatmap", ()))
    assert stream.calls == [
        ("acquire", "ws:heatmap:", "BTCUSDT"), ("release", "ws:heatmap:", "BTCUSDT"),
    ]  # fmt: skip


def test_heatmap_part_is_a_one_column_kind_6_frame() -> None:
    frame = heatmap_part(1_700_000_000_000, 99_510, 1, ((1_000, 2_000),), 1, 3, True)
    assert frame.body_kind == HEATMAP_COLUMN and frame.flags & 1
    assert frame.raw is not None  # packed at the close: encoded once (#605)
    back = structured(decode(encode(frame)))
    assert back["columns"] == [
        {"t_ms": 1_700_000_000_000, "price_min": "9951.0", "price_step": "0.1",
         "bids": [1.0], "asks": [2.0]}
    ]  # fmt: skip
    assert back["estimated"] is True
