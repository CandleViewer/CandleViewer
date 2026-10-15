"""E17-S02 subscription manager: sub/unsub/ctl, scope narrowing, limits, live revocation,
upstream reference counting and the bar-series lease (pure asyncio; fake clock, no sleeps)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.bars.errors import BarSpecError, SpecCapExceeded
from candleviewer.bars.models import BarSpec
from candleviewer.ws._generated.error_codes import WS_ERROR_CODES
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    handle_ctl,
    handle_sub,
    handle_unsub,
)
from candleviewer.ws.revocation import CLOSE_USER_DISABLED
from candleviewer.ws.upstream import UpstreamRefs

A = uuid.UUID(int=0xA)
B = uuid.UUID(int=0xB)
C = uuid.UUID(int=0xC)
MGR_ID = uuid.UUID(int=0x100)
OWNER_ID = uuid.UUID(int=0x200)
VIEWER_ID = uuid.UUID(int=0x300)
RS = "bb000000-0000-4000-8000-000000000001"
MGR_PERMS = frozenset(
    {Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.POSITIONS_READ}
)
CATALOGUE = {c.value for c in WS_ERROR_CODES}


def _grant(acc: uuid.UUID) -> AccountGrant:
    return AccountGrant(acc, True, False, False)


def _mgr(*accounts: uuid.UUID, perms: frozenset[Permission] = MGR_PERMS) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        MGR_ID, frozenset({"manager"}), perms, tuple(_grant(a) for a in accounts)
    )


def _viewer() -> PrincipalSnapshot:
    perms = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ})
    return PrincipalSnapshot(VIEWER_ID, frozenset({"viewer"}), perms)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Sink:
    def __init__(self) -> None:
        self.opened: list[Any] = []
        self.dropped: list[Any] = []

    async def open(self, key: Any) -> None:
        self.opened.append(key)

    async def drop(self, key: Any) -> None:
        self.dropped.append(key)


class _Bars:
    def __init__(self, fail: Exception | None = None) -> None:
        self.registered: list[tuple[str, str, str, str | None]] = []
        self.released: list[tuple[str, str, str]] = []
        self.fail = fail

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        if self.fail is not None:
            raise self.fail
        self.registered.append((spec.spec_hash, symbol, consumer, user))

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self.released.append((spec_hash, symbol, consumer))


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


def _services(**kw: Any) -> SubscriptionServices:
    clock = kw.pop("clock", _Clock())
    return SubscriptionServices(
        upstream=kw.pop("upstream", UpstreamRefs(_Sink())), clock=clock, **kw
    )


def _sub(conn: ConnectionAuthz, *entries: Any, **body: Any) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    frame = {"t": "sub", "id": "c-1", "p": {"topics": list(entries), **body}}
    asyncio.run(handle_sub(conn, frame, send, now_ms=1))
    assert len(sent) == 1 and sent[0]["t"] == "sub_ok"
    results: list[dict[str, Any]] = sent[0]["p"]["results"]
    for r in results:
        assert r.get("error", {}).get("code", "forbidden") in CATALOGUE  # S10 closure
    return results


def _acc(*accounts: uuid.UUID) -> dict[str, Any]:
    return {"exchange_account_ids": [str(a) for a in accounts]}


# -- sub ---------------------------------------------------------------------------------------


def test_sub_partial_success_in_request_order() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    res = _sub(conn, {"ch": "book.BTCUSDT.50"}, "trades.BTCUSDT", {"ch": "orders", "opts": _acc(B)})
    assert [r["ch"] for r in res] == ["book.BTCUSDT.50", "trades.BTCUSDT", "orders"]
    assert [r["ok"] for r in res] == [True, True, False]
    assert res[2]["error"]["code"] == "account_scope_denied"
    for r in res[:2]:
        assert r["sub_id"] and r["snapshot_pending"] is True and r["effective"]
    assert conn.topics == {"book.BTCUSDT.50", "trades.BTCUSDT"}


def test_sub_clamping_is_reported() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "book.BTCUSDT.50", "opts": {"throttle_ms": 5}})
    assert r["effective"] == {
        "throttle_ms": 50, "encoding": "binary", "coalesce": True, "depth": 50,
    }  # fmt: skip


def test_sub_unknown_option_is_rejected_and_nothing_created() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "footprint.BTCUSDT.time.5", "opts": {"min_stak": 3}})
    assert r["error"]["code"] == "invalid_options" and r["error"]["field"] == "min_stak"
    assert conn.by_id == {}


def test_sub_unknown_entry_field_is_rejected() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "trades.BTCUSDT", "opt": {}})
    assert r["error"]["code"] == "invalid_options"


def test_sub_malformed_topics_distinguished() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    res = _sub(conn, "book.BTCUSDT.77", "bars.BTCUSDT.time.1.5", "book.ETHUSD.50")
    assert [r["error"]["code"] for r in res] == [
        "invalid_topic_format", "invalid_topic_format", "unsupported_symbol",
    ]  # fmt: skip


def test_sub_duplicate_is_rejected_with_ctl_advice() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT")
    (r,) = _sub(conn, "trades.BTCUSDT")
    assert r["error"]["code"] == "duplicate_subscription" and "ctl" in r["error"]["message"]


def test_sub_system_is_implicit_ok_and_not_counted() -> None:
    conn = ConnectionAuthz(_viewer(), _services())
    (r,) = _sub(conn, "system")
    assert r == {"ch": "system", "ok": True, "sub_id": "system"}
    assert conn.by_id == {}


def test_sub_forbidden_role() -> None:
    conn = ConnectionAuthz(_viewer(), _services())
    (r,) = _sub(conn, {"ch": "positions", "opts": _acc(A)})
    assert r["error"]["code"] == "forbidden"


def test_viewer_subscribing_orders_on_granted_account_succeeds_read_only() -> None:
    v = PrincipalSnapshot(VIEWER_ID, _viewer().roles, _viewer().permissions, (_grant(A),))
    conn = ConnectionAuthz(v, _services())
    (r,) = _sub(conn, {"ch": "orders", "opts": _acc(A)})
    assert r["ok"] and not conn.may_submit_order()


def test_sub_cross_account_raw_frame_is_denied() -> None:
    """IDOR: a manager scoped to A hand-crafts a sub for B."""
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "positions", "opts": _acc(B)})
    assert r["error"]["code"] == "account_scope_denied"
    assert conn.subs == set()


def test_sub_account_less_private_topic_is_denied() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, "positions")
    assert r["error"]["code"] == "account_scope_denied"


def test_sub_scope_is_silently_narrowed() -> None:
    conn = ConnectionAuthz(_mgr(A, C), _services())
    (r,) = _sub(conn, {"ch": "positions", "opts": _acc(A, B, C)})
    assert r["ok"] and r["effective"]["exchange_account_ids"] == sorted([str(A), str(C)])


def test_sub_owner_reaches_every_account() -> None:
    owner = PrincipalSnapshot(OWNER_ID, frozenset({"owner"}), frozenset(Permission))
    conn = ConnectionAuthz(owner, _services())
    (r,) = _sub(conn, {"ch": "wallet", "opts": _acc(B)})
    assert r["ok"]


def test_sub_snapshot_false_needs_from_seq() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, "trades.BTCUSDT", snapshot=False)
    assert r["error"]["field"] == "from_seq"
    (r,) = _sub(conn, {"ch": "trades.BTCUSDT", "opts": {"from_seq": 4}}, snapshot=False)
    # §7.6: continuity cannot be proven (no snapshot source) -> accepted, snapshot forced.
    assert r["ok"] and r["snapshot_pending"] is True and r["snapshot_forced"] is True
    (r,) = _sub(conn, "ticker.BTCUSDT", snapshot="yes")
    assert r["error"]["field"] == "snapshot"


def test_sub_limit_200_leaves_existing_untouched() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    for start in range(0, 200, 50):
        res = _sub(conn, *[f"bars.BTCUSDT.tick.{i}" for i in range(start + 1, start + 51)])
        assert all(r["ok"] for r in res)
    before = dict(conn.by_id)
    (r,) = _sub(conn, "trades.BTCUSDT")
    assert r["error"]["code"] == "subscription_limit"
    assert conn.by_id == before


def test_sub_symbol_limit_40_per_connection() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    syms = [f"S{i:02d}USDT" for i in range(40)]
    assert _sub(conn, {"ch": "ticker", "opts": {"symbols": syms}})[0]["ok"]
    assert _sub(conn, "trades.S00USDT")[0]["ok"]  # already-held symbol
    (r,) = _sub(conn, "trades.NEWUSDT")
    assert r["error"]["code"] == "subscription_limit"


def test_sub_more_than_50_topics_rejects_the_excess() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    res = _sub(conn, *[f"bars.BTCUSDT.tick.{i}" for i in range(1, 53)])
    assert [r["error"]["code"] for r in res[50:]] == ["too_many_topics"] * 2


def test_sub_encoding_unsupported() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": "ticker.BTCUSDT", "opts": {"encoding": "binary"}})
    assert r["error"]["code"] == "encoding_unsupported"


# -- replay coexistence --------------------------------------------------------------------------


def test_live_and_replay_subscriptions_coexist_by_sub_id() -> None:
    sink = _Sink()
    conn = ConnectionAuthz(_mgr(A), _services(upstream=UpstreamRefs(sink)))
    (live,) = _sub(conn, "book.BTCUSDT.200")
    (rep,) = _sub(conn, "book.BTCUSDT.200", replay_session_id=RS)
    assert live["ok"] and rep["ok"] and live["sub_id"] != rep["sub_id"]
    assert len(sink.opened) == 1  # replay never opens an upstream
    (dup,) = _sub(conn, "book.BTCUSDT.200", replay_session_id=RS)
    assert dup["error"]["code"] == "duplicate_subscription"


@pytest.mark.parametrize("topic", ["orders", "positions", "executions", "wallet"])
def test_private_topic_with_replay_session_is_invalid_options(topic: str) -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, {"ch": topic, "opts": _acc(A)}, replay_session_id=RS)
    assert r["error"]["code"] == "invalid_options"


@pytest.mark.parametrize("bad", ["nope", 5])
def test_malformed_replay_session_id_is_invalid_options(bad: Any) -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    (r,) = _sub(conn, "trades.BTCUSDT", replay_session_id=bad)
    assert r["error"]["field"] == "replay_session_id"


# -- unsub ---------------------------------------------------------------------------------------


def test_unsub_twice_is_idempotent() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    frame = {"t": "unsub", "p": {"topics": ["book.BTCUSDT.50"]}}
    assert handle_unsub(conn, frame) == [{"ch": "book.BTCUSDT.50", "ok": True}]
    assert handle_unsub(conn, frame) == [{"ch": "book.BTCUSDT.50", "ok": True, "noop": True}]


def test_unsub_system_is_refused() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    assert handle_unsub(conn, {"p": {"topics": ["system", 3]}}) == [{"ch": "system", "ok": False}]
    assert handle_unsub(conn, {"p": "x"}) == []


# -- ctl -----------------------------------------------------------------------------------------


def _ctl(conn: ConnectionAuthz, ch: str, body: Any) -> dict[str, Any]:
    return handle_ctl(conn, {"t": "ctl", "id": "c-9", "ch": ch, "p": body}, 7)


def test_ctl_retunes_throttle_without_resnapshot_and_keeps_sequence() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    sub = conn.find("book.BTCUSDT.50")
    assert sub is not None
    sub.seq, sub.snapshot_pending = 3000, False
    ok = _ctl(conn, "book.BTCUSDT.50", {"throttle_ms": 200})
    assert (ok["t"], ok["id"], ok["p"]) == ("ctl_ok", "c-9", {"effective": {"throttle_ms": 200}})
    assert sub.seq == 3000  # the next delta continues at 3001 (E17-S03)
    assert _ctl(conn, "book.BTCUSDT.50", {"throttle_ms": 5})["p"]["effective"]["throttle_ms"] == 50


def test_ctl_identity_change_forces_resnapshot() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "heatmap.BTCUSDT")
    sub = conn.find("heatmap.BTCUSDT")
    assert sub is not None
    sub.seq, sub.snapshot_pending = 10, False
    ok = _ctl(conn, "heatmap.BTCUSDT", {"time_bucket_ms": 1000})
    assert ok["p"]["resnapshot"] is True and ok["p"]["effective"]["time_bucket_ms"] == 1000
    assert (sub.seq, sub.snapshot_pending, sub.pending_reason) == (10, True, "reconfigure")
    again = _ctl(conn, "heatmap.BTCUSDT", {"time_bucket_ms": 1000})
    assert "resnapshot" not in again["p"]  # unchanged identity -> no re-snapshot


def test_ctl_paused_is_echoed() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT")
    assert _ctl(conn, "trades.BTCUSDT", {"paused": True})["p"]["effective"]["paused"] is True


def test_ctl_resume_after_a_pause_forces_resnapshot() -> None:
    """#2517: deltas dropped while paused took no sequence number, so a resume re-snapshots."""
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "book.BTCUSDT.50")
    sub = conn.find("book.BTCUSDT.50")
    assert sub is not None
    sub.seq, sub.snapshot_pending = 10, False
    assert "resnapshot" not in _ctl(conn, "book.BTCUSDT.50", {"paused": False})["p"]
    assert "resnapshot" not in _ctl(conn, "book.BTCUSDT.50", {"paused": True})["p"]
    assert not sub.snapshot_pending  # pausing keeps the subscription as it is
    ok = _ctl(conn, "book.BTCUSDT.50", {"paused": False})
    assert ok["p"]["resnapshot"] is True and ok["p"]["effective"]["paused"] is False
    assert (sub.seq, sub.snapshot_pending, sub.pending_reason) == (10, True, "reconfigure")


@pytest.mark.parametrize(
    ("body", "code"),
    [({}, "invalid_options"), ({"history": 5}, "invalid_options"), ({"throttle_ms": -1},
     "invalid_options"), ("x", "invalid_options")],
)  # fmt: skip
def test_ctl_rejects_bad_bodies(body: Any, code: str) -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT")
    err = _ctl(conn, "trades.BTCUSDT", body)
    assert (err["t"], err["p"]["code"]) == ("err", code)


def test_ctl_on_unsubscribed_topic_is_not_subscribed() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    err = handle_ctl(conn, {"t": "ctl", "ch": "book.BTCUSDT.50", "p": {"throttle_ms": 9}}, 1)
    assert (err["p"]["code"], err["ch"], "id" in err) == (
        "not_subscribed",
        "book.BTCUSDT.50",
        False,
    )


def test_ctl_on_replay_only_subscription_resolves_it() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, "trades.BTCUSDT", replay_session_id=RS)
    assert _ctl(conn, "trades.BTCUSDT", {"throttle_ms": 100})["t"] == "ctl_ok"


def _scope_of(conn: ConnectionAuthz, ch: str) -> tuple[Any, ...]:
    sub = conn.find(ch)
    assert sub is not None
    return (
        sub.accounts,
        sub.opts.get("exchange_account_ids"),
        sub.opts.get("symbols"),
        sub.opts.get("rule_ids"),
        sub.effective.get("exchange_account_ids"),
        sub.symbols,
        frozenset(sub.upstream),
    )


@pytest.mark.parametrize(
    ("ch", "opts", "key", "value"),
    [
        # Out-of-scope account (the IDOR widening attempt) and an in-scope one.
        ("positions", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(B)]),
        ("positions", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(A)]),
        ("positions", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(A), str(B)]),
        ("orders", {"exchange_account_ids": [str(A)]}, "symbols", ["BTCUSDT"]),
        ("ticker", {"symbols": ["BTCUSDT"]}, "symbols", ["ETHUSDT"]),
        ("ticker", {"symbols": ["BTCUSDT"]}, "symbols", ["BTCUSDT"]),
        ("liquidations", {"symbols": ["BTCUSDT"]}, "symbols", ["ETHUSDT"]),
        ("rules", {"exchange_account_ids": [str(A)]}, "rule_ids", [str(uuid.UUID(int=7))]),
        ("rules", {"exchange_account_ids": [str(A)]}, "exchange_account_ids", [str(B)]),
    ],
)
def test_ctl_cannot_change_subscription_scope(
    ch: str, opts: dict[str, Any], key: str, value: Any
) -> None:
    perms = MGR_PERMS | {Permission.RULES_READ}
    conn = ConnectionAuthz(_mgr(A, perms=perms), _services())
    (r,) = _sub(conn, {"ch": ch, "opts": opts})
    assert r["ok"], r
    before = _scope_of(conn, ch)
    err = _ctl(conn, ch, {key: value})
    assert (err["t"], err["p"]["code"], err["p"]["field"]) == ("err", "invalid_options", key)
    # Mixed with a legal retune, the whole ctl is still refused and nothing changes.
    err = _ctl(conn, ch, {"throttle_ms": 500, key: value})
    assert (err["p"]["code"], err["p"]["field"]) == ("invalid_options", key)
    assert _scope_of(conn, ch) == before
    if ch == "positions":
        assert conn.subs == {("positions", A)}


def test_ctl_keys_and_scope_keys_are_disjoint() -> None:
    from candleviewer.ws.topics import CTL_KEYS, SCOPE_OPTIONS

    every_scope_key = SCOPE_OPTIONS | {"exchange_account_ids", "symbols", "rule_ids"}
    assert not (CTL_KEYS & every_scope_key)
    # Every scope-bearing option any family declares is covered by SCOPE_OPTIONS.
    from candleviewer.ws.topics import FAMILIES

    declared = {k for f in FAMILIES.values() for k in f.options}
    assert declared & every_scope_key <= SCOPE_OPTIONS


# -- live revocation (§9.5) ----------------------------------------------------------------------


def test_scope_narrowed_mid_stream_revokes_only_the_removed_account() -> None:
    conn = ConnectionAuthz(_mgr(A, B), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A, B)}, "book.BTCUSDT.50")
    frames = conn.apply_snapshot(_mgr(A), 9)
    assert [f["t"] for f in frames] == ["permission_change", "revoked"]
    rv = frames[1]
    assert (rv["ch"], rv["p"]["reason"]) == ("positions", "account_scope_changed")
    assert rv["p"]["removed_accounts"] == [str(B)] and rv["p"]["resubscribe_allowed"] is True
    assert conn.subs == {("positions", A), ("book.BTCUSDT.50", None)}


def test_last_account_removed_drops_the_subscription() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A)})
    frames = conn.apply_snapshot(_mgr(), 9)
    assert frames[1]["p"]["removed_accounts"] == [str(A)]
    assert frames[1]["p"]["resubscribe_allowed"] is False
    assert conn.by_id == {}


def test_permission_lost_revokes_with_permission_revoked() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A)}, "trades.BTCUSDT")
    frames = conn.apply_snapshot(_mgr(A, perms=frozenset({Permission.MARKETDATA_READ})), 9)
    assert [(f["ch"], f["p"]["reason"]) for f in frames[1:]] == [
        ("positions", "permission_revoked")
    ]
    assert conn.topics == {"trades.BTCUSDT"}


def test_unchanged_snapshot_revokes_nothing() -> None:
    conn = ConnectionAuthz(_mgr(A), _services())
    _sub(conn, {"ch": "positions", "opts": _acc(A)})
    assert conn.apply_snapshot(_mgr(A), 1)[1:] == []


def _registry(snaps: dict[uuid.UUID, PrincipalSnapshot], **kw: Any) -> ConnectionRegistry:
    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        return snaps[uid]

    return ConnectionRegistry(resolve, lambda: 42, _services(**kw))


def test_registry_grants_changed_pushes_revoked_and_audits() -> None:
    audit = _Audit()
    snaps = {MGR_ID: _mgr(A, B)}
    reg = _registry(snaps, audit=audit)
    sent: list[dict[str, Any]] = []

    async def send(f: dict[str, Any]) -> None:
        sent.append(f)

    async def scenario() -> None:
        conn = ConnectionAuthz(snaps[MGR_ID], reg.services)
        reg.register(conn, send)
        await handle_sub(conn, {"p": {"topics": [{"ch": "positions", "opts": _acc(A, B)}]}}, send)
        snaps[MGR_ID] = _mgr(A)
        await reg.grants_changed(MGR_ID)

    asyncio.run(scenario())
    assert [f["t"] for f in sent] == ["sub_ok", "permission_change", "revoked"]
    assert [r["action"] for r in audit.records] == ["ws.subscription.revoked"]
    assert audit.records[0]["after_state"] == {"removed_accounts": [str(B)]}


def test_registry_kill_switch_reevaluates_every_user() -> None:
    snaps = {MGR_ID: _mgr(A), VIEWER_ID: _viewer()}
    reg = _registry(snaps)
    got: list[str] = []

    async def send(f: dict[str, Any]) -> None:
        got.append(f["t"])

    reg.register(ConnectionAuthz(snaps[MGR_ID], reg.services), send)
    reg.register(ConnectionAuthz(snaps[VIEWER_ID], reg.services), send)
    asyncio.run(reg.kill_switch_changed())
    assert got == ["permission_change", "permission_change"]


def test_registry_user_disabled_sends_bye_4403_and_releases() -> None:
    sink = _Sink()
    clock = _Clock()
    snaps = {MGR_ID: _mgr(A)}
    reg = _registry(snaps, upstream=UpstreamRefs(sink), clock=clock)
    closed: list[tuple[dict[str, Any], int]] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        closed.append((frame, code))

    async def noop(_f: dict[str, Any]) -> None:
        return None

    evicted: list[str] = []

    async def close() -> None:
        evicted.append("x")

    async def scenario() -> int:
        c1 = ConnectionAuthz(snaps[MGR_ID], reg.services)
        reg.register(c1, noop, None, closer)
        await handle_sub(c1, {"p": {"topics": ["trades.BTCUSDT"]}}, noop)
        reg.register(ConnectionAuthz(snaps[MGR_ID], reg.services), noop, close)
        n = await reg.user_disabled(MGR_ID)
        clock.now = 31.0
        await reg.services.upstream.sweep(clock.now)
        return n

    assert asyncio.run(scenario()) == 2
    (bye, code), = closed  # fmt: skip
    assert (bye["t"], bye["p"]["reason"], code) == ("bye", "user_disabled", CLOSE_USER_DISABLED)
    assert evicted == ["x"] and len(sink.dropped) == 1
    assert asyncio.run(reg.user_disabled(MGR_ID)) == 0


def test_registry_unregister_releases_upstream_into_grace() -> None:
    clock = _Clock()
    sink = _Sink()
    reg = _registry({MGR_ID: _mgr(A)}, upstream=UpstreamRefs(sink), clock=clock)

    async def noop(_f: dict[str, Any]) -> None:
        return None

    conn = ConnectionAuthz(_mgr(A), reg.services)
    reg.register(conn, noop)
    asyncio.run(handle_sub(conn, {"p": {"topics": ["book.BTCUSDT.50"]}}, noop))
    reg.unregister(conn)
    assert asyncio.run(reg.services.upstream.sweep(29.9)) == []
    assert len(asyncio.run(reg.services.upstream.sweep(30.0))) == 1


# -- upstream reference counting (US-MKT-005) ----------------------------------------------------


def test_three_panes_two_connections_share_one_upstream_and_drop_after_grace() -> None:
    clock = _Clock()
    sink = _Sink()
    services = _services(upstream=UpstreamRefs(sink), clock=clock)
    c1 = ConnectionAuthz(_mgr(A), services)
    c2 = ConnectionAuthz(_viewer(), services)
    _sub(c1, "book.BTCUSDT.50")
    _sub(c2, "book.BTCUSDT.50")
    _sub(c2, "book.BTCUSDT.50", replay_session_id=RS)  # third pane (replay: no upstream)
    key = ("BTCUSDT", "book", ("50",))
    assert sink.opened == [key] and services.upstream.consumers(key) == 2
    c1.unsubscribe("book.BTCUSDT.50")
    c2.release_all()
    clock.now = 10.0
    assert asyncio.run(services.upstream.sweep(clock.now)) == []
    assert asyncio.run(services.upstream.sweep(29.99)) == []
    assert asyncio.run(services.upstream.sweep(30.0)) == [key]
    assert sink.dropped == [key]


def test_reopen_inside_grace_does_not_churn_upstream() -> None:
    clock = _Clock()
    sink = _Sink()
    services = _services(upstream=UpstreamRefs(sink), clock=clock)
    conn = ConnectionAuthz(_mgr(A), services)
    _sub(conn, "trades.BTCUSDT")
    conn.unsubscribe("trades.BTCUSDT")
    clock.now = 20.0
    _sub(conn, "trades.BTCUSDT")
    assert asyncio.run(services.upstream.sweep(100.0)) == []
    assert len(sink.opened) == 1 and sink.dropped == []


def test_batched_ticker_takes_one_ref_per_symbol() -> None:
    sink = _Sink()
    conn = ConnectionAuthz(_mgr(A), _services(upstream=UpstreamRefs(sink)))
    _sub(conn, {"ch": "ticker", "opts": {"symbols": ["BTCUSDT", "ETHUSDT"]}})
    assert sorted(k[0] for k in sink.opened) == ["BTCUSDT", "ETHUSDT"]


def test_private_topics_take_no_upstream_ref() -> None:
    sink = _Sink()
    conn = ConnectionAuthz(_mgr(A), _services(upstream=UpstreamRefs(sink)))
    _sub(conn, {"ch": "positions", "opts": _acc(A)})
    assert sink.opened == []


# -- BarBuilderSet lease (spec cap) --------------------------------------------------------------


def test_bars_sub_registers_series_with_the_authenticated_principal() -> None:
    bars = _Bars()
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars), connection_id="c-x")
    (r,) = _sub(conn, {"ch": "bars.BTCUSDT.time.5", "opts": {"history": 5}})
    assert r["ok"]
    ((spec_hash, sym, consumer, user),) = bars.registered
    assert (sym, consumer, user) == ("BTCUSDT", "c-x/" + r["sub_id"], str(MGR_ID))
    conn.unsubscribe("bars.BTCUSDT.time.5")
    assert bars.released == [(spec_hash, "BTCUSDT", "c-x/" + r["sub_id"])]


def test_bars_spec_cap_maps_to_subscription_limit_and_creates_nothing() -> None:
    bars = _Bars(fail=SpecCapExceeded("per_user", 8, 8))
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars))
    (r,) = _sub(conn, "footprint.BTCUSDT.tick.100")
    assert r["error"]["code"] == "subscription_limit" and conn.by_id == {}


def test_bars_unbuildable_spec_is_invalid_topic_format() -> None:
    conn = ConnectionAuthz(_mgr(A), _services(bars=_Bars(fail=BarSpecError("no"))))
    (r,) = _sub(conn, "bars.BTCUSDT.pnf.10:3")
    assert r["error"]["code"] == "invalid_topic_format" and conn.by_id == {}


def test_replay_bars_never_take_a_live_lease() -> None:
    bars = _Bars()
    conn = ConnectionAuthz(_mgr(A), _services(bars=bars))
    _sub(conn, "bars.BTCUSDT.time.5", replay_session_id=RS)
    assert bars.registered == []


# -- audit ---------------------------------------------------------------------------------------


def test_denials_are_audited_and_audit_failure_is_not_fatal() -> None:
    audit = _Audit()
    conn = ConnectionAuthz(_mgr(A), _services(audit=audit))
    _sub(conn, {"ch": "positions", "opts": _acc(B)}, "book.ETHUSD.50", {"ch": "orders", "opts": 1})
    assert [(r["action"], r["reason"]) for r in audit.records] == [
        ("ws.subscribe.denied", "account_scope_denied"),
        ("ws.subscribe.denied", "invalid_options"),
    ]

    class _Broken:
        async def emit(self, action: str, **kw: Any) -> None:
            raise RuntimeError("down")

    conn2 = ConnectionAuthz(_viewer(), _services(audit=_Broken()))
    (r,) = _sub(conn2, {"ch": "positions", "opts": _acc(A)})
    assert r["error"]["code"] == "forbidden"
    assert conn2.apply_snapshot(_viewer(), 1)  # no crash either
    reg = _registry({VIEWER_ID: _viewer()}, audit=_Broken())

    async def noop(_f: dict[str, Any]) -> None:
        return None

    c3 = ConnectionAuthz(PrincipalSnapshot(VIEWER_ID, _viewer().roles, MGR_PERMS, (_grant(A),)),
                         reg.services)  # fmt: skip
    reg.register(c3, noop)
    _sub(c3, {"ch": "positions", "opts": _acc(A)})
    asyncio.run(reg.roles_changed(VIEWER_ID))  # revocation audit fails: still delivered
    assert c3.by_id == {}
