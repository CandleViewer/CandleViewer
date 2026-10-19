"""E12-T06 slice D1a (#399): an owning module's `meta` on `snap` frames, `meta` on `d` frames,
`publish(select=...)` and `flush_pending(match)`, in `ws/sequencing.py`."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.ws import sequencing
from candleviewer.ws.bars_wire import bar_item, bars_frames
from candleviewer.ws.binary import decode_b64
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import (
    OWNER_META_MAX_BYTES,
    Rendered,
    SequencingHub,
    SnapshotBody,
    SnapshotCache,
    SnapshotSource,
)
from tests.unit.ws._seq_support import ACC_A, ACC_B, Conn, Source
from tests.unit.ws.test_pipeline_ladder import _structured
from tests.unit.ws.test_pipeline_outbound import _queued
from tests.unit.ws.test_pipeline_pacing import _BAR, _BARS, _SERIES, _routed

CH = "bars.BTCUSDT.time.5"
RS = "bb000000-0000-4000-8000-000000000001"
SPEC = BarSpec(kind="time", interval_ms=300_000)
OWNER = {"spec_hash": "ab" * 32, "build_version": 1, "include_delta": False}
EMPTY = {"symbol": "BTCUSDT", "bar_type": "time", "param": "5", "bars": []}


def _subscribed(
    *opts: dict[str, Any], cache: SnapshotCache | None = None
) -> tuple[SequencingHub, list[tuple[Conn, Subscription]]]:
    """One connection per `opts`, each subscribed to `CH` and past its snapshot."""
    src, hub, subs = Source(), SequencingHub(), []
    src.bodies["bars"] = SnapshotBody(EMPTY)
    for o in opts:
        conn = Conn(src, cache=cache)
        hub.register(conn.authz, conn.emitter)
        subs.append((conn, conn.sub({"ch": CH, "opts": o})[1]))
        conn.take()
    return hub, subs


def _bar(index: int) -> Bar:
    t = 1_700_000_000_000_000 + index * 300_000_000
    return Bar.model_validate(
        dict(
            spec_hash=SPEC.spec_hash, symbol="BTCUSDT", index=index, open_time=t,
            close_time=t + 299_999_999, open=Decimal("100.1"), high=Decimal("101"),
            low=Decimal("99.5"), close=Decimal("100.5"), volume=Decimal("10"),
            buy_volume=Decimal("6"), sell_volume=Decimal("4"), delta=Decimal("2"),
            min_delta=Decimal("-1"), max_delta=Decimal("3"), trade_count=7,
            turnover=Decimal("1001"), vwap=Decimal("100.3"), closed=True, partial=False,
            gap_before=False,
        )
    )  # fmt: skip


@pytest.mark.parametrize("key", ["reason", "previous_seq", "source"])
def test_snapshot_body_refuses_a_server_owned_meta_key(key: str) -> None:
    with pytest.raises(ValueError, match=f"snapshot meta keys \\['{key}'\\] are set by the server"):
        SnapshotBody({}, meta={key: 1, "spec_hash": "ab" * 32})


def test_snapshot_body_refuses_owner_meta_over_its_byte_bound() -> None:
    room = OWNER_META_MAX_BYTES - len('{"spec_hash":""}')
    assert len(SnapshotBody({}, meta={"spec_hash": "a" * room}).meta["spec_hash"]) == room
    with pytest.raises(ValueError, match="snapshot meta is over 1024 bytes"):
        SnapshotBody({}, meta={"spec_hash": "a" * (room + 1)})


def test_snapshot_body_meta_is_a_read_only_copy() -> None:
    owner = dict(OWNER)
    body = SnapshotBody({}, meta=owner)
    owner["reason"] = "late"  # the caller's dict, not the body's
    meta: Any = body.meta
    with pytest.raises(TypeError):
        meta["reason"] = "late"
    assert dict(body.meta) == OWNER


class _OwnerCache(SnapshotCache):
    """Hands `snapshot` a rendering whose owner mapping names server keys: only `SnapshotBody`
    refuses them, so this reaches the merge."""

    def get(self, sub: Subscription, source: SnapshotSource, max_part_bytes: int) -> Rendered:
        owner = {"reason": "owner", "source": "owner", "previous_seq": 99, "history_bars": 3}
        return Rendered(EMPTY, (), False, MappingProxyType(owner))


def test_snapshot_meta_merge_lets_the_server_keys_win() -> None:
    hub, [(conn, sub)] = _subscribed({"encoding": "structured"}, cache=_OwnerCache())
    assert hub.resnapshot(lambda s: s is sub, "reconfigure") == 1
    (snap,) = conn.take()
    assert snap["meta"] == {"reason": "reconfigure", "source": "live", "previous_seq": 1,
                            "history_bars": 3}  # fmt: skip


def test_an_initial_snapshot_takes_no_server_key_from_the_owner() -> None:
    src = Source()
    conn = Conn(src, cache=_OwnerCache())
    conn.sub({"ch": CH, "opts": {"encoding": "structured"}})
    (snap,) = conn.take()  # the server sets no previous_seq on a first snap; nor may the owner
    assert snap["meta"] == {"reason": "initial", "source": "live", "history_bars": 3}


@pytest.mark.parametrize("encoding", ["binary", "structured"])
@pytest.mark.parametrize("path", ["initial", "replay", "resync"])
def test_owner_meta_rides_every_chunk_and_each_chunk_stays_within_the_limit(
    encoding: str, path: str
) -> None:
    bars = [_bar(i) for i in range(200)]
    items = [bar_item(b, generation=0, bar_kind="time", include_delta=False) for b in bars]
    src = Source()
    src.bodies["bars"] = SnapshotBody(
        {**EMPTY, "bars": items},
        bars_frames(bars, generation=0, include_delta=False, price_scale=1, qty_scale=3),
        price_scale=1, qty_scale=3, meta=OWNER,
    )  # fmt: skip
    servers: dict[str, dict[str, Any]] = {
        "initial": {"reason": "initial", "source": "live"},
        "replay": {"reason": "initial", "source": "replay"},
        "resync": {"reason": "upstream_reconnect", "source": "live", "previous_seq": 10**9},
    }
    server = servers[path]
    for limit in range(12_000, 12_400, 13):  # some limit packs a chunk tightly
        hub, conn = SequencingHub(), Conn(src, max_frame_bytes=limit)
        hub.register(conn.authz, conn.emitter)
        entry = {"ch": CH, "opts": {"encoding": encoding}}
        _, sub = conn.sub(entry, replay_session_id=RS if path == "replay" else None)
        if path == "resync":  # a longer envelope: a reason, a ten-digit previous_seq
            conn.take()
            sub.seq = 10**9
            hub.resnapshot(lambda s: True, "upstream_reconnect")  # this hub holds only `sub`
        out = conn.take()
        assert len(out) > 1 and all(len(json.dumps(f, separators=(",", ":"))) <= limit for f in out)
        assert all(f["meta"] == {**server, **OWNER} for f in out)
        sent = [decode_b64(f["p"]).records if f["e"] == "b64" else f["p"]["bars"] for f in out]
        assert sum(map(len, sent)) == 200


def test_publish_select_sends_one_delta_to_each_selected_subscription_only() -> None:
    hub, [(a, sa), (b, sb)] = _subscribed({"encoding": "structured"}, {"include_delta": True})
    meta = {"include_delta": True}
    assert hub.publish(CH, EMPTY, meta=meta, select=lambda s: s is sb) == 1
    assert (a.take(), sa.seq, sb.seq) == ([], 1, 2)
    (d,) = b.take()
    assert (d["s"], d["meta"]) == (2, meta) and d["meta"] is not meta


def test_delta_meta_is_copied_per_subscription_and_never_names_a_server_key() -> None:
    hub, [(a, sa), (b, sb)] = _subscribed({"encoding": "structured"}, {"encoding": "structured"})
    assert hub.publish(CH, EMPTY, meta={"include_delta": False}) == 2
    (da,), (db,) = a.take(), b.take()
    assert da["meta"] == db["meta"] == {"include_delta": False} and da["meta"] is not db["meta"]
    assert hub.publish(CH, EMPTY, meta={}) == 2 and all("meta" not in f for f in a.take())
    with pytest.raises(ValueError, match="server-owned"):
        hub.publish(CH, EMPTY, meta={"reason": "spoof"})
    assert (b.take()[-1]["s"], sa.seq, sb.seq) == (3, 3, 3)  # the refusal took no `s`


def _spec(size: int) -> dict[str, str]:
    """A `meta` of exactly `size` bytes of JSON, by the bound's measure (`_dumps`)."""
    return {"spec_hash": "a" * (size - len('{"spec_hash":""}'))}


def _circular() -> dict[str, Any]:
    meta: dict[str, Any] = {}
    meta["self"] = meta
    return meta


def _too_deep() -> dict[str, Any]:
    """Nested far past the interpreter's limit (about 10 000 levels in 3.12), built in a loop."""
    inner: Any = []
    for _ in range(100_000):
        inner = [inner]
    return {"x": inner}


class _Unreadable(Mapping[str, Any]):
    """A mapping that breaks the protocol a `dict` keeps: it cannot give its keys (`where` is
    "keys"), or lists a key and raises `KeyError` for it ("item")."""

    def __init__(self, where: str) -> None:
        self.where = where

    def __iter__(self) -> Iterator[str]:
        if self.where == "keys":
            raise RuntimeError("no keys")
        return iter(("k",))

    def __getitem__(self, key: str) -> Any:
        raise KeyError(key)

    def __len__(self) -> int:
        return 1


class _Collides(str):
    """A key that hashes as a server-owned key does and raises when compared with it: the check
    itself can fail on what the copy holds."""

    def __hash__(self) -> int:
        return hash("reason")

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("no comparing")


_REFUSED_ROWS: dict[str, Any] = {
    "server-key": {"reason": "spoof"},
    "over-bound": _spec(OWNER_META_MAX_BYTES + 1),
    "non-ascii": {"spec_hash": "é" * 169},  # 169 characters, but 6 bytes each as JSON: 1030 bytes
    "not-json": {"x": object()},
    "circular": _circular(),
    "deep": _too_deep(),
    "nan": {"x": float("nan")},
    "inf": {"x": float("inf")},
    "iter-raises": _Unreadable("keys"),
    "getitem-raises": _Unreadable("item"),
    "key-compare-raises": {_Collides("k"): 1},
    "bytes-key": {b"k": 1},  # JSON keys are text; `skipkeys` would drop this one
}
_REFUSED = pytest.mark.parametrize("meta", _REFUSED_ROWS.values(), ids=list(_REFUSED_ROWS))


@pytest.mark.parametrize("form", [dict, MappingProxyType])  # `SnapshotBody.meta` is the latter
def test_a_d_meta_has_a_snapshots_owner_meta_bound(
    form: Callable[[dict[str, str]], Mapping[str, str]],
) -> None:
    """Exactly `OWNER_META_MAX_BYTES` of JSON is sent, as `SnapshotBody` builds it; one byte more
    is refused before any `s` is taken, as it is there. A read-only `meta` is measured as a dict
    and goes out as one."""
    hub, [(conn, sub)] = _subscribed({"encoding": "structured"})
    sent: list[dict[str, Any]] = []
    conn.emitter.push = sent.append  # the envelope schema's keys are not under test
    at, over = _spec(OWNER_META_MAX_BYTES), _spec(OWNER_META_MAX_BYTES + 1)
    assert SnapshotBody({}, meta=at).meta == at and hub.publish(CH, EMPTY, meta=form(at)) == 1
    with pytest.raises(ValueError, match="snapshot meta is over 1024 bytes"):
        SnapshotBody({}, meta=over)
    with pytest.raises(ValueError, match="delta meta is over 1024 bytes"):
        conn.emitter.delta(sub, EMPTY, meta=form(over))
    assert ([f["meta"] for f in sent], sub.seq) == ([at], 2)
    assert type(sent[0]["meta"]) is dict


def _hold_back(sub: Subscription, state: str) -> None:
    """Put `sub` in a state in which the emitter holds a `d` back (or leave it live)."""
    if state == "pending":
        sub.snapshot_pending = True
    elif state == "paused":
        sub.effective["paused"] = True
    elif state == "ended":
        sub.ended = True


@_REFUSED
@pytest.mark.parametrize("state", ["live", "pending", "paused", "ended"])
def test_flag_off_a_refused_d_meta_is_the_publishers_error(
    meta: Mapping[str, Any], state: str
) -> None:
    """It reaches the publisher, as a server-owned key does, whatever the subscription's state: not
    a failed delivery the hub contains (that leaves it pending a `snap`). No `s` is taken."""
    hub, [(conn, sub)] = _subscribed({"encoding": "structured"})
    _hold_back(sub, state)
    with pytest.raises(ValueError, match="delta meta"):
        hub.publish(CH, EMPTY, meta=meta)
    assert (conn.take(), sub.seq, sub.snapshot_pending) == ([], 1, state == "pending")


def test_flag_off_a_waking_publish_raises_a_refused_d_meta_too() -> None:
    """`wake` follows a contained failure with the `snap`; a refused `meta` is not contained, so
    nothing is sent and the subscription is not held for one."""
    hub, [(conn, sub)] = _subscribed({"encoding": "structured"})
    with pytest.raises(ValueError, match="delta meta is over 1024 bytes"):
        hub.publish(CH, EMPTY, meta=_spec(OWNER_META_MAX_BYTES + 1), wake=True)
    assert (conn.take(), sub.seq, sub.snapshot_pending) == ([], 1, False)


def test_a_refused_d_meta_is_refused_when_a_binary_part_rides_too() -> None:
    """A binary `d` carries its `meta` on the envelope beside the part: the same check."""
    hub, [(conn, sub)] = _subscribed({"encoding": "binary"})
    part = bars_frames([_bar(1)], generation=0, include_delta=False, price_scale=1, qty_scale=3)[0]
    with pytest.raises(ValueError, match="delta meta is over 1024 bytes"):
        hub.publish(CH, EMPTY, part=part, meta=_spec(OWNER_META_MAX_BYTES + 1))
    assert (conn.take(), sub.seq) == ([], 1)
    assert hub.publish(CH, EMPTY, part=part, meta={"include_delta": False}) == 1
    assert [(f["e"], f["s"]) for f in conn.take()] == [("b64", 2)]  # the part did ride


class _Drifting(Mapping[str, Any]):
    """A mapping whose content changes each time it is read (iterated): `states[0]` the first
    time, `states[1]` the next, the last for good. `reads` counts them. A `dict` holds still."""

    def __init__(self, *states: Mapping[str, Any]) -> None:
        self.states, self.reads = states, 0

    def _now(self) -> Mapping[str, Any]:
        return self.states[min(max(self.reads, 1), len(self.states)) - 1]

    def __iter__(self) -> Iterator[str]:
        self.reads += 1
        return iter(self._now())

    def __getitem__(self, key: str) -> Any:
        return self._now()[key]

    def __len__(self) -> int:
        return len(self._now())


@pytest.mark.parametrize(
    ("states", "sent"),
    [
        ([{"a": 1}, _spec(OWNER_META_MAX_BYTES + 1)], [{"a": 1}]),
        ([_spec(OWNER_META_MAX_BYTES + 1), {"a": 1}], None),
        ([{"reason": "spoof"}, {"a": 1}], None),
    ],
    ids=["grows-after", "shrinks-after", "names-a-server-key-once"],
)
def test_a_d_meta_is_read_once_and_goes_out_as_it_was_checked_or_is_refused(
    states: list[dict[str, Any]], sent: list[dict[str, Any]] | None
) -> None:
    """The copy that is checked is the copy that is sent, and the caller's `meta` is read once.
    One that drifts (a `dict` never does) is neither passed on a state and sent as another, nor
    refused on a state it no longer has: `sent` is the first state, or the refusal of it."""
    _, [(conn, sub)] = _subscribed({"encoding": "structured"})
    out: list[dict[str, Any]] = []
    conn.emitter.push = out.append
    lazy = _Drifting(*states)
    if sent is None:
        with pytest.raises(ValueError, match="delta meta"):
            conn.emitter.delta(sub, EMPTY, meta=lazy)
    else:
        assert conn.emitter.delta(sub, EMPTY, meta=lazy)
    assert ([f["meta"] for f in out], sub.seq, lazy.reads) == (sent or [], 2 if sent else 1, 1)


class _Truth(Mapping[str, Any]):
    """Over the bound, and its truth value is no guide: false the first time it is asked and true
    after (`how` is "lies"), or an error ("raises"). `asked` counts the times. A `dict` is false
    only when empty."""

    def __init__(self, how: str) -> None:
        self.how, self.asked = how, 0
        self.content = _spec(OWNER_META_MAX_BYTES + 1)

    def __bool__(self) -> bool:
        self.asked += 1
        if self.how == "raises":
            raise RuntimeError("no truth value")
        return self.asked > 1

    def __iter__(self) -> Iterator[str]:
        return iter(self.content)

    def __getitem__(self, key: str) -> Any:
        return self.content[key]

    def __len__(self) -> int:
        return len(self.content)


@pytest.mark.parametrize("how", ["lies", "raises"])
def test_flag_off_a_d_meta_is_checked_whatever_its_truth_value_says(how: str) -> None:
    """Neither the emitter nor the hub asks the caller's mapping whether it is empty: it is read
    once, and refused for what it holds, as the publisher's `ValueError`."""
    hub, [(conn, sub)] = _subscribed({"encoding": "structured"})
    meta = _Truth(how)
    with pytest.raises(ValueError, match="delta meta is over 1024 bytes"):
        hub.publish(CH, EMPTY, meta=meta)
    assert (conn.take(), sub.seq, meta.asked) == ([], 1, 0)


@_REFUSED
def test_flag_on_a_refused_d_meta_is_contained_and_re_snapshotted(meta: Mapping[str, Any]) -> None:
    """The pipeline contains it: the update is dropped, no `s` is taken, and a `backpressure`
    `snap` follows at the writer's turn, the connection open."""
    hub = SequencingHub()
    pipe, asked, conn = _routed(hub)
    sub = _structured(conn, _BARS)
    _queued(pipe)
    hub.publish(_BARS, {**_SERIES, "bars": [{**_BAR, "confirm": False}]}, meta=meta)
    assert (sub.seq, sub.pending_reason, _queued(pipe), asked) == (1, "backpressure", [], [])
    pipe.service(0.0)
    assert [(f["t"], f["s"]) for f in _queued(pipe)] == [("snap", 2)]


@pytest.mark.parametrize("form", [dict, MappingProxyType])
def test_flag_on_a_d_meta_at_the_bound_is_sent(
    form: Callable[[dict[str, str]], Mapping[str, str]],
) -> None:
    hub = SequencingHub()
    pipe, _, conn = _routed(hub)
    _structured(conn, _BARS)
    _queued(pipe)
    at = _spec(OWNER_META_MAX_BYTES)
    hub.publish(_BARS, {**_SERIES, "bars": [{**_BAR, "confirm": False}]}, meta=form(at))
    assert [(f["t"], f["s"], f["meta"]) for f in _queued(pipe)] == [("d", 2, at)]


def test_a_d_without_meta_is_unchanged_and_never_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The read stays behind `meta is not None`: a `d` without one never reaches it."""
    hub, [(conn, _)] = _subscribed({"encoding": "structured"})
    calls: list[Mapping[str, Any]] = []

    def record(meta: Mapping[str, Any]) -> tuple[dict[str, Any], None]:
        calls.append(meta)
        return {}, None

    monkeypatch.setattr(sequencing, "_read_delta_meta", record)
    assert hub.publish(CH, EMPTY) == 1
    (d,) = conn.take()
    assert ("meta" in d, d["s"], calls) == (False, 2, [])


def test_publish_asks_select_only_after_the_scope_check() -> None:
    hub, conn = SequencingHub(), Conn(Source(), ACC_A)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.authz.admit({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert sub is not None
    sub.snapshot_pending = False
    asked: list[Subscription] = []

    def select(s: Subscription) -> bool:
        asked.append(s)
        return True

    assert hub.publish("orders", {"orders": []}, account=ACC_B, select=select) == 0
    assert asked == []  # never shown a subscription outside the scope, so it can only narrow
    assert hub.publish("orders", {"orders": []}, account=ACC_A, select=select) == 1
    assert asked == [sub]


def test_subscriptions_lists_the_live_or_one_replay_sessions_subscription() -> None:
    hub, [(conn, live)] = _subscribed({"encoding": "structured"})
    _, replay = conn.sub({"ch": CH, "opts": {"encoding": "structured"}}, replay_session_id=RS)
    assert (hub.subscriptions(CH), hub.subscriptions(CH, RS)) == ([live], [replay])
    assert hub.subscriptions(CH, "bb000000-0000-4000-8000-000000000002") == []


def test_flush_pending_retries_only_the_subscriptions_match_accepts() -> None:
    hub, [(a, sa), (b, sb)] = _subscribed({"encoding": "structured"}, {"encoding": "structured"})
    for sub in (sa, sb):
        sub.snapshot_pending, sub.pending_reason = True, "reconfigure"
    assert hub.flush_pending(lambda s: s is sb) == 1
    assert (a.take(), [f["t"] for f in b.take()], sa.snapshot_pending) == ([], ["snap"], True)
    assert hub.flush_pending() == 1  # no `match`: every pending subscription
