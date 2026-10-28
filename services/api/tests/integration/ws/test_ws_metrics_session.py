"""E17-T06 (#571), test plan "Integration": after a scripted WS session (connect, subscribe, resync,
overflow, close) every expected metric moved, and no unexpected label value appeared.

The session runs the real `/ws` router on the test's own loop behind `_Wire` (the rig of
`tests/unit/ws/test_pipeline_outbound.py`): no thread, no sleep, a fake clock, every wait bounded.
It runs with the backpressure flag on (one connection per step that needs its own queue, below),
plus a flag-off pass on MessagePack with a binary book, for the series only that wiring moves.

What a scrape sees is what the test reads: `export_ws_metrics` and `export_cvwb_metrics` on a
fresh registry (the ones `create_app` serves), rendered by `generate_latest` and parsed back from
the exposition text. The registries are process-global, so every assertion is a delta between a
scrape before and one after the session; test order never matters.

Deliverable of #571 (Scope / Deliverables) -> series asserted:

* connection count and class gauges: `cv_ws_connections_in_use`, `cv_ws_connection_class{state}`
  (up while open, back down after the close; `cv_ws_clients` is the ticket's name for the first);
* `cv_ws_topics_per_client` -> `cv_ws_client_topics_depth` (one observation per subscribe step);
* `cv_ws_resync_total{reason}` -> `client_resync` (the client's `resync`) and `backpressure`;
* `cv_ws_overflow_total{reason}` -> `drop`, `resnapshot`, `close_budget`, `withdrawn`;
* `cv_ws_conflated_total{topic_family}` -> `cv_ws_conflated_total{topic}` (`book`), and the
  `cv_ws_coalesced_count` histogram -> `cv_ws_coalesced_updates`;
* `cv_ws_frame_encode_seconds{kind}`, `cv_ws_frame_bytes{kind}` -> `json`, `msgpack`, and the CVWB
  `kind` of a binary book snapshot; `cvwb_frames_encoded_total`, `cvwb_bytes_encoded_total`;
* `cv_ws_snapshot_build_seconds{topic_family}`, `cv_ws_snapshot_bytes{topic_family}` -> `topic`
  `book`, `trades`, `orders` (one public of each shape and a private family);
* `cv_ws_fanout_seconds` (the budget #6 histogram, weighted 1 in `SAMPLE_EVERY`);
* `cv_ws_queue_bytes`, `cv_ws_queue_frames`, `cv_ws_rtt_seconds` (one observation per
  classification, flag on, the probe answered with a `pong`);
* `cv_ws_closes_total{reason}` -> `shutdown`, `slow_consumer`; `cv_ws_auth_failures_total{reason}`;
  `cv_ws_revoked_total{reason}` -> `permission_revoked`; `cv_ws_clock_skew_ms`, and the E17-S01
  (#377) / E17-S02 (#378) `cv_ws_handshake_seconds` and `cv_ws_subscribe_total{topic,result}`.

Not coverable here, each named so nobody reads the gap as an oversight:

* `cv_ws_errors_total{code}`: counted in process only and not served (not on the SR-125 label
  allow-list, #2747), so no scrape shows it; `tests/unit/ws/test_error_registry_runtime.py` owns it.
* `cv_ws_sequence_gaps_detected_total`: the server guarantees it stays zero; it is asserted
  unmoved here, which is its contract.
* `cv_ws_upstream_consumers_in_use{symbol,topic}`, `cv_ws_stale_topics_in_use`: they need the
  ingestion-side `UpstreamRefs` wiring; the rig's refs are inert. The label audit still covers
  whatever such a series holds.
* `cv_ws_overflow_total{drop_share,unmergeable,close_redrop,close_flush_deadline}` and
  `cv_ws_resync_total{upstream_desync,...}`: each needs a different fault (a shared budget, an
  unmergeable window, a second overflow, an expired flush, an upstream gap); the per-series unit
  tests (`test_pipeline_ladder.py`, `test_sequencing.py`) own them. The label audit pins the sets.
* The Grafana panels, the alerts and a frontend mark: other deliverables of the ticket.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable
from typing import Any, Final, NamedTuple, get_args

import msgpack
import pytest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.auth.generated_permissions import Permission
from candleviewer.observability.metrics import CollectorRegistry, generate_latest
from candleviewer.observability.metrics_catalogue import CATALOGUE, MetricSpec
from candleviewer.ws._generated.cvwb_layout import KINDS
from candleviewer.ws._generated.error_codes import WS_ERROR_CODES
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.coalescing import MERGED_FAMILIES
from candleviewer.ws.lifecycle import CLOSE_REASONS, OTHER_CLOSE_REASON
from candleviewer.ws.metrics import (
    AUTH_FAILURE_REASONS,
    CV_WS_NAMES,
    EXPORTED_NAMES,
    FRAME_KINDS,
    SAMPLE_EVERY,
    export_cvwb_metrics,
    export_ws_metrics,
)
from candleviewer.ws.pacing import ConnectionClass
from candleviewer.ws.revocation import RevokedReason
from candleviewer.ws.sequencing import COUNTED_SNAP_REASONS, SnapshotBody
from candleviewer.ws.topics import FAMILIES, MACHINE_KINDS
from candleviewer.ws.upstream import cv_ws_upstream_consumers_in_use  # noqa: F401  (registers it)
from tests.unit.ws._seq_support import ACC_A, USER
from tests.unit.ws.test_lifecycle_socket import BASE_MS, SESSION
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _DEADLINE_S,
    _JSON,
    _MSGPACK,
    _no_sleep,
    _Rig,
    _Wire,
)

_TRADES = "trades.BTCUSDT"
_BODY: Final = {"symbol": "BTCUSDT", "depth": 50, "asks": []}
#: Frames the sampler stamps: one in `SAMPLE_EVERY` per subscription, weighted by it.
_DELTAS = 2 * SAMPLE_EVERY

Key = tuple[str, frozenset[tuple[str, str]]]


class Scrape(dict[Key, float]):
    """One scrape: (sample name, labels without `env`) -> value."""

    def value(self, name: str, **labels: str) -> float:
        return self.get((name, frozenset(labels.items())), 0.0)

    def names(self) -> set[str]:
        return {name for name, _ in self}


def scrape() -> Scrape:
    """The WS series as `/metrics` serves them: the exporters on a fresh registry, rendered as
    the exposition text and parsed back."""
    registry = CollectorRegistry()
    export_ws_metrics(registry, env="test")
    export_cvwb_metrics(registry, env="test")
    out = Scrape()
    for family in text_string_to_metric_families(generate_latest(registry).decode()):
        for s in family.samples:
            labels = frozenset((k, v) for k, v in s.labels.items() if k != "env")
            out[(s.name, labels)] = s.value
    return out


class Run(NamedTuple):
    before: Scrape
    mid: Scrape  # connection 1 open, subscribed to three topics
    after: Scrape

    def delta(self, name: str, **labels: str) -> float:
        return self.after.value(name, **labels) - self.before.value(name, **labels)

    def up(self, name: str, **labels: str) -> float:
        """A gauge while connection 1 was open, against before."""
        return self.mid.value(name, **labels) - self.before.value(name, **labels)


def _delta_of(book: int, **extra: Any) -> dict[str, Any]:
    return {**_BODY, "bids": [[f"{100 + book}.0", "1.000"]], **extra}


async def _ticks(sock: _Wire, rig: _Rig, n: int, publish: Callable[[int], Any]) -> None:
    """`n` deltas, one at a time and 1.5 s apart on the fake clock, so each leaves its throttle
    window alone and the classification (1 s) runs between them; the frame is awaited."""
    for i in range(n):
        rig.clock.now += 1.5
        publish(i)
        await sock.next()


async def _flag_on_connection() -> Scrape:
    """Connection 1: hello, auth, three subscribes (public book, public trades, private orders),
    64 deltas (two sampled), a client resync, a merged window, an overflow that the ladder drops
    and re-snapshots (a parked writer, a budget of 8 frames), an unsub, a planned shutdown."""
    rig = _Rig(BackpressureConfig(max_frames=8, classify_interval_ms=1000))
    rig.source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    sock = _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        await rig.sub(sock, _TRADES)
        await rig.sub(sock, "orders")
        mid = scrape()
        await _ticks(sock, rig, _DELTAS, lambda i: rig.sequencing.publish(_BOOK, _delta_of(i)))
        sock.feed({"t": "resync", "id": "r", "ch": _BOOK, "p": {"reason": "manual"}})
        assert [f["t"] for f in await sock.next()] == ["snap"]
        # Three book deltas inside one throttle window merge into one frame.
        for i in range(3):
            rig.sequencing.publish(_BOOK, _delta_of(i))
        rig.clock.now += 1.0
        assert [f["t"] for f in await sock.next()] == ["d"]
        # Overflow: park the writer, fill the 8-frame budget past it; the ladder drops the book's
        # queued deltas (step 1), then queues its `backpressure` snapshot once the queue is below
        # half (step 2). Nothing closes.
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()
        for _ in range(4):
            rig.hub.broadcast_system({"kind": "tick"})
        for i in range(5):
            rig.book_delta(i)
        sock.release()
        assert [f["t"] for f in await sock.next(6)] == ["d"] * 5 + ["snap"]
        # One more classification, answered by the wire's `pong`.
        rig.clock.now += 1.5
        rig.sequencing.publish(_BOOK, _delta_of(0))
        await sock.next()
        sock.feed({"t": "unsub", "id": "u", "p": {"topics": [_TRADES]}})
        assert [f["t"] for f in await sock.next()] == ["unsub_ok"]
        await rig.hub.shutdown(grace_ms=0, sleep=_no_sleep)
        await handler
    assert conn.closing and sock.pings  # the RTT probe pinged and the wire answered
    return mid


async def _slow_consumer_connection() -> None:
    """Connection 2: nine frames in one turn against a budget of eight (§8.4 step 3)."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        for i in range(9):
            rig.hub.broadcast_system({"kind": "tick", "n": i})
        (bye,) = await sock.next()
        await handler
    assert bye["p"]["reason"] == "slow_consumer"


async def _withdrawn_connection() -> None:
    """Connection 3: the permission of `orders` is removed while frames of it are queued behind a
    parked writer: they are dropped (`withdrawn`), the topic is revoked (`permission_revoked`)."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        await rig.sub(sock, "orders")
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()
        for i in range(3):
            rig.sequencing.publish("orders", {"orders": [], "n": i}, account=ACC_A)
        rig.perms = rig.perms - {Permission.ORDERS_READ}
        await rig.registry.roles_changed(USER)
        sock.release()
        sent: list[dict[str, Any]] = []
        while not any(f["t"] == "revoked" for f in sent):
            sent += await sock.next()
        assert [f["t"] for f in sent] == [
            "d",
            "permission_change",
            "revoked",
        ]  # the held `system` frame
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await handler
    assert conn.pipeline is not None


async def _failed_auth_connection() -> None:
    """Connection 4: an `auth` frame with no token."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler = asyncio.create_task(rig.endpoint(sock))
        sock.feed({"t": "hello", "id": "h", "p": {"clock_ms": BASE_MS}})
        assert [f["t"] for f in await sock.next()] == ["welcome"]
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": ""}})
        frames = [await sock.next()]
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await handler
    assert frames


async def _flag_off_connection() -> None:
    """The flag-off wiring, on `cv.v1.msgpack`: the writer (not the pipeline) encodes and observes
    the stamped frames; a binary book snapshot feeds the CVWB series."""
    rig, sock = _Rig(None), _Wire(_MSGPACK)
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        sock.feed({"t": "sub", "id": "s", "p": {"topics": [{"ch": _BOOK, "opts": {}}]}})
        await sock.next(2)
        for i in range(SAMPLE_EVERY):
            rig.sequencing.publish(_BOOK, _delta_of(i))
        await sock.next(SAMPLE_EVERY)
        await rig.hub.shutdown(grace_ms=0, sleep=_no_sleep)
        await handler
    assert sock.raw and all(kind == "bytes" for kind, _ in sock.raw)
    assert msgpack.unpackb(sock.raw[-1][1])["t"] == "bye"


@pytest.fixture
async def run() -> Run:
    """The scripted session, once per test (each one is a few milliseconds): a scrape before, one
    while connection 1 is open, and one after every connection has closed."""
    before = scrape()
    mid = await _flag_on_connection()
    await _slow_consumer_connection()
    await _withdrawn_connection()
    await _failed_auth_connection()
    await _flag_off_connection()
    return Run(before, mid, scrape())


# -- every expected series moved ---------------------------------------------------------------


async def test_session_connection_gauges_rise_while_open_and_return_after_close(run: Run) -> None:
    """Connection count and class gauges (the ticket's `cv_ws_clients`, the classes)."""
    assert run.up("cv_ws_connections_in_use") == 1
    assert run.up("cv_ws_connection_class", state="healthy") == 1
    assert run.delta("cv_ws_connections_in_use") == 0
    assert all(run.delta("cv_ws_connection_class", state=c.value) == 0 for c in ConnectionClass)


async def test_session_handshake_clock_skew_and_topics_depth_are_observed(run: Run) -> None:
    """E17-S01 handshake and clock skew; `cv_ws_topics_per_client` as one depth per subscribe step
    (connection 1: 1, 2, 3 topics)."""
    assert run.delta("cv_ws_handshake_seconds_count") >= 4  # one `auth_ok` on each connection
    assert run.delta("cv_ws_clock_skew_ms_count") >= 4
    assert run.up("cv_ws_client_topics_depth_count") == 3
    assert run.up("cv_ws_client_topics_depth_sum") == 1 + 2 + 3


@pytest.mark.parametrize(
    ("topic", "ok"), [("book", 2), ("trades", 1), ("orders", 2)], ids=lambda v: str(v)
)
async def test_session_subscribe_results_count_each_topic_family(
    run: Run, topic: str, ok: int
) -> None:
    """E17-S02 `cv_ws_subscribe_total{topic,result}`: the subscribes of the session, by family."""
    assert run.delta("cv_ws_subscribe_total", topic=topic, result="ok") >= ok


@pytest.mark.parametrize("topic", ["book", "trades", "orders"])
async def test_session_snapshots_are_timed_and_sized_by_topic_family(run: Run, topic: str) -> None:
    """`cv_ws_snapshot_build_seconds{topic}` and `cv_ws_snapshot_bytes{topic}`."""
    assert run.delta("cv_ws_snapshot_build_seconds_count", topic=topic) >= 1
    assert run.delta("cv_ws_snapshot_bytes_count", topic=topic) >= 1
    assert run.delta("cv_ws_snapshot_bytes_sum", topic=topic) > 0


async def test_session_fanout_is_observed_in_sample_weights(run: Run) -> None:
    """Budget #6 `cv_ws_fanout_seconds`: one frame in `SAMPLE_EVERY` is stamped and observed with
    that weight; 64 deltas on a subscription stamp two."""
    count = run.delta("cv_ws_fanout_seconds_count")
    assert count >= _DELTAS and count % SAMPLE_EVERY == 0
    assert run.delta("cv_ws_fanout_seconds_sum") >= 0


@pytest.mark.parametrize("kind", ["json", "msgpack"])
async def test_session_frame_encode_time_and_size_are_observed_per_codec(
    run: Run, kind: str
) -> None:
    """`cv_ws_frame_encode_seconds{kind}` and `cv_ws_frame_bytes{kind}`: `json` from the flag-on
    connections (the pipeline's one encode), `msgpack` from the flag-off one (the writer's)."""
    seconds = run.delta("cv_ws_frame_encode_seconds_count", kind=kind)
    sized = run.delta("cv_ws_frame_bytes_count", kind=kind)
    assert seconds >= SAMPLE_EVERY and seconds == sized
    assert run.delta("cv_ws_frame_bytes_sum", kind=kind) > 0


async def test_session_cvwb_binary_frames_are_counted_by_kind(run: Run) -> None:
    """`cvwb_frames_encoded_total{kind}` and `cvwb_bytes_encoded_total{kind}`: a binary book
    snapshot encodes `book_snapshot` parts."""
    moved = {v.name: run.delta("cvwb_frames_encoded_total", kind=v.name) for v in KINDS.values()}
    assert moved["book_snapshot"] >= 1, moved
    assert run.delta("cvwb_bytes_encoded_total", kind="book_snapshot") > 0
    assert run.delta("cv_ws_frame_encode_seconds_count", kind="book_snapshot") >= 1


async def test_session_resyncs_count_by_reason(run: Run) -> None:
    """`cv_ws_resync_total{reason}`: the client's `resync` and the ladder's `backpressure`; the
    routine `initial` attach is not counted (it has no series)."""
    assert run.delta("cv_ws_resync_total", reason="client_resync") == 1
    assert run.delta("cv_ws_resync_total", reason="backpressure") == 1
    assert ("cv_ws_resync_total", frozenset({("reason", "initial")})) not in run.after


@pytest.mark.parametrize(
    ("reason", "moved"),
    [("drop", 1), ("resnapshot", 1), ("close_budget", 1), ("withdrawn", 3)],
)
async def test_session_overflow_counts_each_ladder_step_by_reason(
    run: Run, reason: str, moved: int
) -> None:
    """`cv_ws_overflow_total{reason}`: the drop and the re-snapshot of the parked writer, the
    budget close of the slow consumer, and the three `orders` frames a withdrawal dropped."""
    assert run.delta("cv_ws_overflow_total", reason=reason) == moved


async def test_session_merged_window_is_counted_as_conflated_and_coalesced(run: Run) -> None:
    """`cv_ws_conflated_total{topic}` (the ticket's `topic_family`): a window of three book
    deltas conflates two; `cv_ws_coalesced_updates` observes it once, with three updates."""
    assert run.delta("cv_ws_conflated_total", topic="book") == 2
    assert run.delta("cv_ws_coalesced_updates_count") >= 1
    assert run.delta("cv_ws_coalesced_updates_sum") >= 3


async def test_session_queue_depth_and_rtt_are_observed_once_per_classification(
    run: Run,
) -> None:
    """`cv_ws_queue_bytes`, `cv_ws_queue_frames` and `cv_ws_rtt_seconds`: one observation per
    classification of a flag-on connection, so all three move together."""
    rtt = run.delta("cv_ws_rtt_seconds_count")
    assert rtt >= _DELTAS
    assert run.delta("cv_ws_queue_bytes_count") == run.delta("cv_ws_queue_frames_count") == rtt


async def test_session_closes_count_by_reason(run: Run) -> None:
    """`cv_ws_closes_total{reason}`: the planned shutdowns (connection 1 and the flag-off one)
    and the slow consumer; no reason that nothing closed with moved."""
    assert run.delta("cv_ws_closes_total", reason="shutdown") == 2
    assert run.delta("cv_ws_closes_total", reason="slow_consumer") == 1
    quiet = set(CLOSE_REASONS) - {"shutdown", "slow_consumer"}
    assert {r for r in quiet if run.delta("cv_ws_closes_total", reason=r)} <= {"normal"}


async def test_session_failed_auth_and_withdrawn_grant_are_counted_by_reason(run: Run) -> None:
    """`cv_ws_auth_failures_total{reason}` and `cv_ws_revoked_total{reason}`."""
    assert run.delta("cv_ws_auth_failures_total", reason="missing_token") == 1
    assert run.delta("cv_ws_revoked_total", reason="permission_revoked") == 1


async def test_session_server_sequence_gaps_stay_at_zero(run: Run) -> None:
    """`cv_ws_sequence_gaps_detected_total` is the server's guarantee: a clean session leaves it."""
    assert run.delta("cv_ws_sequence_gaps_detected_total") == 0


# -- no unexpected label value appeared --------------------------------------------------------

#: Closed label sets, series name -> label -> allowed values, from the constants that define them
#: (never from the session). A labelled WS series missing here fails `..._is_audited`.
_TOPIC_FAMILIES: Final = frozenset(FAMILIES) | {"unknown"}
_OVERFLOW: Final = frozenset(
    {
        "drop",
        "drop_share",
        "unmergeable",
        "resnapshot",
        "close_budget",
        "close_redrop",
        "close_flush_deadline",
        "withdrawn",
    }
)
_CLOSED: Final[dict[str, dict[str, frozenset[str]]]] = {
    "cvwb_frames_encoded_total": {"kind": frozenset(k.name for k in KINDS.values())},
    "cvwb_bytes_encoded_total": {"kind": frozenset(k.name for k in KINDS.values())},
    "cv_ws_auth_failures_total": {"reason": frozenset(AUTH_FAILURE_REASONS)},
    "cv_ws_closes_total": {"reason": frozenset({*CLOSE_REASONS, OTHER_CLOSE_REASON})},
    "cv_ws_system_frames_withheld_total": {
        "reason": frozenset({"unknown_kind", "invalid_body", "no_principal", "no_role"})
    },
    "cv_ws_audit_failures_total": {
        "reason": frozenset({"error", "timeout", "cancelled", "abandoned"})
    },
    "cv_ws_revoked_total": {"reason": frozenset(get_args(RevokedReason))},
    "cv_ws_resync_total": {"reason": frozenset(COUNTED_SNAP_REASONS)},
    "cv_ws_overflow_total": {"reason": _OVERFLOW},
    "cv_ws_conflated_total": {"topic": frozenset(MERGED_FAMILIES)},
    "cv_ws_connection_class": {"state": frozenset(c.value for c in ConnectionClass)},
    "cv_ws_frame_encode_seconds": {"kind": frozenset(FRAME_KINDS)},
    "cv_ws_frame_bytes": {"kind": frozenset(FRAME_KINDS)},
    "cv_ws_snapshot_bytes": {"topic": _TOPIC_FAMILIES},
    "cv_ws_snapshot_build_seconds": {"topic": _TOPIC_FAMILIES},
    "cv_ws_malformed_updates_total": {"topic": _TOPIC_FAMILIES},
    "cv_ws_subscribe_total": {"topic": _TOPIC_FAMILIES},
    "cv_ws_permission_snapshots_refused_total": {"event": frozenset()},  # checked as non-empty
    "cv_ws_rebuild_refused_total": {"kind": frozenset(), "cause": frozenset()},
    "cv_ws_upstream_consumers_in_use": {"topic": _TOPIC_FAMILIES, "symbol": frozenset()},
    "cv_machine_ws_publish_total": {"entity_kind": frozenset(MACHINE_KINDS)},
    "cv_machine_ws_scope_missing_total": {"entity_kind": frozenset(MACHINE_KINDS)},
    "cv_machine_ws_registry_full_total": {"entity_kind": frozenset(MACHINE_KINDS)},
}
_CLOSED["cv_ws_subscribe_total"]["result"] = frozenset()  # `ok` or an error code, checked apart
#: Label values these series take from a set the module that owns it keeps beyond the test's reach
#: (a refusal's cause, a permission event, an error code): not enumerated, but bounded by the
#: catalogue's `max_series` and free of identifiers (the checks below).
_OPEN_VALUED: Final = frozenset(
    {
        ("cv_ws_permission_snapshots_refused_total", "event"),
        ("cv_ws_rebuild_refused_total", "kind"),
        ("cv_ws_rebuild_refused_total", "cause"),
        ("cv_ws_upstream_consumers_in_use", "symbol"),
        ("cv_ws_subscribe_total", "result"),
    }
)
_SUFFIXES: Final = ("_bucket", "_count", "_sum", "_total", "_created")
_UUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_CONNECTION_ID: Final = re.compile(r"ws_[0-9a-f]{12}")
#: A token-shaped value: 16+ characters of hex or base64url, never a word of a closed set.
_TOKEN: Final = re.compile(r"[A-Za-z0-9_\-+/=]{16,}")
_SYMBOL: Final = re.compile(r"[A-Z0-9]{2,20}USDT")


def _series_name(sample: str, names: Iterable[str]) -> str:
    """The series a sample belongs to (`..._bucket`, `..._count`, ... stripped)."""
    known = set(names)
    for candidate in (sample, *(sample.removesuffix(s) for s in _SUFFIXES)):
        if candidate in known:
            return candidate
        if f"{candidate}_total" in known:
            return f"{candidate}_total"
    return sample


def _ws_specs() -> dict[str, MetricSpec]:
    served = CV_WS_NAMES | EXPORTED_NAMES
    return {s.name: s for s in CATALOGUE if s.name in served and s.exported}


def _labelled(after: Scrape) -> list[tuple[str, dict[str, str]]]:
    """Every (series, labels) of the scrape, `le` dropped, one entry per distinct label set."""
    specs = _ws_specs()
    seen: dict[tuple[str, frozenset[tuple[str, str]]], None] = {}
    for sample, labels in after:
        name = _series_name(sample, specs)
        if name in specs:
            seen[(name, frozenset((k, v) for k, v in labels if k != "le"))] = None
    return [(name, dict(labels)) for name, labels in seen]


async def test_session_label_names_are_the_catalogued_ones(run: Run) -> None:
    """Every WS series of the scrape carries exactly the label names the catalogue declares."""
    specs = _ws_specs()
    seen = _labelled(run.after)
    for name, labels in seen:
        assert set(labels) == set(specs[name].labels), name
    # Not vacuous: the series the session moved are among the ones checked.
    moved = {
        "cv_ws_overflow_total",
        "cv_ws_closes_total",
        "cv_ws_resync_total",
        "cv_ws_frame_bytes",
    }
    assert moved <= {name for name, _ in seen}


async def test_session_label_values_belong_to_their_closed_sets(run: Run) -> None:
    """Every label value on every labelled series is in the series' closed set (the reason enums,
    the kinds, the topic families, the classes), whatever the session did or other tests left."""
    unexpected = [
        (name, label, value)
        for name, labels in _labelled(run.after)
        for label, value in labels.items()
        if (name, label) not in _OPEN_VALUED and value not in _CLOSED[name][label]
    ]
    assert unexpected == []


async def test_session_subscribe_result_is_ok_or_a_catalogued_error_code(run: Run) -> None:
    """`cv_ws_subscribe_total{result}` is `ok` or one of the closed 23 section 10.2 codes."""
    results = {
        labels["result"] for name, labels in _labelled(run.after) if name == "cv_ws_subscribe_total"
    }
    assert "ok" in results and results <= {"ok", *WS_ERROR_CODES}


async def test_session_labelled_series_is_audited(run: Run) -> None:
    """Every labelled WS series the catalogue lists has a closed set above, so a new one cannot
    slip in unchecked; no series is served that the catalogue does not list."""
    labelled = {name for name, s in _ws_specs().items() if s.labels}
    assert labelled <= set(_CLOSED)
    specs = _ws_specs()
    served = {_series_name(n, CV_WS_NAMES | EXPORTED_NAMES) for n, _ in run.after}
    assert {n for n in served if n.startswith(("cv_ws_", "cvwb_"))} <= set(specs)


async def test_session_series_counts_stay_within_the_catalogue_caps(run: Run) -> None:
    """No WS series holds more label sets than its `max_series` (the cardinality audit's table)."""
    counts: dict[str, int] = {}
    for name, _ in _labelled(run.after):
        counts[name] = counts.get(name, 0) + 1
    over = {
        n: (c, _ws_specs()[n].max_series)
        for n, c in counts.items()
        if c > _ws_specs()[n].max_series
    }
    assert over == {}


async def test_session_no_label_value_is_an_identifier(run: Run) -> None:
    """No label value is a user, account, session, connection or span id, a token, or a symbol:
    the ids and tokens the session used are matched literally, the rest by shape. The one series
    that may name a symbol folds the rest into `other`."""
    forbidden = {str(USER), str(ACC_A), SESSION, "tok", "BTCUSDT", "h", "a", "s"}
    for name, labels in _labelled(run.after):
        for label, value in labels.items():
            if (name, label) == ("cv_ws_upstream_consumers_in_use", "symbol"):
                continue
            assert value not in forbidden, (name, label, value)
            assert not _UUID.fullmatch(value), (name, label, value)
            assert not _CONNECTION_ID.search(value), (name, label, value)
            assert not _SYMBOL.fullmatch(value), (name, label, value)
            assert not (_TOKEN.fullmatch(value) and value not in _closed_values()), (
                name,
                label,
                value,
            )


def _closed_values() -> frozenset[str]:
    values = {v for labels in _CLOSED.values() for vs in labels.values() for v in vs}
    return frozenset(values | {"ok", *WS_ERROR_CODES})


async def test_session_symbols_appear_only_on_the_upstream_series_and_fold_into_other(
    run: Run,
) -> None:
    """`symbol` is a label of `cv_ws_upstream_consumers_in_use` alone, and there at most 20
    distinct symbols and `other` (cap 210 = 21 x 10 public families)."""
    with_symbol = {name for name, labels in _labelled(run.after) if "symbol" in labels}
    assert with_symbol <= {"cv_ws_upstream_consumers_in_use"}
    symbols = {
        labels["symbol"]
        for name, labels in _labelled(run.after)
        if name == "cv_ws_upstream_consumers_in_use"
    }
    assert len(symbols) <= 21 and all(s == "other" or _SYMBOL.fullmatch(s) for s in symbols)
