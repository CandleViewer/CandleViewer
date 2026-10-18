"""E12-T06 slice D1b (#399): the bars delta publisher, `ws/bars_publish.py`."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final
from unittest.mock import Mock

import pytest
from structlog.testing import capture_logs

from candleviewer.bars.emit import BarEmission, BarSink
from candleviewer.bars.leases import CAP_GLOBAL
from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.ws import bars_publish
from candleviewer.ws.bars_publish import MAX_SERIES, BarsPublisher
from candleviewer.ws.bars_wire import bar_item
from candleviewer.ws.binary import FrameEncodeError, decode_b64
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.permissions import Subscription, handle_sub
from candleviewer.ws.sequencing import SequencingHub, SnapReason, SnapshotBody
from tests.unit.ws._seq_support import Clock, Conn, Source

SPEC = BarSpec(kind="time", interval_ms=300_000)
CH = "bars.BTCUSDT.time.5"
RS = "bb000000-0000-4000-8000-000000000001"
SWAP: Final = "generation_swap"
T0_US = 1_700_000_000_000_000
EMPTY = {"symbol": "BTCUSDT", "bar_type": "time", "param": "5", "bars": []}
EXACT = ("generation", "index", "t_ms", "trades", "confirm")
NUMERIC = ("o", "h", "l", "c", "v", "turnover", "delta")
#: Structured and binary subscribers, without and with `include_delta`.
_FLOWS = (False, True)
GROUPS = [{"encoding": e, "include_delta": f} for e in ("structured", "binary") for f in _FLOWS]


def _bar(index: int = 3, **kw: Any) -> Bar:
    t = T0_US + index * 300_000_000
    base = dict(
        spec_hash=SPEC.spec_hash, symbol="BTCUSDT", index=index, open_time=t,
        close_time=t + 299_999_999, open=Decimal("100.1"),
        high=Decimal("101"), low=Decimal("99.5"), close=Decimal("100.5"), volume=Decimal("10"),
        buy_volume=Decimal("6"), sell_volume=Decimal("4"), delta=Decimal("2"),
        min_delta=Decimal("-1"), max_delta=Decimal("3"), trade_count=7, turnover=Decimal("1001"),
        vwap=Decimal("100.3"), closed=False, partial=False, gap_before=False,
    )  # fmt: skip
    return Bar.model_validate(base).model_copy(update=kw)


def _up(kind: str = "update", *, amended: bool = False, **kw: Any) -> BarUpdate:
    bar = _bar(**{"closed": kind == "close", **kw})
    return BarUpdate.model_validate({"kind": kind, "bar": bar, "amended": amended})


def _em(*updates: BarUpdate, generation: int = 0, spec: BarSpec = SPEC) -> BarEmission:
    return BarEmission(spec, generation, updates)


def _world(
    *opts: Any, scales: tuple[int, int] | None = (1, 3), src: Source | None = None, **kw: Any
) -> tuple[SequencingHub, BarsPublisher, list[tuple[Conn, Subscription]]]:
    """One connection per `opts`, each subscribed to `CH` and past its snapshot."""
    src = src or Source()
    src.bodies["bars"] = SnapshotBody(EMPTY)
    hub, subs = SequencingHub(), []
    for o in opts:
        conn = Conn(src)
        hub.register(conn.authz, conn.emitter)
        subs.append((conn, conn.sub({"ch": CH, "opts": o})[1]))
        conn.take()
    return hub, BarsPublisher(hub, lambda _: scales, swap_reason=SWAP, **kw), subs


def _count(reason: str) -> float:
    return float(bar_emit_sink_errors_total.labels(reason=reason)._value.get())


def _size(frame: dict[str, Any]) -> int:
    return len(json.dumps(frame, separators=(",", ":")))


def _events(logs: Sequence[Mapping[str, Any]], event: str) -> list[Mapping[str, Any]]:
    return [e for e in logs if e["event"] == event]


# -- publisher ------------------------------------------------------------------------------


def test_the_publisher_is_the_ws_bar_sink() -> None:
    sink: BarSink = BarsPublisher(SequencingHub(), lambda _: None, swap_reason=SWAP)
    assert sink.name == "ws"


@pytest.mark.parametrize("reason", ["nope", "initial", "backpressure"])
def test_the_publisher_refuses_a_reason_that_is_not_a_swap(reason: Any) -> None:
    with pytest.raises(ValueError, match=f"'{reason}' is not a swap reason"):
        BarsPublisher(SequencingHub(), lambda _: None, swap_reason=reason)


async def test_forming_close_and_amended_close_carry_confirm_and_amended() -> None:
    _, pub, [(conn, _)] = _world({"encoding": "structured"})
    for update in (_up("open"), _up(), _up("close"), _up("close", amended=True)):
        await pub.emit(_em(update))
    out = conn.take()
    assert [f["s"] for f in out] == [2, 3, 4, 5]
    assert all(f["meta"] == {"include_delta": False} for f in out)
    assert all(f["p"].keys() == {"symbol", "bar_type", "param", "bars", "coalesced"} for f in out)
    shapes = [(f["p"]["bars"][0]["confirm"], f["p"]["bars"][0].get("amended")) for f in out]
    assert shapes == [(False, None), (False, None), (True, None), (True, True)]


async def test_each_include_delta_group_gets_its_own_variant_in_both_encodings() -> None:
    _, pub, subs = _world(*GROUPS)
    bar = _bar(delta=Decimal("-0.5"))
    await pub.emit(_em(BarUpdate(kind="update", bar=bar)))
    frames = [conn.take() for conn, _ in subs]
    assert all(len(f) == 1 and f[0]["s"] == 2 for f in frames)
    (plain,), (flow,), (plain_b,), (flow_b,) = frames
    assert [f[0]["meta"]["include_delta"] for f in frames] == [False, True, False, True]
    want = {f: bar_item(bar, generation=0, bar_kind="time", include_delta=f) for f in _FLOWS}
    assert (plain["p"]["bars"], flow["p"]["bars"]) == ([want[False]], [want[True]])
    assert (plain_b["e"], flow_b["e"]) == ("b64", "b64")
    for frame, f in ((plain_b, False), (flow_b, True)):  # the twins agree, as decimals (§16.4)
        (got,) = structured(decode_b64(frame["p"]))["bars"]
        item = {"delta": "0", **want[f]}  # without include_delta the record carries 0
        assert [got[k] for k in EXACT] == [item[k] for k in EXACT]
        assert [Decimal(got[k]) for k in NUMERIC] == [Decimal(item[k]) for k in NUMERIC]


async def test_each_group_builds_items_and_frames_once_and_an_unwatched_channel_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = {n: Mock(wraps=getattr(bars_publish, n)) for n in ("bar_item", "bars_frames")}
    for name, spy in spies.items():
        monkeypatch.setattr(bars_publish, name, spy)
    _, pub, _ = _world(*GROUPS, *GROUPS)
    await pub.emit(_em(_up()))
    await pub.emit(_em(_up(), spec=BarSpec(kind="tick", tick_count=100)))  # nobody subscribed
    assert [spy.call_count for spy in spies.values()] == [2, 2]  # one bar, two groups


async def test_binary_scales_cover_the_bars() -> None:
    _, pub, [(conn, _)] = _world({})
    await pub.emit(_em(_up(open=Decimal("100.15"))))
    (d,) = conn.take()
    assert (decode_b64(d["p"]).price_scale, decode_b64(d["p"]).qty_scale) == (2, 3)


async def test_unknown_scales_send_structured_counted_each_time_and_logged_once() -> None:
    _, pub, [(conn, _)] = _world({}, scales=None)
    before = _count("ws_no_scales")
    with capture_logs() as logs:
        for _ in range(3):
            await pub.emit(_em(_up()))
    assert [(d["e"], d["meta"]) for d in conn.take()] == [("j", {"include_delta": False})] * 3
    assert _count("ws_no_scales") == before + 3
    assert [e["log_level"] for e in _events(logs, "ws_bars_no_scales")] == ["warning"]


async def test_a_multi_frame_emission_sends_one_delta_per_frame_in_order() -> None:
    _, pub, [(binary, _), (plain, _)] = _world({}, {"encoding": "structured"})
    far = 50 * 86_400_000_000 // 300_000_000  # 50 days on: past the u32 offset span
    await pub.emit(_em(_up("close", index=3), _up("open", index=3 + far)))
    b, p = binary.take(), plain.take()
    assert [f["s"] for f in b] == [f["s"] for f in p] == [2, 3]
    decoded = [structured(decode_b64(f["p"]))["bars"] for f in b]
    assert [[r["index"] for r in bars] for bars in (*decoded, *(f["p"]["bars"] for f in p))] == [
        [3], [3 + far], [3], [3 + far]
    ]  # fmt: skip


async def test_a_large_emission_is_cut_to_the_frame_limit_on_shared_boundaries() -> None:
    flow_only = {"encoding": "structured", "include_delta": True}  # a structured-only group
    opts: list[dict[str, Any]] = [{}, {"encoding": "structured"}, flow_only]
    _, pub, [(binary, _), (plain, _), (flow, _)] = _world(*opts, max_frame_bytes=6000)
    await pub.emit(_em(*(_up("close", index=i) for i in range(60))))
    b, p, f = binary.take(), plain.take(), flow.take()
    assert len(b) == len(p) > 1 and len(f) > 1 and all(_size(d) <= 6000 for d in b + p + f)
    assert [len(decode_b64(f["p"]).records) for f in b] == [len(f["p"]["bars"]) for f in p]
    assert [x["index"] for f in p for x in f["p"]["bars"]] == list(range(60))
    assert all(_size(f) > 6000 - 300 for f in p[:-1])  # a run ends only when full


async def test_a_binary_only_group_is_cut_by_the_binary_budget_alone() -> None:
    _, pub, [(conn, _)] = _world({}, max_frame_bytes=2000)
    await pub.emit(_em(*(_up("close", index=i) for i in range(60))))
    out = conn.take()
    assert all(f["e"] == "b64" and _size(f) <= 2000 for f in out)
    assert all(_size(f) > 2000 - 200 for f in out[:-1])  # full binary runs, not structured ones
    assert sum(len(decode_b64(f["p"]).records) for f in out) == 60


async def test_a_binary_group_on_structured_frames_is_cut_to_the_limit_too() -> None:
    _, pub, [(conn, _)] = _world({}, scales=None, max_frame_bytes=2000)
    await pub.emit(_em(*(_up("close", index=i) for i in range(60))))
    out = conn.take()
    assert len(out) > 1 and all(f["e"] == "j" and _size(f) <= 2000 for f in out)
    assert [b["index"] for f in out for b in f["p"]["bars"]] == list(range(60))


async def test_an_amended_close_goes_structured_even_to_binary_subscribers() -> None:
    _, pub, [(conn, _)] = _world({})
    before = (_count("ws_no_scales"), _count("ws_binary_refused"))
    await pub.emit(_em(_up("close")))
    await pub.emit(_em(_up("close", amended=True)))  # kind 4 has no amended bit (A2)
    closed, amended = conn.take()
    assert (closed["e"], amended["e"], amended["p"]["bars"][0]["amended"]) == ("b64", "j", True)
    assert (_count("ws_no_scales"), _count("ws_binary_refused")) == before  # by design


async def test_an_unsent_delta_never_widens_the_scales_or_takes_an_s() -> None:
    _, pub, [(plain, ps), (flow, fs)] = _world({}, {"include_delta": True})
    await pub.emit(_em(_up(volume=Decimal("0"), delta=Decimal("1E-300"))))
    (d,) = plain.take()
    assert (d["e"], decode_b64(d["p"]).qty_scale, ps.seq) == ("b64", 3, 2)
    assert (flow.take(), fs.seq) == ([], 1)  # its item refuses the 300 places: dropped, no `s`


async def test_a_binary_refusal_sends_structured_counted_and_logged_once_per_episode() -> None:
    _, pub, [(conn, _)] = _world({})
    huge, before = _up(open=Decimal("1E+19")), _count("ws_binary_refused")  # overflows at 1
    with capture_logs() as logs:
        for update in (huge, huge, _up(), huge):  # the good one ends the episode
            await pub.emit(_em(update))
    out = conn.take()
    assert [(d["e"], d["s"]) for d in out] == [("j", 2), ("j", 3), ("b64", 4), ("j", 5)]
    assert out[0]["p"]["bars"][0]["o"] == "10000000000000000000"
    assert _count("ws_binary_refused") == before + 3
    warned = _events(logs, "ws_bars_binary_refused")
    assert len(warned) == 2 and warned[0]["ch"] == CH and "overflows" in warned[0]["reason"]


async def test_a_refused_group_is_dropped_counted_each_time_and_logged_once_per_episode() -> None:
    _, pub, subs = _world({}, {"encoding": "structured"})
    bad, before = _up(amended=True), _count("ws")  # an amended forming bar (§8.2)
    with capture_logs() as logs:
        for update in (bad, bad, _up(), bad):  # the good one ends the episode
            await pub.emit(_em(update))
    assert [s.seq for _, s in subs] == [2, 2]  # only the good emission was sent
    assert _count("ws") == before + 3
    errors = _events(logs, "ws_bars_item_refused")
    assert [e["log_level"] for e in errors] == ["error"] * 2 and "closed bar" in errors[0]["reason"]


async def test_a_refusal_in_one_include_delta_group_spares_the_other() -> None:
    opts = [{"encoding": "structured", "include_delta": f} for f in (True, False)]
    _, pub, [(flow, fs), (plain, _)] = _world(*opts)  # the refusing group is handled first
    before = _count("ws")
    await pub.emit(_em(_up(min_delta=Decimal("-1." + "1" * 40))))  # only the flow item sends it
    assert (len(plain.take()), flow.take(), fs.seq, _count("ws")) == (1, [], 1, before + 1)


async def test_a_generation_swap_resnapshots_the_live_channel_instead_of_a_delta() -> None:
    _, pub, [(conn, live)] = _world({"encoding": "structured"})
    _, replay = conn.sub({"ch": CH, "opts": {"encoding": "structured"}}, replay_session_id=RS)
    _, other = conn.sub({"ch": "bars.BTCUSDT.time.1", "opts": {"encoding": "structured"}})
    conn.take()
    for generation in (0, 7, 7):
        await pub.emit(_em(_up(), generation=generation))
    out = conn.take()
    assert [(f["t"], f["s"]) for f in out] == [("d", 2), ("snap", 3), ("d", 4)]
    assert out[1]["meta"] == {"reason": SWAP, "source": "live", "previous_seq": 2}
    assert out[2]["p"]["bars"][0]["generation"] == 7
    assert (live.seq, replay.seq, other.seq) == (4, 1, 1)  # only the live channel re-snapshots


async def test_a_lower_generation_is_a_swap_too() -> None:
    _, pub, [(conn, _)] = _world({"encoding": "structured"})
    for generation in (7, 3, 3):  # a store from an older process can hold the higher one
        await pub.emit(_em(_up(), generation=generation))
    assert [(f["t"], f["s"]) for f in conn.take()] == [("d", 2), ("snap", 3), ("d", 4)]


async def test_a_swap_storm_warns_once_a_minute_with_the_real_count_and_re_arms() -> None:
    clock = Clock()
    _, pub, _ = _world({"encoding": "structured"}, clock=clock)
    before = _count("ws_generation_swap")
    flaps = [(float(t), t % 2) for t in range(65)] + [(130.0, 1), (190.0, 0)]
    with capture_logs() as logs:  # a swap a second for 64 s, then two a minute apart
        for clock.now, generation in flaps:
            await pub.emit(_em(_up(), generation=generation))
    assert _count("ws_generation_swap") == before + 66
    assert len(_events(logs, "ws_bars_generation_swap")) == 3 + 2
    storms = [(e["log_level"], e["swaps"]) for e in _events(logs, "ws_bars_generation_swap_storm")]
    assert storms == [("warning", 4), ("warning", 60)]  # t=4, then t=64: swaps 5..64


async def test_a_swap_skips_paused_and_still_pending_subscriptions() -> None:
    _, pub, [(conn, _), (held, paused), (late, pending)] = _world({}, {}, {})
    paused.effective["paused"] = True
    await pub.emit(_em(_up(), generation=0))
    conn.take(), late.take()
    pending.snapshot_pending = True  # as if its snapshot were still being built
    await pub.emit(_em(_up(), generation=5))
    assert [f["t"] for f in conn.take()] == ["snap"]
    assert (held.take(), late.take(), paused.seq, pending.seq) == ([], [], 1, 2)
    assert pending.pending_reason == "initial"


async def test_a_swap_the_store_cannot_snapshot_yet_is_flushed_on_a_later_emission() -> None:
    src = Source()
    _, pub, [(conn, sub), (held, paused), (gone, _)] = _world({}, {}, {}, src=src)
    paused.effective["paused"], paused.snapshot_pending, paused.pending_reason = True, True, SWAP
    await pub.emit(_em(_up(), generation=0))
    gone.take()
    src.unavailable.add("BTCUSDT")  # the store has nothing to snapshot yet
    for generation in (5, 7, 7):  # two swaps, then a retry that still finds nothing
        await pub.emit(_em(_up(), generation=generation))
    assert sub.snapshot_pending
    src.unavailable.clear()
    gone.authz.unsubscribe(CH)  # unsubscribed while swap-pending: never flushed again
    for _ in range(2):  # the retry succeeds, then deltas resume
        await pub.emit(_em(_up(), generation=7))
    out = conn.take()
    assert [(f["t"], f["s"], f.get("meta", {}).get("reason")) for f in out] == [
        ("d", 2, None), ("snap", 3, SWAP), ("d", 4, None)
    ]  # fmt: skip
    assert (held.take(), gone.take(), paused.seq) == ([], [], 1)


async def test_a_d_the_hub_failed_to_emit_gets_its_snap_at_the_next_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3363, flag off: the first connection's `d` fails once (`FrameEncodeError`; every bars `d`
    carries its `include_delta` meta) and nothing reaches the emitter. The other connection gets
    that `d`; the failed one is pending `upstream_desync` and gets its `snap` at the next
    emission, with no `d` before it (`s` 3, after the 2 the failed `d` took), then `d`s again."""
    _, pub, [(bad, bs), (good, _)] = _world({}, {})
    push, failed = bad.emitter.push, list[dict[str, Any]]()

    def once(frame: dict[str, Any]) -> None:
        if not failed:
            failed.append(frame)
            raise FrameEncodeError("refused")
        push(frame)

    monkeypatch.setattr(bad.emitter, "push", once)
    await pub.emit(_em(_up()))
    assert (bad.take(), bs.snapshot_pending, bs.pending_reason) == ([], True, "upstream_desync")
    for _ in range(2):
        await pub.emit(_em(_up()))
    out = bad.take()
    assert [(f["t"], f["s"]) for f in out] == [("snap", 3), ("d", 4)]
    assert out[0]["meta"] == {"reason": "upstream_desync", "source": "live", "previous_seq": 2}
    assert [f["s"] for f in good.take()] == [2, 3, 4]
    assert failed[0]["meta"] == {"include_delta": False}  # the shape that failed: a bars `d`


async def test_an_emission_during_a_sub_never_sends_its_snap_before_sub_ok() -> None:
    src = Source()
    hub, pub, _ = _world(src=src)
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)

    class Leases:  # the builder replays its tape through the router while `sub` is in flight
        def check(self, spec: BarSpec, symbol: str, user: Any = None) -> None: ...

        async def register(
            self, spec: BarSpec, symbol: str, consumer: str, user: Any = None
        ) -> None:
            await pub.emit(_em(_up()))

        def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
            pass

    async def send(frame: dict[str, Any]) -> None:
        conn.push(frame)

    conn.authz.services.bars, builds = Leases(), src.builds
    await handle_sub(conn.authz, {"t": "sub", "id": "c-1", "p": {"topics": [CH]}}, send)
    assert ([f["t"] for f in conn.take()], src.builds) == (["sub_ok"], builds)
    conn.emitter.flush_pending(conn.authz.by_id.values())  # the gateway's flush after sub_ok
    assert [f["t"] for f in conn.take()] == ["snap"]


@pytest.mark.parametrize("reason", ["initial", "backpressure"])  # a `sub` in flight, E17's hold
async def test_a_swap_and_its_retry_keep_another_flows_hold_and_skip_a_replay(
    reason: SnapReason,
) -> None:
    src = Source()
    _, pub, [(held, hs), (conn, _)] = _world({}, {}, src=src)
    _, replay = conn.sub({"ch": CH, "opts": {}}, replay_session_id=RS)
    await pub.emit(_em(_up(), generation=0))
    held.take(), conn.take()
    hs.snapshot_pending, hs.pending_reason = True, reason
    replay.snapshot_pending, replay.pending_reason = True, SWAP
    src.unavailable.add("BTCUSDT")
    await pub.emit(_em(_up(), generation=5))  # the swap leaves the live subscription pending
    src.unavailable.clear()
    await pub.emit(_em(_up(), generation=5))  # its retry
    assert [("rs" in f, f["meta"]["reason"]) for f in conn.take()] == [(False, SWAP)]
    assert (held.take(), hs.pending_reason, replay.snapshot_pending) == ([], reason, True)


async def test_groups_count_only_the_subscriptions_a_frame_reaches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, pub, [(conn, sub)] = _world({}, scales=None)
    sub.effective["paused"] = True
    spy = Mock(wraps=bar_item)
    monkeypatch.setattr(bars_publish, "bar_item", spy)
    before = _count("ws_no_scales")
    await pub.emit(_em(_up()))
    assert (conn.take(), sub.seq, spy.call_count, _count("ws_no_scales")) == ([], 1, 0, before)


async def test_note_generation_seeds_a_missing_baseline_and_keeps_an_existing_one() -> None:
    _, pub, [(conn, _)] = _world({"encoding": "structured"})
    pub.note_generation("BTCUSDT", SPEC, 5)
    pub.note_generation("BTCUSDT", SPEC, 5)  # another snapshot in the same generation
    assert pub._seeds == {("BTCUSDT", SPEC.spec_hash): 5}  # kept at 5
    for generation in (7, 7):
        await pub.emit(_em(_up(), generation=generation))
    assert [f["t"] for f in conn.take()] == ["snap", "d"]  # 7 differs from the seeded 5: a swap


@pytest.mark.parametrize(("seen", "at"), [(True, 9), (True, 7), (False, 9), (False, 7)])
async def test_two_snapshot_generations_re_snapshot_every_subscriber(seen: bool, at: int) -> None:
    _, pub, subs = _world({}, {})
    if seen:  # a baseline from an emission at 7; else a seed from a snapshot at 7
        await pub.emit(_em(_up(), generation=7))
    for generation in (7, 9):  # one client's snapshot at 7, then another's at 9
        pub.note_generation("BTCUSDT", SPEC, generation)
    await pub.emit(_em(_up(), generation=at))  # either generation: a swap for both
    frames = [("d", None)] * seen + [("snap", SWAP)]  # each whole sequence: no `d` after the swap
    assert [[(f["t"], f["meta"].get("reason")) for f in c.take()] for c, _ in subs] == [frames] * 2


@pytest.mark.parametrize(
    ("noted", "logged"),
    [((7,), (7, False)), ((7, 9), (None, True)), ((-5,), (None, True))],
    ids=["one-generation", "two-generations", "negative"],
)
async def test_the_swap_log_names_the_previous_generation_or_the_mixed_mark(
    noted: tuple[int, ...], logged: tuple[int | None, bool]
) -> None:
    """Snapshots at `noted` before the first emission: one generation seeds the baseline; two, or
    a negative one (none is valid), mark it mixed, so the swap has no `previous` generation."""
    _, pub, _ = _world({})
    for generation in noted:
        pub.note_generation("BTCUSDT", SPEC, generation)
    with capture_logs() as logs:
        await pub.emit(_em(_up(), generation=11))
    swaps = _events(logs, "ws_bars_generation_swap")
    assert [(e["previous"], e["mixed"]) for e in swaps] == [logged]


async def test_note_generation_seeds_aside_and_never_ages_out_an_emitting_series() -> None:
    _, pub, _ = _world({"encoding": "structured"}, max_series=2)
    tick, minute = BarSpec(kind="tick", tick_count=100), BarSpec(kind="time", interval_ms=60_000)
    hour = BarSpec(kind="time", interval_ms=3_600_000)
    await pub.emit(_em(_up(), generation=3))
    for spec in (tick, minute, hour):  # three seeds, two kept: `tick`'s goes first
        pub.note_generation("BTCUSDT", spec, 1)
    with capture_logs() as logs:
        for spec in (SPEC, tick, minute, hour):
            await pub.emit(_em(_up(), generation=4, spec=spec))
    swapped = [e["ch"] for e in _events(logs, "ws_bars_generation_swap")]
    assert swapped == [CH, "bars.BTCUSDT.time.1", "bars.BTCUSDT.time.60"]


async def test_note_generation_takes_no_seed_for_an_emitting_series() -> None:
    _, pub, [(conn, _)] = _world({"encoding": "structured"}, max_series=2)
    await pub.emit(_em(_up(), generation=3))
    pub.note_generation("BTCUSDT", SPEC, 1)  # the series is live: no seed is taken
    for spec in (BarSpec(kind="tick", tick_count=100), BarSpec(kind="time", interval_ms=60_000)):
        await pub.emit(_em(_up(), spec=spec))  # ages SPEC's entry out
    before = _count("ws_generation_swap")
    await pub.emit(_em(_up(), generation=3))  # back at its own generation: a delta, no swap
    assert [f["t"] for f in conn.take()] == ["d", "d"] and _count("ws_generation_swap") == before


async def test_the_series_map_is_bounded_and_forgets_the_least_recent_first() -> None:
    assert MAX_SERIES == 2 * CAP_GLOBAL == 1024
    _, pub, [(conn, _)] = _world({"encoding": "structured"}, max_series=2)
    tick, minute = BarSpec(kind="tick", tick_count=100), BarSpec(kind="time", interval_ms=60_000)
    for spec in (SPEC, tick, SPEC, minute):  # `tick` emitted least recently: dropped
        await pub.emit(_em(_up(), spec=spec))
    assert pub.series_count() == 2
    conn.take()
    with capture_logs() as logs:
        await pub.emit(_em(_up(), generation=9))  # remembered: a swap
        await pub.emit(_em(_up(), generation=9, spec=tick))  # forgotten: no swap
    assert [e["ch"] for e in logs if e["event"] == "ws_bars_generation_swap"] == [CH]
    assert [f["t"] for f in conn.take()] == ["snap"]


async def test_pending_and_paused_subscriptions_get_nothing() -> None:
    _, pub, [(paused, ps), (pending, pend)] = _world({}, {})
    ps.effective["paused"], pend.snapshot_pending = True, True
    await pub.emit(_em(_up()))
    assert (paused.take(), pending.take(), ps.seq, pend.seq) == ([], [], 1, 1)


async def test_each_symbol_goes_to_its_own_channel_and_an_unnamed_spec_nowhere() -> None:
    _, pub, [(conn, _)] = _world({"encoding": "structured"})
    mark = BarSpec(kind="time", interval_ms=300_000, price_source="mark")  # no wire name
    await pub.emit(_em(_up(index=3), _up(index=4, symbol="ETHUSDT")))
    await pub.emit(_em(_up(), spec=mark))
    pub.note_generation("BTCUSDT", mark, 1)
    (d,) = conn.take()
    assert [b["index"] for b in d["p"]["bars"]] == [3] and pub.series_count() == 2
