"""E17-S03 DoD evidence (QA 2026-10-12): §16.3 re-snapshot budgets, `snap`/`d` contract tests
GENERATED from `FAMILIES`, the resync window, `snapshot_forced`, a 10 000-delta exact replay and the
stale flag under a stalled upstream. Every emitted frame is schema-validated by `Conn.push`."""

from __future__ import annotations

import json
import random
import time
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.sequencing import (
    SequencingHub,
    SnapshotBody,
    SnapshotCache,
    book_window,
    cv_ws_stale_topics_in_use,
    window_delta,
)
from candleviewer.ws.topics import FAMILIES
from tests.unit.ws._seq_support import ACC_A, USER, Book, Clock, Conn, Source, validate
from tests.unit.ws.test_sequencing import RefClient, _book_source, _resync

KIB = 1024
ACC = str(ACC_A)
_SYM = "BTCUSDT"

# Minimal schema-valid snapshot + delta body per family (ws-schema.json §14-§15).
_UUID = "00000000-0000-4000-8000-0000000000aa"
_SAMPLES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "book": (
        {"symbol": _SYM, "bids": [["100.0", "1.0"]], "asks": [["101.0", "2.0"]]},
        {"symbol": _SYM, "bids": [["100.0", "0"]], "asks": []},
    ),
    "trades": (
        {"symbol": _SYM, "trades": []},
        {
            "symbol": _SYM,
            "trades": [{"ts_ms": 1, "price": "100.0", "size": "1", "side": "buy"}],
        },
    ),
    "bars": (
        {"symbol": _SYM, "bar_type": "time", "param": "1", "bars": []},
        {
            "symbol": _SYM,
            "bar_type": "time",
            "param": "1",
            "bars": [
                {
                    "generation": 0,
                    "index": 1,
                    "t_ms": 1,
                    "o": "1",
                    "h": "2",
                    "l": "1",
                    "c": "2",
                    "v": "3",
                    "confirm": False,
                }
            ],
        },
    ),
    "footprint": (
        {"symbol": _SYM, "bar_type": "time", "param": "1", "bars": []},
        {
            "symbol": _SYM,
            "bar_type": "time",
            "param": "1",
            "bars": [{"generation": 0, "index": 1, "t_ms": 1, "cells": []}],
        },
    ),
    "heatmap": (
        {"symbol": _SYM, "time_bucket_ms": 500, "columns": []},
        {
            "symbol": _SYM,
            "time_bucket_ms": 500,
            "columns": [{"t_ms": 1, "price_min": "1", "price_step": "1", "bids": [], "asks": []}],
        },
    ),
    "profile": (
        {"symbol": _SYM, "kind": "volume", "profiles": []},
        {
            "symbol": _SYM,
            "kind": "volume",
            "profiles": [{"period_start_ms": 1, "rows": []}],
        },
    ),
    "metrics": (
        {"symbol": _SYM, "series": []},
        {"symbol": _SYM, "series": [{"metric": "cvd", "t_ms": 1, "v": "1"}]},
    ),
    "ticker": (
        {"tickers": []},
        {"tickers": [{"symbol": _SYM, "last_price": "100.0", "ts_ms": 1}]},
    ),
    "liquidations": (
        {"liquidations": []},
        {"liquidations": [{"symbol": _SYM, "ts_ms": 1, "side": "buy", "price": "1", "size": "1"}]},
    ),
    "orders": (
        {"orders": []},
        {
            "orders": [
                {
                    "id": _UUID,
                    "exchange_account_id": ACC,
                    "symbol": _SYM,
                    "state": "new",
                    "updated_at_ms": 1,
                }
            ]
        },
    ),
    "positions": (
        {"positions": []},
        {
            "positions": [
                {
                    "id": _UUID,
                    "exchange_account_id": ACC,
                    "symbol": _SYM,
                    "side": "flat",
                    "size": "0",
                    "updated_at_ms": 1,
                }
            ]
        },
    ),
    "executions": (
        {"executions": []},
        {
            "executions": [
                {
                    "id": _UUID,
                    "exec_id": "e1",
                    "order_id": _UUID,
                    "exchange_account_id": ACC,
                    "symbol": _SYM,
                    "side": "buy",
                    "exec_qty": "1",
                    "exec_price": "1",
                    "ts_ms": 1,
                }
            ]
        },
    ),
    "wallet": (
        {"balances": []},
        {
            "balances": [
                {"exchange_account_id": ACC, "coin": "USDT", "equity": "1", "updated_at_ms": 1}
            ]
        },
    ),
    "trade_groups": (
        {"trade_groups": []},
        {"trade_groups": [{"id": _UUID, "status": "open", "updated_at_ms": 1}]},
    ),
    "rules": ({"rules": []}, {"rules": []}),
    "alerts": (
        {"deliveries": []},
        {
            "deliveries": [
                {
                    "id": 1,
                    "alert_id": _UUID,
                    "channel": "in_app",
                    "status": "queued",
                    "message": "m",
                    "fired_at_ms": 1,
                }
            ]
        },
    ),
    "recorder": ({"overall": "healthy", "symbols": []}, {"overall": "healthy", "symbols": []}),
    "system": ({"kind": "health"}, {"kind": "notice"}),
}
_IMPLICIT = {"system"}
_SCOPED = {f.family for f in FAMILIES.values() if f.account_scoped}
_SEG = {"symbol": _SYM, "depth": "50", "bar_type": "time", "param": "1", "profile_kind": "volume"}


def _entry(fam: str, shape: tuple[str, ...]) -> dict[str, Any]:
    ch = ".".join((fam, *(_SEG[s] for s in shape)))
    opts = {"exchange_account_ids": [ACC]} if fam in _SCOPED else {}
    return {"ch": ch, "opts": {**opts, "encoding": "structured"}}


_CASES = [
    pytest.param(f.family, s, id=".".join((f.family, *s)))
    for f in FAMILIES.values()
    for s in f.shapes
    if f.family not in _IMPLICIT  # `system` is auto-subscribed at auth_ok, never a Subscription
]


def test_sample_table_covers_every_registered_family() -> None:
    assert set(_SAMPLES) == set(FAMILIES)
    assert {c.values[0] for c in _CASES} == set(FAMILIES) - _IMPLICIT


@pytest.mark.parametrize(("family", "shape"), _CASES)
def test_snap_and_d_frames_every_topic_family_validate_against_ws_schema(
    family: str, shape: tuple[str, ...]
) -> None:
    snap_body, delta_body = _SAMPLES[family]
    src = Source()
    src.bodies[family] = SnapshotBody(snap_body, price_scale=1, qty_scale=3)
    if family == "book":
        src.books[_SYM] = Book(_SYM)
        src.books[_SYM].apply([["100.0", "1.0"]], [["101.0", "2.0"]])
    conn = Conn(src)
    conn.authz.principal = PrincipalSnapshot(
        USER, frozenset({"owner"}), frozenset(Permission), (AccountGrant(ACC_A, True, True, True),)
    )
    _, sub = conn.authz.admit(_entry(family, shape))
    assert sub is not None
    conn.emitter.flush_pending([sub])
    assert conn.emitter.delta(sub, delta_body)
    snap, d = conn.take()  # Conn.push validated both against the envelope + payload schema
    assert (snap["t"], snap["s"], snap["meta"]["source"]) == ("snap", 1, "live")
    assert (d["t"], d["s"], d["ch"]) == ("d", 2, sub.ch)
    assert snap["ch"] == d["ch"] and d["e"] == "j" and snap["e"] == "j"


# -- §16.3 re-snapshot budgets --

_BUDGET_BYTES = 700 * KIB
_HARD_BYTES = 2 * 1024 * KIB


def _reference_workspace() -> tuple[Source, list[dict[str, Any]]]:
    """4 panes (§16.3): 1 m chart (500 bars), 5 m footprint (60 bars x 40 cells), depth-50 DOM,
    tape (100 trades). Deterministic, no clock or RNG."""
    src = _book_source(_SYM, levels=60)
    src.bodies["bars"] = SnapshotBody(
        {
            "symbol": _SYM,
            "bar_type": "time",
            "param": "1",
            "bars": [
                {
                    "generation": 0,
                    "index": i,
                    "t_ms": 1_789_000_000_000 + i * 60_000,
                    "o": "100.0",
                    "h": "101.0",
                    "l": "99.0",
                    "c": "100.5",
                    "v": "123.456",
                    "confirm": True,
                }
                for i in range(500)
            ],
        }
    )
    src.bodies["footprint"] = SnapshotBody(
        {
            "symbol": _SYM,
            "bar_type": "time",
            "param": "5",
            "bars": [
                {
                    "generation": 0,
                    "index": b,
                    "t_ms": 1_789_000_000_000 + b * 300_000,
                    "cells": [
                        {"price": f"{100 + p}.0", "bid_volume": "1.5", "ask_volume": "2.5"}
                        for p in range(40)
                    ],
                }
                for b in range(60)
            ],
        }
    )
    src.bodies["trades"] = SnapshotBody(
        {
            "symbol": _SYM,
            "trades": [
                {"ts_ms": 1_789_000_000_000 + i, "price": "100.5", "size": "0.01", "side": "buy"}
                for i in range(100)
            ],
        }
    )
    chans = [
        f"book.{_SYM}.50",
        f"bars.{_SYM}.time.1",
        f"footprint.{_SYM}.time.5",
        f"trades.{_SYM}",
    ]
    return src, [{"ch": c, "opts": {"encoding": "structured"}} for c in chans]


def _resnapshot() -> tuple[int, float, int]:
    """One re-snapshot of the reference workspace: (bytes, seconds, frames). Only the product's
    build and encode are timed. The harness validates the frames against the schema after the
    window (#2489: inside it, validation was about 99% of the measured time)."""
    src, entries = _reference_workspace()
    conn = Conn(src, cache=SnapshotCache())
    subs = [conn.sub(e)[1] for e in entries]
    conn.take()
    frames: list[dict[str, Any]] = []
    conn.emitter.push = frames.append
    start = time.perf_counter()
    for s in subs:
        conn.emitter.cache.invalidate(s.ch)
        conn.emitter.snapshot(s, "client_resync")
    elapsed = time.perf_counter() - start
    assert len(frames) >= len(subs)  # a window that emitted nothing must not pass as fast
    for frame in frames:
        validate(frame)
    size = sum(len(json.dumps(f, separators=(",", ":"))) for f in frames)
    return size, elapsed, len(frames)


def test_reference_workspace_resnapshot_size_is_under_700_kib() -> None:
    size, _, n = _resnapshot()
    assert n >= 4
    assert size < _BUDGET_BYTES < _HARD_BYTES


#: §16.3 re-snapshot time: 400 ms target, 1.5 s hard fail. The product path takes about 7 ms
#: (#2489), so the target holds with ample headroom on a shared runner; E17-Q03 (#568) measures
#: it on reference hardware.
_TARGET_S = 0.4
_HARD_S = 1.5


@pytest.mark.perf
def test_reference_workspace_resnapshot_build_and_encode_is_under_the_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    best = min(_resnapshot()[1] for _ in range(5))  # best-of-5 damps scheduler noise
    with capsys.disabled():  # recorded in the run's log, pass or fail
        print(f"\n§16.3 re-snapshot build+encode, best of 5: {best * 1000:.1f} ms")
    assert best < _HARD_S
    assert best < _TARGET_S


# -- resync window (§7.5) --


def test_client_resync_fifth_allowed_and_sixth_rejected_as_resync_rate_limited_revoked() -> None:
    conn = Conn(_book_source())
    _, sub = conn.sub({"ch": f"book.{_SYM}.50", "opts": {"encoding": "structured"}})
    conn.take()
    for i in range(5):  # all five inside one 60 s window are answered
        conn.clock.now = 10.0 * i
        _resync(conn, sub.ch)
        assert [f["t"] for f in conn.take()] == ["snap"]
    conn.clock.now = 50.0  # still inside the window of the first request
    _resync(conn, sub.ch)
    err, revoked = conn.take()
    assert (err["p"]["code"], revoked["p"]["reason"]) == ("resync_rate_limited",) * 2
    assert (err["t"], revoked["t"]) == ("err", "revoked")
    assert conn.authz.find(sub.ch) is None


# -- attaching without a snapshot (§7.6) --


def test_snapshot_false_with_gap_in_coverage_replies_snapshot_forced_true_and_sends_snap() -> None:
    src = _book_source()
    src.covered_from_ts = 2_000
    conn = Conn(src)
    result, sub = conn.sub(
        {"ch": f"book.{_SYM}.50", "opts": {"from_seq": 5, "from_ts_ms": 1_000}}, snapshot=False
    )
    assert result["snapshot_forced"] is True
    (snap,) = conn.take()
    assert snap["t"] == "snap" and snap["meta"]["reason"] == "initial" and sub.seq == 1


# -- 10 000 deltas reproduce the server state exactly --


def test_apply_10000_seeded_deltas_reproduces_server_book_exactly() -> None:
    rng = random.Random(411)  # noqa: S311 - seeded, non-cryptographic test data
    src = Source()
    book = Book(_SYM)
    book.apply([[f"{1000 - i}", "1"] for i in range(80)], [[f"{1001 + i}", "1"] for i in range(80)])
    src.books[_SYM] = book
    hub = SequencingHub()
    conn = Conn(src)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.sub({"ch": f"book.{_SYM}.50", "opts": {"encoding": "structured"}})
    client = RefClient()
    prev = book.top(50)
    deltas = 0
    for _ in range(10_000):
        side = rng.choice(("b", "a"))
        base = 1000 - rng.randrange(0, 90) if side == "b" else 1001 + rng.randrange(0, 90)
        size = rng.choice(("0", "0", str(rng.randrange(1, 500))))
        book.apply(
            [[str(base), size]] if side == "b" else [], [[str(base), size]] if side == "a" else []
        )
        new = (
            book_window(book.bids, 50, descending=True),
            book_window(book.asks, 50, descending=False),
        )
        hub.publish(
            sub.ch,
            {
                "symbol": _SYM,
                "bids": window_delta(prev[0], new[0]),
                "asks": window_delta(prev[1], new[1]),
            },
        )
        prev = new
        deltas += 1
    for f in conn.take():
        client.feed(f)
    assert deltas == 10_000 and sub.seq == 10_001 and client.gaps == 0
    assert (client.bids, client.asks) == book.top(50)


# -- stale flag under a stalled upstream --


class _FreshnessSource(Source):
    """Source whose `stale` follows the upstream freshness SLO against the injected clock."""

    def __init__(self, clock: Clock, slo_s: float) -> None:
        super().__init__()
        self.clock, self.slo_s, self.last_update = clock, slo_s, 0.0

    def build(self, sub: Any) -> SnapshotBody | None:
        self.stale = self.clock() - self.last_update > self.slo_s
        self.gen += 1  # freshness is part of the state identity: never serve a cached verdict
        return super().build(sub)


def test_snapshot_stale_flag_follows_stalled_upstream_and_clears_on_recovery() -> None:
    clock = Clock()
    src = _FreshnessSource(clock, slo_s=5.0)
    book = Book(_SYM)
    book.apply([["100.0", "1"]], [["101.0", "1"]])
    src.books[_SYM] = book
    hub = SequencingHub()
    conn = Conn(src, clock=clock)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.sub({"ch": f"book.{_SYM}.50", "opts": {"encoding": "structured"}})
    assert conn.take()[0]["p"]["stale"] is False
    clock.now = 30.0  # upstream stalled far beyond the SLO; no sleeping
    hub.resnapshot(lambda s: s.ch == sub.ch, "upstream_desync")
    (stale_snap,) = conn.take()
    assert stale_snap["p"]["stale"] is True and stale_snap["meta"]["reason"] == "upstream_desync"
    assert cv_ws_stale_topics_in_use._value.get() == 1
    src.last_update = 30.0  # feed resumes
    hub.resnapshot(lambda s: s.ch == sub.ch, "upstream_reconnect")
    (fresh_snap,) = conn.take()
    assert fresh_snap["p"]["stale"] is False
    assert cv_ws_stale_topics_in_use._value.get() == 0
