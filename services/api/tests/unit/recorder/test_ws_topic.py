"""#492 S6: the `recorder` WS topic over the real `SequencingHub` and `TopicEmitter` (every frame
they send is checked against `cv://ws/v1/recorder.schema.json`). Pending until a runtime is bound,
then the snapshot first and one whole frame a second; the `symbols` filter; the R-I2 view recorded
at admit for everyone but the Owner (ruling Q6), never carrying `position_open` or a path; a full
frame only for a principal that is the Owner now; a publish that raises re-snapshots with
`upstream_desync`; the subscription gauge. The size and CPU budgets run in the perf lane."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.recorder import control as rc
from candleviewer.recorder.policy import PolicyConfig
from candleviewer.recorder.status import RecordingStatusCache
from candleviewer.recorder.ws_topic import RecorderTopic, frame
from candleviewer.ws.metrics import cv_ws_recorder_subscriptions_in_use
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws_wiring import recorder_topic
from tests.contract.ws._harness import check_schema
from tests.unit.recorder._budget_fakes import FakeMeter, make_budget
from tests.unit.recorder._control_fakes import NOW, FakeRecorder
from tests.unit.ws._seq_support import PERMS, Conn

_REC = "cv://ws/v1/recorder.schema.json"
_PATHISH = re.compile(r'[/\\]|"[A-Za-z]:')
WALL = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _runtime(symbols: int = 0) -> FakeRecorder:
    fake = FakeRecorder()
    fake.put("BTCUSDT", pinned=True, lag_ms=42, rows_last_hour=7, dropped_messages=0,
             resyncs_last_hour=1, disk_bytes=10**9, last_event_at=NOW)  # fmt: skip
    fake.put("ETHUSDT", "position_open", "chart_open", refusals=("position_open", "chart_open"),
             lingering=True, linger_until=NOW)  # fmt: skip
    fake.put("XRPUSDT", "position_open", refusals=("position_open",))
    fake.put("SOLUSDT", "chart_open", state="idle", refusals=("symbol_cap",))
    for n in range(symbols):
        fake.put(f"S{n:02d}USDT", "chart_open", lag_ms=5, rows_last_hour=10**9, lingering=False,
                 dropped_messages=0, resyncs_last_hour=0, disk_bytes=10**11)  # fmt: skip
    link = rc.Connection("wss://stream.bybit.com/v5/public/linear", "connected", 14, NOW, 0, 18)
    fake.status_fields = {"connections": (link,), "policy": PolicyConfig()}
    return fake


@dataclass
class _World:
    hub: SequencingHub
    topic: RecorderTopic[SnapshotBody]
    cache: RecordingStatusCache
    runtime: FakeRecorder | None = None


def _world(runtime: FakeRecorder | None = None, **kw: Any) -> _World:
    hub = SequencingHub()
    world = _World(hub, recorder_topic(hub), cast(RecordingStatusCache, None), runtime)
    budget = make_budget(FakeMeter())[0]
    world.cache = RecordingStatusCache(lambda: world.runtime, budget, wall=lambda: WALL, **kw)
    world.topic.attach(world.cache)
    return world


class _Unchecked(Conn):
    """A connection that only encodes its frames, as a socket would (no schema check)."""

    def push(self, frame: dict[str, Any]) -> None:
        self.out.append(frame)
        json.dumps(frame)


def _conn(
    w: _World, *, owner: bool = False, symbols: list[str] | None = None, cls: type[Conn] = Conn
) -> Conn:
    conn = cls(cast(Any, w.topic), user=uuid.uuid4())
    roles = frozenset({"owner" if owner else "manager"})
    perms = PERMS | {Permission.RECORDING_READ}
    conn.authz.principal = replace(conn.authz.principal, roles=roles, permissions=perms)
    w.hub.register(conn.authz, conn.emitter)
    conn.sub({"ch": "recorder"} | ({"opts": {"symbols": symbols}} if symbols else {}))
    return conn


def _payloads(conn: Conn) -> list[tuple[str, dict[str, Any]]]:
    return [(f["t"], f["p"]) for f in conn.take() if f["t"] in ("snap", "d")]


async def test_pending_until_bound_then_the_snapshot_first_and_one_frame_a_second() -> None:
    slept: list[float] = []
    done = asyncio.Event()

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:
            done.set()
            await asyncio.Event().wait()

    w = _world(sleep=sleep)
    owner, other = _conn(w, owner=True), _conn(w)
    sub = owner.authz.find("recorder", None)
    assert sub is not None and w.topic.build(sub) is None
    await w.cache.refresh_once()  # no runtime yet: still pending, nothing sent
    assert _payloads(owner) == _payloads(other) == []
    w.runtime = _runtime()
    w.cache.start()
    await done.wait()
    await w.cache.stop()
    for conn in (owner, other):
        assert [t for t, _ in _payloads(conn)] == ["snap", "d", "d"]  # one frame per computation
    assert slept == [1.0, 1.0, 1.0]


async def test_the_symbols_option_narrows_the_frame() -> None:
    w = _world(_runtime())
    full = _conn(w, owner=True, symbols=["ETHUSDT", "DOGEUSDT"])
    restricted = _conn(w, symbols=["XRPUSDT", "DOGEUSDT", "BTCUSDT"])
    await w.cache.refresh_once()
    ((_, snap),) = _payloads(full)
    assert [(r["symbol"], r["state"]) for r in snap["symbols"]] == [
        ("DOGEUSDT", "idle"), ("ETHUSDT", "recording")]  # fmt: skip
    ((_, snap),) = _payloads(restricted)  # an untracked symbol is unknown, never idle
    assert [r["symbol"] for r in snap["symbols"]] == ["BTCUSDT"]


async def test_restricted_frames_never_carry_position_open_or_a_path() -> None:
    w = _world(_runtime())
    owner, other = _conn(w, owner=True), _conn(w)
    for _ in range(2):
        await w.cache.refresh_once()
    full, restricted = _payloads(owner), _payloads(other)
    assert "position_open" in json.dumps(full) and len(restricted) == 2
    for _, body in restricted:
        text = json.dumps(body)
        assert body["role_restricted"] is True and "position_open" not in text
        assert _PATHISH.search(text) is None
        assert {r["symbol"]: r.get("refusal") for r in body["symbols"]}["ETHUSDT"] == "chart_open"


async def test_a_full_frame_reaches_only_a_principal_that_is_the_owner_now() -> None:
    w = _world(_runtime())
    owner = _conn(w, owner=True)
    await w.cache.refresh_once()
    assert [t for t, _ in _payloads(owner)] == ["snap"]
    owner.authz.principal = replace(owner.authz.principal, roles=frozenset({"manager"}))
    await w.cache.refresh_once()
    assert _payloads(owner) == []


async def test_a_publish_that_raises_resnapshots_with_upstream_desync() -> None:
    hub = SequencingHub()
    calls: list[str] = []

    def broken(ch: str, body: Any, **kw: Any) -> int:
        calls.append(ch)
        raise RuntimeError("fan-out failed")

    topic = RecorderTopic(hub.subscriptions, broken, hub.resnapshot, SnapshotBody)
    w = _World(hub, topic, RecordingStatusCache(lambda: w.runtime, None), _runtime())
    topic.attach(w.cache)
    conn = _conn(w, owner=True)
    await w.cache.refresh_once()
    frames = conn.take()
    assert calls == ["recorder"] and [f["t"] for f in frames] == ["snap"]
    assert "upstream_desync" in json.dumps(frames)


def test_attach_once_generation_zero_and_no_continuity() -> None:
    w = _world()
    with pytest.raises(ValueError, match="attached"):
        w.topic.attach(w.cache)
    sub = _conn(w).authz.find("recorder", None)
    assert sub is not None and w.topic.generation(sub) == 0
    assert w.topic.continuity(sub, 1) is False


async def test_every_frame_validates_against_the_recorder_schema() -> None:
    w = _world(_runtime(symbols=3))
    await w.cache.refresh_once()
    snapshot = w.cache.snapshot()
    assert snapshot is not None
    for restricted in (False, True):
        for symbols in (frozenset(), frozenset({"ETHUSDT", "DOGEUSDT"})):
            body = frame(snapshot, symbols, restricted)
            assert body is not None
            check_schema(_REC, body, "recorder")


def test_the_view_is_recorded_at_admit_and_the_gauge_counts_subscriptions() -> None:
    def gauge() -> float:
        return float(cv_ws_recorder_subscriptions_in_use._value.get())

    start, w = gauge(), _world()
    owner, other = _conn(w, owner=True), _conn(w)
    subs = [c.authz.find("recorder", None) for c in (owner, other)]
    assert [s.role_restricted for s in subs if s is not None] == [False, True]
    assert gauge() == start + 2
    assert other.authz.unsubscribe("recorder", None) is not None
    assert gauge() == start + 1


@pytest.mark.perf
async def test_twenty_symbols_fit_8_kib_and_five_subscribers_take_under_2_pct_of_a_core() -> None:
    w = _world(_runtime(symbols=16))  # 20 symbols
    for symbols in ([], ["BTCUSDT"], ["ETHUSDT"], ["S01USDT", "S02USDT"]):
        _conn(w, owner=True, symbols=symbols or None, cls=_Unchecked)
    _conn(w, cls=_Unchecked)
    await w.cache.refresh_once()
    snapshot = w.cache.snapshot()
    assert snapshot is not None
    body = frame(snapshot, frozenset(), False)
    assert len(json.dumps(body, separators=(",", ":")).encode()) < 8 * 1024
    start = time.process_time()
    for _ in range(50):  # 50 seconds of 1 Hz computations, each sent to five subscribers
        await w.cache.refresh_once()
    assert (time.process_time() - start) / 50 < 0.02
