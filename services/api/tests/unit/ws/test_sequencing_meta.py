"""E12-T06 slice D1a (#399): an owning module's `meta` on `snap` frames, `meta` on `d` frames,
`publish(select=...)` and `flush_pending(match)`, in `ws/sequencing.py`."""

from __future__ import annotations

import json
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from candleviewer.bars.models import Bar, BarSpec
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
