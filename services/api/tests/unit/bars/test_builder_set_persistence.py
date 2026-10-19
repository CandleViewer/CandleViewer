"""`BarBuilderSet` persistence + restart (E12-T03): 60 s blobs, atomic write, corrupt-safe read,
restore + replay-from-watermark, BI-5 at the set level."""

from __future__ import annotations

import os
import random
from pathlib import Path

import orjson
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.bars import state_store
from candleviewer.bars.builder_set import STATE_COLD_STARTED, BarBuilderSet
from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import Bar
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import (
    H1,
    M1,
    T3,
    TOPIC,
    V5,
    Clock,
    FakeTape,
    RecordingSink,
    make_set,
    settle,
    write_failures,
)
from ._trades import SYM, trade, us

T0 = us("10:00:00")
SPECS = (M1, H1, T3, V5)


def _tape(n: int, seed: int = 7) -> list[TradeEvent]:
    rnd = random.Random(seed)  # noqa: S311 - seeded test data, not crypto
    out, ts = [], T0
    for i in range(n):
        ts += rnd.choice((0, 0, 1, 1_000_000, 7_000_000, 45_000_000))  # equal-ts runs included
        side = "buy" if rnd.random() < 0.5 else "sell"
        out.append(
            trade(
                ts, px=str(100 + rnd.randint(-5, 5)), qty=str(rnd.randint(1, 4)), side=side, seq=i
            )
        )
    return out


async def _run(
    root: Path, trades: list[TradeEvent], tape: FakeTape | None = None, clock: Clock | None = None
) -> tuple[RecordingSink, BarBuilderSet]:
    bus, sink = Bus(), RecordingSink()
    s = make_set(root, bus=bus, sinks=[sink], tape=tape, clock=clock)
    for i, spec in enumerate(SPECS):
        await s.register(spec, SYM, f"c{i}")
    for t in trades:
        await bus.publish(TOPIC, t)
    await settle(bus, s)
    return sink, s


def _final(sink: RecordingSink) -> dict[tuple[str, int], Bar]:
    """Last emitted full `Bar` (OHLCV, delta, trade_count, flags) per (spec, index)."""
    return {(h, b.index): b for h, _, b in sink.bars}


def _closes(*sinks: RecordingSink) -> dict[str, list[Bar]]:
    """Close emissions per spec, in emission order. Per spec, because replay on restart
    runs spec by spec, so the cross-spec interleaving legitimately differs."""
    out: dict[str, list[Bar]] = {}
    for sink in sinks:
        for h, k, b in sink.bars:
            if k == "close":
                out.setdefault(h, []).append(b)
    return out


async def _restart_matches(tmp_path: Path, trades: list[TradeEvent], cut: int, lag: int) -> None:
    """Snapshot after `cut - lag` trades, crash after `cut`, restart, replay; compare to a
    straight run. `lag` trades past the blob are on the tape and redelivered live too."""
    ref, s_ref = await _run(tmp_path / "ref", trades)
    await s_ref.stop()
    root = tmp_path / "live"
    first, s1 = await _run(root, trades[: cut - lag])
    for lane in s1._lanes.values():
        for e in lane.entries:
            await s1._store.save(s1._stored(lane, e))
    s1._lanes.clear()  # crash: no final blobs, no drain
    tape = FakeTape(trades[:cut])
    second, s2 = await _run(root, trades[cut - lag :], tape=tape)
    await s2.stop()
    merged = _final(first)
    merged.update(_final(second))
    assert merged == _final(ref)  # every bar identical in full, not just its close price
    # the emitted close sequence matches too: nothing re-applied, nothing missing, no extra
    # emission (a double-applied trade shows up as a changed bar or an extra close)
    assert _closes(first, second) == _closes(ref)


async def test_restart_resumes_mid_bar_bi5(tmp_path: Path) -> None:
    await _restart_matches(tmp_path, _tape(300), cut=180, lag=25)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(seed=st.integers(0, 10_000), cut=st.integers(1, 900), lag=st.integers(0, 60))
async def test_restart_any_cut_point_bi5(
    tmp_path_factory: pytest.TempPathFactory, seed: int, cut: int, lag: int
) -> None:
    """PR-lane BI-5 sample (25 examples); the 100-example sweep runs nightly (#2177)."""
    trades = _tape(1_000, seed)
    await _restart_matches(tmp_path_factory.mktemp("bi5"), trades, cut + 30, min(lag, cut))


@pytest.mark.harness
@settings(
    max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(seed=st.integers(0, 10_000), cut=st.integers(1, 900), lag=st.integers(0, 60))
async def test_restart_any_cut_point_bi5_full_sweep(
    tmp_path_factory: pytest.TempPathFactory, seed: int, cut: int, lag: int
) -> None:
    """Nightly `harness` lane: the full 100-example BI-5 sweep (~2 min under coverage, #2177)."""
    trades = _tape(1_000, seed)
    await _restart_matches(tmp_path_factory.mktemp("bi5"), trades, cut + 30, min(lag, cut))


async def test_restart_replays_only_after_watermark(tmp_path: Path) -> None:
    trades = _tape(100)
    _, s1 = await _run(tmp_path, trades[:60])
    await s1.stop()  # graceful: final blobs written
    tape = FakeTape(trades[:80])
    _, s2 = await _run(tmp_path, [], tape=tape)
    wm = trades[59].ts_event
    assert tape.reads == len(SPECS) * sum(t.ts_event >= wm for t in trades[:80])
    await s2.stop()


async def test_persist_every_60s_with_fake_clock(tmp_path: Path) -> None:
    clock, bus = Clock(T0), Bus()
    s = make_set(tmp_path, bus=bus, clock=clock)
    await s.register(T3, SYM, "a")
    path = tmp_path / SYM / f"{T3.spec_hash}.state.json"
    assert orjson.loads(path.read_bytes())["wm"] is None  # the cold-start blob (#2662)
    await bus.publish(TOPIC, trade(T0, seq=1))
    await settle(bus, s)
    clock.t = T0 + 59_999_999
    await s.tick()
    assert orjson.loads(path.read_bytes())["wm"] is None  # not rewritten before 60 s
    clock.t = T0 + 60_000_000
    await s.tick()
    assert orjson.loads(path.read_bytes())["wm"] == [T0, ["1"]]
    await s.stop()


async def test_crash_between_write_and_rename_keeps_old_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StateStore(tmp_path)
    _, s = await _run(tmp_path, _tape(10))
    lane = s._lanes[SYM]
    good = s._stored(lane, lane.entries[2])
    await store.save(good)
    before = store.path(SYM, T3.spec_hash).read_bytes()

    def crash(*_: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr("candleviewer.bars.state_store.os.replace", crash)
    await s._save(good, "periodic")  # logged + swallowed, never raises
    assert store.path(SYM, T3.spec_hash).read_bytes() == before
    loaded, reason = await store.load(SYM, T3.spec_hash)
    assert reason == "ok" and loaded is not None and loaded.state == good.state
    monkeypatch.undo()
    await s.stop()


def _corrupt_variants(good: bytes) -> dict[str, bytes]:
    doc = orjson.loads(good)
    return {
        "truncated": good[: len(good) // 2],
        "garbage": b"\x00\xff not json",
        "version": orjson.dumps({**doc, "v": 99}),
        "wrong_series": orjson.dumps({**doc, "spec_hash": "0" * 64}),
        "bad_inner": orjson.dumps({**doc, "blob": '{"cur": 5}'}),
        "bad_state_version": orjson.dumps({**doc, "state_version": 7}),
        "too_large": good + b" " * state_store.MAX_BLOB_BYTES,
    }


@pytest.mark.parametrize("variant", list(_corrupt_variants(b'{"v":1}')))
async def test_corrupt_blob_discarded_cold_start_never_raises(tmp_path: Path, variant: str) -> None:
    _, s1 = await _run(tmp_path, _tape(40))
    await s1.stop()
    path = tmp_path / SYM / f"{T3.spec_hash}.state.json"
    path.write_bytes(_corrupt_variants(path.read_bytes())[variant])
    sink, s2 = await _run(tmp_path, [trade(us("11:00:00"), seq=999)])
    assert STATE_COLD_STARTED in s2.health_reasons()
    assert (await StateStore(tmp_path).load(SYM, T3.spec_hash))[1] == "ok"  # replaced, not kept
    t3 = [u for u in sink.seen if u[0] == T3.spec_hash]
    assert t3[0][2:4] == ("open", 0)  # cold start: fresh series
    await s2.stop()


async def test_watermark_past_tape_head_is_refused(tmp_path: Path) -> None:
    trades = _tape(40)
    _, s1 = await _run(tmp_path, trades)
    await s1.stop()
    _, s2 = await _run(tmp_path, [], tape=FakeTape(trades[:10]))
    assert STATE_COLD_STARTED in s2.health_reasons()
    await s2.stop()


async def test_store_rejects_unsafe_path_components(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    for sym, h in (("../etc", "a" * 64), (SYM, "../" + "a" * 61), ("btcusdt", "a" * 64)):
        with pytest.raises(BarsError):
            store.path(sym, h)


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("part", ["symbol", "spec_hash"])
def test_store_rejects_a_path_component_ending_in_a_newline(
    tmp_path: Path, part: str, tail: str
) -> None:
    """#3555: `$` also matches before a final newline, so `match` built a path with the newline
    in a directory or file name. Each of the two components is read."""
    legal = {"symbol": SYM, "spec_hash": "a" * 64}
    store = StateStore(tmp_path)
    assert store.path(**legal) == tmp_path / SYM / f"{'a' * 64}.state.json"
    with pytest.raises(BarsError):
        store.path(**{**legal, part: legal[part] + tail})


async def test_store_missing_unreadable_and_delete(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    assert await store.load(SYM, "a" * 64) == (None, "missing")
    (tmp_path / SYM / ("b" * 64 + ".state.json")).mkdir(parents=True)
    assert (await store.load(SYM, "b" * 64))[1] == "unreadable"
    await store.delete(SYM, "c" * 64)  # missing is fine


async def test_store_roundtrip_without_watermark(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    _, s = await _run(tmp_path / "x", [])
    lane = s._lanes[SYM]
    st0 = s._stored(lane, lane.entries[0])
    assert st0.watermark is None
    await store.save(st0)
    assert await store.load(SYM, M1.spec_hash) == (st0, "ok")
    assert Watermark(5, frozenset({"a"})).covers(5, "a") and not Watermark(5, frozenset()).covers(
        6, "b"
    )
    await s.stop()


async def test_disk_full_on_save_is_logged_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(T0)
    s = make_set(tmp_path, clock=clock)
    await s.register(T3, SYM, "a")

    async def full(_: StoredState) -> None:
        raise OSError(28, os.strerror(28))

    monkeypatch.setattr(s._store, "save", full)
    periodic, final = write_failures("periodic"), write_failures("final")
    clock.t += 60_000_000
    await s.tick()
    assert write_failures("periodic") == periodic + 1  # counted, by phase
    await s.stop()
    assert write_failures("final") == final + 1
