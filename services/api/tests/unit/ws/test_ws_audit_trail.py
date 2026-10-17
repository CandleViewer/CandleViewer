"""SR-186 / SR-187 / SR-E17-04 (#2174): the WS audit trail and its failure counter.

The new private-topic subscriptions of a `sub` frame write ONE `ws.subscribe.granted` record once
its `sub_ok` is queued (WS-R01); a resync-rate-limit revocation writes `ws.subscription.revoked`;
the 3rd failed `auth`'s row and the revocation, disable and slow-consumer close rows name who and
from where. Every WS audit row not confirmed written counts once in `cv_ws_audit_failures_total`
(the fan-out's: `test_revocation_fanout.py`). No sleeps: event-gated sinks, bounds patched to 0 or
10 ms, and the bounded socket helpers of `test_lifecycle_socket`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

import candleviewer.ws.gateway as gateway
import tests.unit.ws.test_lifecycle_socket as ls
from candleviewer.api.csrf import RefusalAuditTracker
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws import permissions
from candleviewer.ws.lifecycle import OriginRefusal
from candleviewer.ws.metrics import AUDIT_FAILURE_REASONS, count_audit_failure
from candleviewer.ws.metrics import cv_ws_audit_failures_total as failures_total
from candleviewer.ws.origin_audit import OriginRefusalAudit
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.sequencing import RESYNC_MAX_PER_WINDOW
from tests.unit.ws.test_gateway_teardown import _UVICORN_CANCEL, _cancel, _Rig, _Socket
from tests.unit.ws.test_origin_refusal_audit import SLOW_S, _FailingAudit, _StalledAudit

GRANTED, DENIED, REVOKED = "ws.subscribe.granted", "ws.subscribe.denied", "ws.subscription.revoked"
MGR = uuid.UUID(int=0x2174)
A, B, C = (uuid.UUID(int=n) for n in (0xA, 0xB, 0xC))  # C is never granted
PERMS = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.POSITIONS_READ})
GRANTS = tuple(AccountGrant(a, True, False, False) for a in (A, B))


def _failures() -> dict[str, float]:
    """`cv_ws_audit_failures_total` now, by reason."""
    (family,) = failures_total.collect()
    return {s.labels["reason"]: s.value for s in family.samples if s.name.endswith("_total")}


def _delta(before: Mapping[str, float]) -> dict[str, float]:
    """The reasons that moved since `before`, and by how much."""
    return {r: v - before[r] for r, v in _failures().items() if v != before[r]}


class _Sink:
    """Records each row and the frames sent before it. A write of the `fail` action raises; one of
    the `hang` action first waits for `release` (unset, only a bound or a cancellation ends it)."""

    def __init__(self, sent: list[dict[str, Any]], fail: str = "", hang: str = "") -> None:
        self.sent, self.fail, self.hang = sent, fail, hang
        self.rows: list[dict[str, Any]] = []
        self.sent_before: dict[str, list[str]] = {}
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)  # refused unless registered, as `AuditWriter.emit` does
        self.entered.set()
        if action == self.hang:
            await self.release.wait()
        if action == self.fail:
            raise OSError("audit WAL unavailable")
        self.sent_before[action] = [f["t"] for f in self.sent]
        self.rows.append({"action": action, **kw})


def _connection(**sink: str) -> tuple[ConnectionAuthz, list[dict[str, Any]], _Sink]:
    """A Manager's connection granted accounts A and B, over a `_Sink`."""
    sent: list[dict[str, Any]] = []
    principal = PrincipalSnapshot(MGR, frozenset({"manager"}), PERMS, GRANTS)
    audit = _Sink(sent, **sink)
    return ConnectionAuthz(principal, SubscriptionServices(audit=audit)), sent, audit


async def _sub(authz: ConnectionAuthz, sent: list[dict[str, Any]], *topics: Any) -> None:
    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    await handle_sub(authz, {"t": "sub", "id": "s", "p": {"topics": list(topics)}}, send, now_ms=1)


def _acc(ch: str, *accounts: uuid.UUID) -> dict[str, Any]:
    return {"ch": ch, "opts": {"exchange_account_ids": [str(a) for a in accounts]}}


def test_every_reason_is_bound_at_import() -> None:
    assert set(_failures()) == set(AUDIT_FAILURE_REASONS)
    assert AUDIT_FAILURE_REASONS == ("error", "timeout", "cancelled", "abandoned")


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (TimeoutError(), "timeout"),
        (asyncio.CancelledError(), "cancelled"),
        (OSError(), "error"),
        (ExceptionGroup("sink", [TimeoutError()]), "error"),  # the sink raised, whatever it wraps
    ],
)
def test_the_exception_being_handled_names_the_reason(exc: BaseException, reason: str) -> None:
    before = _failures()
    try:
        raise exc
    except (TimeoutError, asyncio.CancelledError, OSError, ExceptionGroup):
        count_audit_failure()
    assert _delta(before) == {reason: 1}


def test_an_unknown_reason_or_no_exception_counts_error_and_adds_no_series() -> None:
    before = _failures()
    unknown: Any = "timed_out"  # a typo past the type check
    count_audit_failure(1, unknown)
    count_audit_failure()  # outside an `except`
    assert _delta(before) == {"error": 2} and set(_failures()) == set(AUDIT_FAILURE_REASONS)


# -- SR-186: one `ws.subscribe.granted` record per `sub` frame ------------------------------------


async def test_a_sub_frame_writes_one_granted_row_for_its_new_private_subscriptions() -> None:
    authz, sent, sink = _connection()
    # `trades` is public; `wallet` needs `accounts:read`, so it is refused (its own denial row).
    topics = [_acc("positions", A, B), "trades.BTCUSDT", _acc("orders", A), _acc("wallet", A)]
    await _sub(authz, sent, *topics)
    assert [r["action"] for r in sink.rows] == [DENIED, GRANTED]  # one each, never one per topic
    listed = [["positions", [str(A), str(B)]], ["orders", [str(A)]]]
    assert sink.rows[1] == {
        "action": GRANTED,
        "actor_label": "ws",
        "actor_user_id": MGR,
        "object_kind": "ws_connection",
        "object_id": authz.connection_id,
        "outcome": AuditOutcome.SUCCESS,
        "severity": Severity.INFO,
        "after_state": {"count": 2, "subscriptions": listed},
        "request_id": None,  # the upgrade's E04 id on a socket; none outside a request
    }
    assert sink.sent_before == {DENIED: [], GRANTED: ["sub_ok"]}  # after the reply is queued


@pytest.mark.parametrize(
    "topics", [["trades.BTCUSDT"], [_acc("orders", C)]], ids=["public", "private_refused"]
)
async def test_a_frame_without_a_new_private_subscription_writes_no_granted_row(
    topics: list[Any],
) -> None:
    authz, sent, sink = _connection()
    await _sub(authz, sent, *topics)
    assert GRANTED not in [r["action"] for r in sink.rows] and sent[-1]["t"] == "sub_ok"


async def test_the_granted_row_lists_the_first_max_grants_listed_and_counts_them_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(permissions, "MAX_GRANTS_LISTED", 1)
    authz, sent, sink = _connection()
    await _sub(authz, sent, _acc("positions", B), _acc("orders", A))
    (row,) = sink.rows
    assert row["after_state"] == {"count": 2, "subscriptions": [["positions", [str(B)]]]}


def test_the_contract_and_the_threat_model_state_how_many_grants_are_listed() -> None:
    """§5.2 and WS-R01 give the bound in prose: a change to the constant must change both."""
    n, docs = permissions.MAX_GRANTS_LISTED, Path(__file__).resolve().parents[5] / "docs"
    contract = (docs / "plan" / "23-ws-protocol.md").read_text(encoding="utf-8")
    threats = (docs / "security" / "threat-models" / "E17-ws-gateway.md").read_text("utf-8")
    assert f"for the first {n} in request order" in contract
    assert f"the first {n} listed, all counted" in threats


@pytest.mark.parametrize(("mode", "reason"), [("fail", "error"), ("hang", "timeout")])
async def test_a_granted_row_not_confirmed_is_logged_and_counted_and_the_reply_still_goes(
    mode: str, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(permissions, "FANOUT_AUDIT_TIMEOUT_S", 0.01)
    authz, sent, _ = _connection(**{mode: GRANTED})
    before = _failures()
    with capture_logs() as logs:
        async with asyncio.timeout(5):  # fail fast, not hang, if the bound regresses
            await _sub(authz, sent, _acc("positions", A))
    assert [f["t"] for f in sent] == ["sub_ok"] and len(authz.by_id) == 1
    assert _delta(before) == {reason: 1}
    (line,) = [e for e in logs if e["event"] == "ws subscribe-granted audit not confirmed"]
    assert (line["log_level"], line["connection_id"]) == ("warning", authz.connection_id)


@pytest.mark.parametrize("action", [GRANTED, DENIED])
async def test_a_cancelled_sub_audit_row_is_counted_and_the_cancellation_propagates(
    action: str,
) -> None:
    authz, sent, sink = _connection(hang=action)
    before = _failures()
    task = asyncio.create_task(_sub(authz, sent, _acc("positions", A if action == GRANTED else C)))
    async with asyncio.timeout(5):
        await sink.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _delta(before) == {"cancelled": 1}


async def test_a_refusal_row_that_fails_is_counted() -> None:
    authz, sent, _ = _connection(fail=DENIED)
    before = _failures()
    await _sub(authz, sent, _acc("orders", C))
    assert _delta(before) == {"error": 1} and sent[-1]["t"] == "sub_ok"


# -- the gateway: the resync revocation, the failed auth and the close rows -----------------------


@pytest.fixture
def world() -> Any:
    w = ls._World()
    w.registry.services.audit = w.audit  # the permission layer's sink, as `create_app` wires it
    with w.client:
        yield w


def _rows(world: ls._World, action: str) -> list[dict[str, Any]]:
    return [r for r in world.audit.records if r["action"] == action]


def test_a_resync_rate_limited_revocation_writes_its_revoked_row(world: ls._World) -> None:
    ch = "book.BTCUSDT.50"
    with world.client.websocket_connect("/ws", subprotocols=ls.JSON) as ws:
        ls._hello(ws)
        ls._auth(ws)
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [ch]}})
        assert ls._recv_type(ws, "sub_ok")["p"]["results"][0]["ok"] is True
        for i in range(RESYNC_MAX_PER_WINDOW + 1):  # every one at the fake clock's t=0
            ws.send_json({"t": "resync", "id": f"r{i}", "ch": ch, "p": {"reason": "manual"}})
        assert ls._recv_type(ws, "err")["p"]["code"] == "resync_rate_limited"
        assert ls._recv(ws)["p"]["reason"] == "resync_rate_limited"
        ls._settle(world, lambda: bool(_rows(world, REVOKED)))
    (row,) = _rows(world, REVOKED)  # the close row follows once the socket is gone
    assert (row["object_id"], row["reason"]) == (ch, "resync_rate_limited")
    assert (row["actor_user_id"], row["after_state"]) == (ls.USER, {"removed_accounts": []})


def test_the_third_failed_auth_row_names_the_source_address_and_the_request(
    world: ls._World,
) -> None:
    headers = {"x-correlation-id": ls.REQUEST_ID}
    with world.client.websocket_connect("/ws", subprotocols=ls.JSON, headers=headers) as ws:
        ls._hello(ws)
        for i in range(2):
            assert ls._auth(ws, f"{ls.REJECTED_MARK}-{i}")["p"]["code"] == "auth_failed"
        ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": f"{ls.REJECTED_MARK}-2"}})
        bye, code = ls._bye_then_close(ws)
    (row,) = world.audit.records  # written before the `bye`; an unauthenticated close has none
    assert (bye["p"]["reason"], code, row["action"]) == ("auth_failed", 4401, "auth.login_failed")
    assert (row["actor_ip"], row["request_id"], row["reason"]) == (
        "testclient",
        ls.REQUEST_ID,
        "ws_auth_failed",
    )
    # No identity before a first `auth` succeeds: the source address is what aggregates (SR-187).
    assert row["actor_user_id"] is None and ls.REJECTED_MARK not in repr(row)


@pytest.mark.parametrize(("failure", "reason"), [("raises", "error"), ("hangs", "timeout")])
@pytest.mark.parametrize("row", ["auth-failure", "close"])
def test_a_gateway_row_not_confirmed_is_counted_and_the_close_still_goes(
    world: ls._World, row: str, failure: str, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(action: str, **kw: Any) -> None:
        if failure == "raises":
            raise OSError("audit WAL unavailable")
        await asyncio.Event().wait()  # a stalled sink: only the bound ends it

    monkeypatch.setattr(world.audit, "emit", broken)
    monkeypatch.setattr(gateway, "CLOSE_AUDIT_TIMEOUT_S", 0)
    before = _failures()
    with capture_logs() as logs:
        with world.client.websocket_connect("/ws", subprotocols=ls.JSON) as ws:
            ls._hello(ws)
            if row == "close":
                ls._auth(ws)
                ws.close(1000)
            else:
                for _ in range(2):
                    assert ls._auth(ws, ls.REJECTED_MARK)["p"]["code"] == "auth_failed"
                ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": ls.REJECTED_MARK}})
                assert ls._bye_then_close(ws)[0]["p"]["reason"] == "auth_failed"
            ls._settle(world, lambda: _failures() != before)
    assert _delta(before) == {reason: 1}
    events = [e["log_level"] for e in logs if e["event"] == f"ws {row} audit not confirmed"]
    assert events == ["warning"]


@pytest.mark.parametrize("row", ["close", "auth-failure"])
async def test_a_cancel_inside_a_gateway_row_is_counted_and_still_propagates(
    row: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, sock, emitting = _Rig(), _Socket(), asyncio.Event()

    async def hung_emit(action: str, **kw: Any) -> None:
        emitting.set()
        await asyncio.Event().wait()  # a sink that never answers

    monkeypatch.setattr(rig.audit, "emit", hung_emit)
    before = _failures()
    async with asyncio.timeout(5):
        if row == "close":
            handler = await rig.authenticated(sock)
            handler.cancel(msg=_UVICORN_CANCEL)  # the first, mid-read: the teardown writes it
        else:  # three `auth` frames without a token: the 3rd failure writes its row
            handler = asyncio.create_task(rig.endpoint(sock))
            sock.feed({"t": "hello", "id": "h"})
            for _ in range(3):
                sock.feed({"t": "auth", "id": "a", "p": {}})
        await emitting.wait()  # the row now waits on the sink
        await _cancel(handler)  # a cancel inside the emit: the handler still ends cancelled
    assert _delta(before) == {"cancelled": 1}


@pytest.mark.parametrize(
    ("close", "reason", "severity"),
    [
        ("session", "session_revoked", "info"),
        ("session_disabled", "user_disabled", "info"),
        ("user_disabled", "user_disabled", "info"),
        ("evicted", "slow_consumer", "warning"),
    ],
)
def test_revocation_disable_and_slow_consumer_closes_are_rows_per_identity_and_source(
    world: ls._World, close: str, reason: str, severity: str
) -> None:
    with world.client.websocket_connect("/ws", subprotocols=ls.JSON) as ws:
        ls._hello(ws)
        ls._auth(ws)
        portal = world.client.portal
        assert portal is not None
        if close.startswith("session"):  # the session service's publish, or the registry's
            disabled = close == "session_disabled"
            reasons = ("user_disabled",) if disabled else ()
            assert portal.call(world.revocation.revoke, ls.SESSION, *reasons) == 1
        elif close == "user_disabled":
            assert portal.call(world.registry.user_disabled, ls.USER) == 1
        else:
            (conn,) = world.hub.of_user(ls.USER)
            portal.call(conn.evict)
        assert ls._bye_then_close(ws)[0]["p"]["reason"] == reason
        (row,) = ls._close_audits(world)
    assert (row["reason"], row["severity"], row["actor_ip"]) == (reason, severity, "testclient")
    assert (row["actor_user_id"], row["session_id"]) == (ls.USER, ls.SESSION)


async def test_a_refused_upgrade_row_not_confirmed_is_counted_once() -> None:
    before = _failures()
    failing = OriginRefusalAudit(_FailingAudit(), tracker=RefusalAuditTracker())
    assert await failing.record(OriginRefusal.ORIGIN_MISSING, "100.64.0.7") is True
    stalled, tracker = _StalledAudit(), RefusalAuditTracker()
    slow = OriginRefusalAudit(stalled, tracker=tracker, timeout_s=SLOW_S)
    assert await slow.record(OriginRefusal.CROSS_SITE, "100.64.0.8") is True
    stalled.release.set()
    assert await tracker.drain(5) == 0  # the slow one lands late: counted once, as `timeout`
    assert _delta(before) == {"error": 1, "timeout": 1}


@pytest.mark.parametrize("fails", [True, False])
async def test_a_cancelled_upgrade_audit_wait_counts_only_a_late_failure(fails: bool) -> None:
    refused, tracker = "auth.ws_origin_refused", RefusalAuditTracker()
    sink = _Sink([], fail=refused if fails else "", hang=refused)
    audit, before = OriginRefusalAudit(sink, tracker=tracker), _failures()
    task = asyncio.create_task(audit.record(OriginRefusal.CROSS_SITE, "100.64.0.9"))
    async with asyncio.timeout(5):
        await sink.entered.wait()
        task.cancel()  # the upgrade's handler is cancelled while it waits for the row
        with pytest.raises(asyncio.CancelledError):
            await task
        sink.release.set()  # the shielded write runs on: it fails, or it lands
        assert await tracker.drain(5) == 0
    assert _delta(before) == ({"error": 1} if fails else {})
