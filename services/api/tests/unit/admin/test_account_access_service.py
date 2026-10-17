"""`AccountAccessService` (E42-T08 S9c, #2648): the write behind
`PUT /users/{userId}/account-access`, over the real store, whose unit of work is the store tests'
fake. A refusal changes nothing: no write, no record, no push. The route over it is
tests/unit/api/test_users_account_access_put.py, and AC3 end to end is
tests/unit/architecture/test_ws_principal_composition.py."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Coroutine, Iterator, Mapping, Sequence
from typing import Any, cast

import pytest
import structlog
from prometheus_client import REGISTRY
from sqlalchemy.exc import DBAPIError, InvalidRequestError

from candleviewer.admin.account_access import (
    COUNT_TIMEOUT_S,
    DRAIN_TIMEOUT_S,
    PUSH_WAIT_S,
    AccountAccessService,
)
from candleviewer.observability.context import bind_context
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories import account_access_sqlalchemy as m
from candleviewer.storage.repositories.account_access import (
    AccessAuditUnavailableError,
    AccessBusyError,
    AccessGrant,
    AccessPositionsUnknownError,
    AccessSelfTargetError,
    AccessUnknownAccountError,
    AccessUserNotActiveError,
    AccessUserNotFoundError,
    RemovalContext,
)
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    handle_sub,
)
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import KillSwitchView, StorePrincipalLoader, WsEvents
from tests.unit.api import test_users_account_access_get as g
from tests.unit.storage import test_account_access_sqlalchemy as st
from tests.unit.ws import test_store_principal_loader as ld

CALLER, TARGET, OTHER, _A, _B, _C = g.CALLER, g.TARGET, g.OTHER, st._A, st._B, st._C
_HELD_A = ((_A, True, False, False, None, OTHER),)  # the target's one live grant: _A read
_BY_CALLER: Any = {"actor_user_id": CALLER, "acknowledge_unknown_positions": False}
_ACKNOWLEDGED: Any = _BY_CALLER | {"acknowledge_unknown_positions": True}


class _Positions:  # `PositionStateProvider`: a count, `None` (unknown), an error or "hang"
    source = "test"

    def __init__(self, result: object) -> None:
        self.result, self.asked = result, list[str]()

    def open_position_count(self, user_id: str) -> Coroutine[Any, Any, int | None]:
        self.asked.append(user_id)  # noted when asked: the read is built before it is awaited
        return self._read()

    async def _read(self) -> int | None:
        if self.result == "hang":
            await asyncio.Event().wait()
        if isinstance(self.result, Exception):
            raise self.result
        return cast(int | None, self.result)


class _Notifier:
    """`WsEvents.grants_changed`: each push, with whether the change had committed by then."""

    def __init__(self, rel: Any, error: Exception | None) -> None:
        self.rel, self.error, self.pushes = rel, error, list[tuple[uuid.UUID, bool]]()
        self.entered, self.gate = asyncio.Event(), asyncio.Event()
        self.gate.set()

    async def grants_changed(self, user_id: uuid.UUID) -> None:
        self.entered.set()
        await self.gate.wait()
        if self.error is not None:
            raise self.error
        self.pushes.append((user_id, self.rel.committed))


class _World:
    def __init__(self, rel: Any = None, *, positions: object = None, **kw: Any) -> None:
        self.rel = rel or st._Rel(rows=_HELD_A)
        self.audit = st._Audit(self.rel, error=kw.pop("audit_error", None))
        self.notifier = _Notifier(self.rel, kw.pop("push_error", None))
        self.positions = _Positions(positions)
        self.store = store = m.SqlAlchemyAccountAccessStore(cast(Any, self.rel), audit=self.audit)
        self.service = AccountAccessService(store, self.notifier, positions=self.positions, **kw)

    def unchanged(self) -> bool:
        """No write statement ran, and no record, commit or push."""
        ran = {s.text for s in self.rel.ran()}
        written = ran & {m._REVOKE.text, m._UPSERT.text, m._INHERIT.text}
        return not (written or self.audit.calls or self.rel.committed or self.notifier.pushes)


def _push_lines(logs: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    return [(e["outcome"], e["log_level"]) for e in logs if e["event"] == "account access push"]


def _counted(outcome: str) -> float:  # the push's `cv_user_lifecycle_steps_total`, read as a delta
    labels = {"step": "grants_push", "outcome": outcome}
    return REGISTRY.get_sample_value("cv_user_lifecycle_steps_total", labels) or 0.0


@contextlib.contextmanager
def _fake_clock(method: str, *, first_only: bool = False) -> Iterator[list[float]]:
    """The running loop's timer as the fake clock for the body (C-13.7): `call_later`, which
    `asyncio.wait` sets its timeout with, or `call_at`, which `asyncio.timeout` does. Each delay
    asked for is recorded and the timer fires at the next turn of the loop, so nothing waits on a
    wall clock; with `first_only` only the first does, and later timers run as they are."""
    loop = asyncio.get_running_loop()
    real, asked = getattr(loop, method), list[float]()

    def timer(when: float, callback: Callable[..., object], *args: object, **kw: Any) -> Any:
        asked.append(when if method == "call_later" else when - loop.time())
        if first_only and len(asked) > 1:
            return real(when, callback, *args, **kw)
        return real(0 if method == "call_later" else loop.time(), callback, *args, **kw)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(loop, method, timer)
        yield asked


@pytest.mark.parametrize(
    ("grants", "ack"),
    [({_B: "trade"}, True), ({_A: "read", _B: "trade"}, False)],
    ids=["swap-acknowledged", "add-only"],
)
async def test_replace_records_ahead_commits_then_pushes(grants: dict[Any, Any], ack: bool) -> None:
    """The record is written ahead of the commit and names the caller's session and address
    (C-2.9); the push follows the commit, an addition alone pushing too (§9.5). The change is the
    set the store read under its locks, a kept grant keeping its granter."""
    w, asked = _World(), _BY_CALLER | {"acknowledge_unknown_positions": ack}
    pushed = _counted("pushed")
    change = await w.service.replace(
        TARGET, grants, actor_ip=st._IP, session_id=st._SESSION, **asked
    )
    ((action, record, _, committed_at_record),) = w.audit.calls
    assert action == "users.access_change" and not committed_at_record and w.rel.committed
    assert (record["actor_ip"], record["session_id"]) == (st._IP, st._SESSION)
    assert w.notifier.pushes == [(TARGET, True)] and _counted("pushed") == pushed + 1
    granter = {_A: OTHER, _B: CALLER}
    assert change.granted == tuple(
        AccessGrant(a, level, st._label(a), "demo", granter[a])
        for a, level in sorted(grants.items())
    )


@pytest.mark.parametrize("bound", [uuid.uuid4(), None], ids=["bound", "unbound"])
async def test_replace_names_the_request_in_the_record_written_ahead(
    bound: uuid.UUID | None,
) -> None:
    """C-2.9: the id the correlation middleware bound reaches the write-ahead record, and a
    request with none leaves it empty."""
    w = _World()
    with bind_context(request_id=bound):
        await w.service.replace(TARGET, {_B: "trade"}, **_ACKNOWLEDGED)
    ((_, record, _, _),) = w.audit.calls
    assert record["request_id"] == bound


async def test_replace_refuses_a_malformed_request_id_before_asking_for_a_count() -> None:
    """The id is parsed first: a count read built before it would be left never awaited."""
    w = _World()
    with bind_context(request_id="not-a-uuid"), pytest.raises(ValueError, match="UUID"):
        await w.service.replace(TARGET, {}, **_ACKNOWLEDGED)
    assert w.positions.asked == [] and w.unchanged()


async def test_noop_writes_nothing_and_pushes_nothing() -> None:
    w = _World()
    change = await w.service.replace(TARGET, {_A: "read"}, **_BY_CALLER)
    assert await w.service.drain() == 0  # nothing is in flight
    assert not change.changed and w.unchanged()
    assert change.granted == (AccessGrant(_A, "read", st._label(_A), "demo", OTHER),)


@pytest.mark.parametrize(
    ("rows", "grants", "positions"),
    [(_HELD_A, {}, None), ((*_HELD_A, (_B, True, True)), {_B: "trade"}, 0)],
    ids=["last-grant", "partial-removal"],
)
async def test_removal_needs_the_acknowledgement_while_a_count_is_unknown(
    rows: Any, grants: dict[Any, Any], positions: int | None
) -> None:
    """AC7, #2648 Q2: every removal of a live grant, not only the last, and even with the
    position count read (0): no open-order count exists yet, so one is always unknown."""
    w = _World(st._Rel(rows=rows), positions=positions)
    with pytest.raises(AccessPositionsUnknownError):
        await w.service.replace(TARGET, grants, **_BY_CALLER)
    await w.service.drain()
    assert w.unchanged()
    await w.service.replace(TARGET, grants, **_ACKNOWLEDGED)
    assert w.rel.committed


async def test_removal_records_leave_and_counts() -> None:
    """O2: the record says positions stay as they are; nothing here flattens or cancels. The
    target's count is read once."""
    w = _World(positions=2)
    await w.service.replace(TARGET, {}, **_ACKNOWLEDGED)
    ((_, record, _, _),) = w.audit.calls
    leave = st._leave(RemovalContext(open_position_count=2, acknowledged_unknown_positions=True))
    assert record["after_state"] == {"grants": []} | leave and leave["open_order_count"] is None
    assert w.positions.asked == [str(TARGET)]


@pytest.mark.parametrize(
    ("positions", "error"),
    [(ConnectionError("oms down"), "ConnectionError"), ("hang", "TimeoutError")],
    ids=["error", "hang"],
)
async def test_count_provider_failure_is_unknown_not_zero(positions: object, error: str) -> None:
    """AC7: a count that failed or did not answer in time is unknown, and the log names the
    error class only."""
    w = _World(positions=positions, count_timeout_s=0)
    with structlog.testing.capture_logs() as logs:
        async with asyncio.timeout(st._WAIT_S):  # ends a regression's hang
            await w.service.replace(TARGET, {}, **_ACKNOWLEDGED)
    assert w.audit.calls[0][1]["after_state"]["open_position_count"] is None
    unread = [e["error"] for e in logs if e["event"] == "account access positions unreadable"]
    assert unread == [error]


async def test_open_position_count_is_bounded_at_two_seconds_unless_told_otherwise() -> None:
    """AC7: a count read is given `COUNT_TIMEOUT_S`, 2 s, and is unknown after it. The loop's
    timer is the fake clock, as for the push's wait: the count's `asyncio.timeout` is the first of
    the call and fires at once, and the delay it was asked for is what is pinned (30 s there would
    let a position source that never answers hold the PUT)."""
    w = _World(positions="hang")
    async with asyncio.timeout(st._WAIT_S):  # ends a regression's hang
        with _fake_clock("call_at", first_only=True) as asked:
            await w.service.replace(TARGET, {}, **_ACKNOWLEDGED)
    assert asked[0] == pytest.approx(COUNT_TIMEOUT_S, abs=0.1) and COUNT_TIMEOUT_S == 2.0
    assert w.audit.calls[0][1]["after_state"]["open_position_count"] is None


_BUSY = DBAPIError("SELECT", None, st._DriverError("55P03"))


@pytest.mark.parametrize(
    ("rel", "audit_error", "refusal"),
    [
        ({"unknown": frozenset({_C})}, None, AccessUnknownAccountError),
        ({"status": None}, None, AccessUserNotFoundError),
        ({"status": "locked"}, None, AccessUserNotActiveError),
        ({"fail_on": m._LOCK_USER, "error": _BUSY}, None, AccessBusyError),
        ({}, RuntimeError("audit WAL unavailable"), AccessAuditUnavailableError),
    ],
    ids=["unknown-account", "missing-user", "not-active", "lock-wait", "audit-unavailable"],
)
async def test_a_refusal_changes_nothing_and_pushes_nothing(
    rel: dict[str, Any], audit_error: Exception | None, refusal: type[Exception]
) -> None:
    """Nothing changed, so the sockets are left alone: not even a push to re-evaluate them."""
    w = _World(st._Rel(rows=_HELD_A, **rel), audit_error=audit_error)
    with pytest.raises(refusal):
        await w.service.replace(TARGET, {_A: "read", _C: "trade"}, **_ACKNOWLEDGED)
    await w.service.drain()  # a push the refusal started would end here
    assert not w.rel.committed and not w.notifier.entered.is_set()


async def test_self_target_is_refused_before_any_statement_and_pushes_nothing() -> None:
    """SR-055's backstop in the store: the caller's own grants. Nothing changed, so no push."""
    w = _World()
    with pytest.raises(AccessSelfTargetError):
        await w.service.replace(CALLER, {_B: "trade"}, **_ACKNOWLEDGED)
    await w.service.drain()
    assert w.rel.log == [] and not w.notifier.entered.is_set() and w.unchanged()


@pytest.mark.parametrize(
    ("rel", "raised"),
    [
        (
            {"fail_on": m._LOCK_USER, "error": DBAPIError("S", None, st._DriverError("57P01"))},
            StorageQueryFailed,
        ),
        ({"on_close": DBAPIError("CLOSE", None, st._DriverError("08006"))}, StorageQueryFailed),
        ({"fail_on": m._LOCK_USER, "error": ConnectionRefusedError("database down")}, OSError),
        ({"on_close": InvalidRequestError("session already closed")}, InvalidRequestError),
    ],
    ids=["driver-error", "close-fails-after-the-commit", "database-down", "session-error-on-close"],
)
async def test_store_failure_pushes_and_still_raises(
    rel: dict[str, Any], raised: type[Exception]
) -> None:
    """UL2-I1: a failure may follow a commit that landed (the second and the fourth did), so the
    live sockets are re-evaluated all the same: a revoked manager must not keep the wider
    principal. Whatever the failure is, bar a refusal, and it still reaches the caller; the
    session error is none the store maps, as the driver's are."""
    w = _World(st._Rel(rows=_HELD_A, **rel))
    with pytest.raises(raised):
        await w.service.replace(TARGET, {_A: "trade"}, **_BY_CALLER)
    async with asyncio.timeout(st._WAIT_S):
        await w.service.drain()
    assert w.notifier.pushes == [(TARGET, w.rel.committed)]


async def test_cancel_during_the_store_call_pushes_and_still_cancels() -> None:
    """UL2-I1: a call cut off inside the commit may have landed it. The sockets are re-evaluated
    (the commit is not known to have happened) and the cancellation still reaches the caller."""
    entered = asyncio.Event()

    async def stuck_commit() -> None:
        entered.set()
        await asyncio.Event().wait()

    w = _World(st._Rel(rows=_HELD_A, on_commit=stuck_commit))
    call = asyncio.create_task(w.service.replace(TARGET, {_A: "trade"}, **_BY_CALLER))
    async with asyncio.timeout(st._WAIT_S):
        await entered.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    async with asyncio.timeout(st._WAIT_S):
        await w.service.drain()
    assert w.notifier.pushes == [(TARGET, False)]


async def test_push_failure_is_counted_and_logged_not_rolled_back() -> None:
    """R7: committed and answered; an error line and one `failed` count. The outer bound ends a
    regression's hang."""
    w, failed = _World(push_error=ConnectionResetError("socket gone")), _counted("failed")
    with structlog.testing.capture_logs() as logs:
        async with asyncio.timeout(st._WAIT_S):
            change = await w.service.replace(TARGET, {_A: "read", _B: "trade"}, **_BY_CALLER)
    assert change.changed and w.rel.committed and not w.notifier.pushes
    assert _push_lines(logs) == [("failed", "error")] and _counted("failed") == failed + 1


async def test_push_outliving_the_wait_is_never_cut_short() -> None:
    """AC3 missed: the request answers after its wait and logs it; the push goes on to the end,
    and `drain` waits for it. Cancelled instead, it could leave the sockets on the old grants."""
    w = _World(push_wait_s=0.0)
    w.notifier.gate.clear()  # the push outlives the request's wait
    timed_out, pushed = _counted("timeout"), _counted("pushed")
    with structlog.testing.capture_logs() as logs:
        async with asyncio.timeout(st._WAIT_S):
            change = await w.service.replace(TARGET, {_A: "read", _B: "trade"}, **_BY_CALLER)
        assert change.changed and w.rel.committed and not w.notifier.pushes
        w.notifier.gate.set()
        async with asyncio.timeout(st._WAIT_S):
            await w.service.drain()
    assert w.notifier.pushes == [(TARGET, True)]
    assert _push_lines(logs) == [("timeout", "warning"), ("pushed", "info")]
    assert (_counted("timeout"), _counted("pushed")) == (timed_out + 1, pushed + 1)  # twice


async def test_push_survives_handler_cancellation() -> None:
    """A caller cancelled after the commit cannot cut the push short; `drain` waits for it."""
    w = _World()
    w.notifier.gate.clear()
    call = asyncio.create_task(w.service.replace(TARGET, {_A: "read", _B: "trade"}, **_BY_CALLER))
    async with asyncio.timeout(st._WAIT_S):
        await w.notifier.entered.wait()
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    w.notifier.gate.set()
    async with asyncio.timeout(st._WAIT_S):
        await w.service.drain()
    assert w.notifier.pushes == [(TARGET, True)]


async def test_request_waits_two_seconds_for_the_push() -> None:
    """AC3: unless told otherwise the request waits `PUSH_WAIT_S`, 2 s, for the push. The loop's
    timer is the fake clock: it fires at once, so no wall-clock wait, and the delay it was asked
    for is what is pinned (30 s there would let a stuck push hold the request)."""
    w = _World()
    w.notifier.gate.clear()  # the push outlives the request's wait
    async with asyncio.timeout(st._WAIT_S):
        with _fake_clock("call_later") as asked:
            await w.service.replace(TARGET, {_A: "read", _B: "trade"}, **_BY_CALLER)
    assert asked == [PUSH_WAIT_S] == [2.0]
    w.notifier.gate.set()
    async with asyncio.timeout(st._WAIT_S):
        assert await w.service.drain() == 0


async def test_drain_gives_up_on_a_push_that_never_ends_and_reports_it() -> None:
    """C-2.18: a push that does not end must not hold the shutdown. `drain` waits `DRAIN_TIMEOUT_S`,
    5 s (the loop's timer is the fake clock, so no wall-clock wait), then logs and returns how
    many pushes are still running. It cuts none short: the push goes on to its end, and the next
    drain finds it done and says nothing."""
    w = _World(push_wait_s=0.0)
    w.notifier.gate.clear()  # the push never ends, as far as the shutdown can tell
    with structlog.testing.capture_logs() as logs:
        async with asyncio.timeout(st._WAIT_S):  # ends a regression's hang
            await w.service.replace(TARGET, {_A: "read", _B: "trade"}, **_BY_CALLER)
            with _fake_clock("call_later") as asked:
                left = await w.service.drain()
            assert (left, asked) == (1, [DRAIN_TIMEOUT_S]) and DRAIN_TIMEOUT_S == 5.0
            assert not w.notifier.pushes
            w.notifier.gate.set()
            assert await w.service.drain() == 0
    assert w.notifier.pushes == [(TARGET, True)]
    event = "account access pushes still in flight at shutdown"
    assert [(e["pushes"], e["log_level"]) for e in logs if e["event"] == event] == [(1, "warning")]


class _GrantsHungUntilTold(ld._Grants):
    """While `hang` is set a load waits for `give_up`, then fails as a store that timed out
    would: the test, not a clock, ends the hang. The loader's own bound is pinned in
    tests/unit/ws/test_store_principal_loader.py."""

    def __init__(self) -> None:
        super().__init__()
        self.give_up = asyncio.Event()

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        if self.hang:
            await self.give_up.wait()
            raise TimeoutError("the grants store gave up")
        return await super().load_grants(owner)


async def test_hung_principal_load_outlasting_the_wait_still_revokes() -> None:
    """Security review (C-12.4): the request stops waiting while the WS principal load is still
    hung on its grants store. The push is not cut short, so once the load fails it ends in the
    deny-all snapshot (a failed load never raises) and the subscription on the removed account
    ends with `revoked` (`permission_revoked`: the deny-all snapshot holds no permission either).
    The store gives up when the test says so, so the order of events does not depend on a clock."""
    identity, grants = ld._Identity(), _GrantsHungUntilTold()
    grants.rows = [(_A, True, False)]
    registry = ConnectionRegistry(
        StorePrincipalLoader(identity, grants),
        lambda: 42,
        SubscriptionServices(upstream=UpstreamRefs(ld._NoUpstream())),
    )
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    snap = await registry.resolve(TARGET)
    conn = ConnectionAuthz(snap.principal, registry.services, version=snap.version)
    registry.register(conn, send)
    sub = {"ch": "orders", "opts": {"exchange_account_ids": [str(_A)]}}
    await handle_sub(conn, {"t": "sub", "id": "s", "p": {"topics": [sub]}}, send)
    grants.hang = True  # every load from now on, the push's too
    rel = st._Rel(rows=_HELD_A)
    store = m.SqlAlchemyAccountAccessStore(cast(Any, rel), audit=st._Audit(rel))
    events = WsEvents(registry, cast(Any, None), KillSwitchView())  # the hub: kill switch only
    service = AccountAccessService(store, events, positions=_Positions(0), push_wait_s=0.0)
    with structlog.testing.capture_logs() as logs:
        async with asyncio.timeout(st._WAIT_S):
            await service.replace(TARGET, {}, **_ACKNOWLEDGED)  # no order count yet
        assert rel.committed and [f["t"] for f in sent] == ["sub_ok"]  # answered; the load hangs
        grants.give_up.set()
        async with asyncio.timeout(st._WAIT_S):
            await service.drain()
    assert [f["t"] for f in sent] == ["sub_ok", "permission_change", "revoked"]
    assert sent[-1]["p"]["reason"] == "permission_revoked" and conn.topics == set()
    assert _push_lines(logs) == [("timeout", "warning"), ("pushed", "info")]
