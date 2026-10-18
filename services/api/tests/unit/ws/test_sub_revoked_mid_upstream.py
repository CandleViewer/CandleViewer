"""#2896: a §9.5 change (or the socket's end) that ends a subscription before its `sub_ok` is
queued, in its own `subscribe_upstream` (event-gated here) or a later await of the frame, leaves
`permission_change`, `revoked`, then its refused result, never `ok: true`, counted as refused. What
it took after the end is released on a return, a raise or a cancellation; it gets no `snap`, grant
or denial record (the change writes `ws.subscription.revoked`), and ended in its own await it draws
nothing. The change runs through the real registry; the fake bar service counts its holds and
leases, and the upstream refs are real."""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import Awaitable
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.bars.errors import BarsError
from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import Hold
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    Subscription,
    SubscriptionServices,
    cv_ws_subscribe_total,
    handle_sub,
)
from candleviewer.ws.topics import EntityScope
from candleviewer.ws.upstream import UpstreamRefs
from tests.unit.ws._seq_support import ACC_A, ACC_B, PERMS, USER, Book, Conn, Source, principal

BARS, BOOK = "bars.BTCUSDT.time.5", "book.BTCUSDT.50"
#: A §6.4 entity on account A (`_Machines`), and a replay session (§11).
ORDER, RS = f"machines.order:{uuid.UUID(int=0xD)}.state", str(uuid.UUID(int=0x5E))
#: What the operator's change leaves the user: `marketdata:read` revoked, or account A removed.
NO_MD = dataclasses.replace(
    principal(ACC_A, ACC_B), permissions=PERMS - {Permission.MARKETDATA_READ}
)
NO_A = principal(ACC_B)
POSITIONS_A = {"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A)]}}
#: §10.2: one fixed message per refusal code (`permissions._REFUSED`); neither is retryable.
_MESSAGES = {
    "forbidden": "Missing permission for this topic.",
    "account_scope_denied": "None of the requested accounts are in scope.",
}


def _refused(ch: str, code: str) -> dict[str, Any]:
    """A refused `sub_ok` result (§5.2): its code, and no `sub_id`."""
    error = {"code": code, "message": _MESSAGES[code], "retryable": False}
    return {"ch": ch, "ok": False, "error": error}


class _Bars:
    """The bar service (`SeriesHolds` and `BarLeases`): what it gave, and how much is held."""

    def __init__(self) -> None:
        self.holds = self.leases = 0
        self.taken: list[str] = []
        self.lost = False

    def lose(self) -> None:
        """#2735: another connection's failed `register` dropped the series' leases."""
        self.leases, self.lost = 0, True

    async def ensure(self, symbol: str, spec: BarSpec) -> Hold:
        self.holds += 1
        self.taken.append("hold")
        return Hold(symbol, spec.spec_hash, self._unhold, lambda: None)

    def _unhold(self, grace: bool) -> None:
        self.holds -= 1

    def check(self, spec: BarSpec, symbol: str, user: str | None = None) -> None: ...

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        self.leases += 1
        self.taken.append("lease")

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        if self.lost:  # as `SpecLeases.release` refuses a lease it does not hold
            raise BarsError(f"The consumer {consumer} holds no lease on that bar series.")
        self.leases -= 1


class _Machines:
    """The §6.4 registry: `ORDER`'s entry, scoped to account A."""

    def scope(self, ch: str) -> EntityScope | None:
        return EntityScope(accounts=frozenset({ACC_A})) if ch == ORDER else None


class _Sink:
    """The exchange side of the upstream refs: an open raises `fail`, and a `gate` family's waits
    for `go`."""

    def __init__(self) -> None:
        self.opened: list[Any] = []
        self.gate, self.entered, self.go = "", asyncio.Event(), asyncio.Event()
        self.fail: Exception | None = None

    async def open(self, key: Any) -> None:
        self.opened.append(key)
        if self.fail is not None:
            raise self.fail
        if key[1] == self.gate:
            self.entered.set()
            await self.go.wait()

    async def drop(self, key: Any) -> None: ...


class _Audit:
    """The audit sink: (action, object) per row; with `hold`, the denial record waits for it."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, Any]] = []
        self.hold: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def emit(self, action: str, **row: Any) -> None:
        if action == "ws.subscribe.denied" and self.hold is not None:
            self.entered.set()
            await self.hold.wait()
        self.rows.append((action, row["object_id"]))


class _World(Conn):
    """USER's connection (`Conn`: its emitter sends the `snap`s the gateway flushes after
    `handle_sub`) on a real registry, whose `revoke` is the operator's change."""

    def __init__(self) -> None:
        self.principal = principal(ACC_A, ACC_B)
        self.sink, self.bars, self.audit = _Sink(), _Bars(), _Audit()
        source, book = Source(), Book("BTCUSDT")
        book.apply([["100.0", "1.000"]], [["101.0", "2.000"]])
        source.books["BTCUSDT"] = book
        self.refs = UpstreamRefs(self.sink)
        services = SubscriptionServices(
            upstream=self.refs, bars=self.bars, series=self.bars, audit=self.audit, snapshots=source
        )
        services.machines = _Machines()
        super().__init__(source, ACC_A, ACC_B, services=services)
        self.registry = ConnectionRegistry(self._resolve, lambda: 9, services)
        self.registry.register(self.authz, self._send)
        self.counts = _counts()

    async def _resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        return self.principal

    async def _send(self, frame: dict[str, Any]) -> None:
        self.push(frame)

    def subscribe(self, *topics: Any, **p: Any) -> asyncio.Task[None]:
        frame = {"t": "sub", "id": "s", "p": {"topics": list(topics), **p}}
        return asyncio.create_task(handle_sub(self.authz, frame, self._send, now_ms=9))

    async def revoke(self, principal: PrincipalSnapshot) -> None:
        self.principal = principal
        await self.registry.roles_changed(USER)

    async def answered(self, task: asyncio.Task[None]) -> list[tuple[str, str | None]]:
        """`task` done and the gateway's flush after it (its `snap`s); (`t`, `ch`) of each frame."""
        await _within(task)
        self.emitter.flush_pending(list(self.authz.by_id.values()))
        return [(f["t"], f.get("ch")) for f in self.out]

    def held(self) -> tuple[int, int, int]:
        """The series holds, bar leases and upstream refs held now."""
        return self.bars.holds, self.bars.leases, sum(map(self.refs.consumers, self.refs.active()))

    def counted(self) -> dict[tuple[str, str], float]:
        """What `cv_ws_subscribe_total` counted since this world was made, by (family, result)."""
        before = self.counts
        return {k: n - before.get(k, 0) for k, n in _counts().items() if n != before.get(k, 0)}


def _counts() -> dict[tuple[str, str], float]:
    samples = [s for m in cv_ws_subscribe_total.collect() for s in m.samples]
    totals = [s for s in samples if s.name.endswith("_total")]
    return {(s.labels["topic"], s.labels["result"]): s.value for s in totals}


async def _within(aw: Awaitable[Any]) -> None:
    async with asyncio.timeout(5):
        await aw


def _gate(
    monkeypatch: pytest.MonkeyPatch, authz: ConnectionAuthz, ch: str
) -> tuple[asyncio.Event, asyncio.Event]:
    """`ch`'s `subscribe_upstream` waits, before it takes anything, until `go` is set."""
    entered, go, real = asyncio.Event(), asyncio.Event(), authz.subscribe_upstream

    async def gated(sub: Subscription) -> dict[str, Any] | None:
        if sub.ch == ch:
            entered.set()
            await go.wait()
        return await real(sub)

    monkeypatch.setattr(authz, "subscribe_upstream", gated)
    return entered, go


#: case -> (the `sub` entry, the change, the refusal code, what it takes from the bar service,
#: upstream refs opened). "bars-in-open" waits mid-way, in its upstream open: the change frees the
#: hold and the lease taken before it, the fix the upstream ref taken after it.
_CASES: dict[str, tuple[Any, PrincipalSnapshot, str, list[str], int]] = {
    "bars": (BARS, NO_MD, "forbidden", ["hold", "lease"], 1),
    "trades": ("trades.BTCUSDT", NO_MD, "forbidden", [], 1),
    "positions": (POSITIONS_A, NO_A, "account_scope_denied", [], 0),
    "bars-in-open": (BARS, NO_MD, "forbidden", ["hold", "lease"], 1),
}


@pytest.mark.parametrize("case", list(_CASES))
async def test_a_topic_revoked_in_its_subscribe_upstream_is_refused_after_revoked_holding_nothing(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _World()
    entry, after, code, taken, opened = _CASES[case]
    ch = entry if isinstance(entry, str) else entry["ch"]
    if case == "bars-in-open":
        w.sink.gate, entered, go = "bars", w.sink.entered, w.sink.go
    else:
        entered, go = _gate(monkeypatch, w.authz, ch)
    task = w.subscribe(entry)
    await _within(entered.wait())
    await w.revoke(after)
    go.set()
    told = [("permission_change", None), ("revoked", ch), ("sub_ok", None)]
    assert await w.answered(task) == told  # and no `snap`
    assert (w.out[1]["p"]["sub_id"], w.out[2]["p"]["results"]) == ("s_01", [_refused(ch, code)])
    assert (w.bars.taken, len(w.sink.opened)) == (taken, opened)  # taken, then released
    assert (w.held(), w.authz.by_id) == ((0, 0, 0), {})
    users = w.authz.services.user_rebuilds  # no draw on the connection's budget or the user's
    assert (len(w.authz.rebuilds._all), users._stamps, users._held) == (0, {}, {})
    assert w.audit.rows == [("ws.subscription.revoked", ch[:40])]  # no grant, no denial
    assert w.counted() == {(ch.partition(".")[0], code): 1}  # its reply's result, once


@pytest.mark.parametrize("entry", [POSITIONS_A, ORDER], ids=["positions", "machines"])
async def test_a_topic_ended_in_a_later_topics_await_is_refused_and_the_other_kept(
    entry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A private topic never waits in its own `subscribe_upstream`: its account goes while the next
    topic waits in its (a `machines` one gets its kind's code, §6.4). That unrevoked `book` is
    answered as before, and its `snap` follows."""
    w = _World()
    ch = entry if isinstance(entry, str) else entry["ch"]
    entered, go = _gate(monkeypatch, w.authz, BOOK)
    task = w.subscribe(entry, {"ch": BOOK, "opts": {"encoding": "structured"}})
    await _within(entered.wait())
    await w.revoke(NO_A)
    go.set()
    told = [("permission_change", None), ("revoked", ch), ("sub_ok", None)]
    assert await w.answered(task) == [*told, ("snap", BOOK)]
    refused, kept = w.out[2]["p"]["results"]
    assert refused == _refused(ch, "account_scope_denied")
    assert (kept["ok"], kept["sub_id"], list(w.authz.by_id)) == (True, "s_02", ["s_02"])
    assert (w.out[3]["s"], w.out[3]["meta"]["reason"]) == (1, "initial")
    assert w.audit.rows == [("ws.subscription.revoked", ch)]
    family = ch.partition(".")[0]  # counted as the reply answers it, never `ok`
    assert w.counted() == {(family, "account_scope_denied"): 1, ("book", "ok"): 1}


async def test_a_topic_ended_while_the_denial_record_is_written_is_refused_too() -> None:
    w = _World()
    w.audit.hold = go = asyncio.Event()
    orders = {"ch": "orders", "opts": {"exchange_account_ids": [str(uuid.UUID(int=0xC))]}}
    task = w.subscribe(orders, POSITIONS_A)  # `orders` on an ungranted account: refused, audited
    await _within(w.audit.entered.wait())
    await w.revoke(NO_A)
    go.set()
    told = [("permission_change", None), ("revoked", "positions"), ("sub_ok", None)]
    assert await w.answered(task) == told
    refusals = [_refused(ch, "account_scope_denied") for ch in ("orders", "positions")]
    assert w.out[2]["p"]["results"] == refusals
    revoked, denied = ("ws.subscription.revoked", "positions"), ("ws.subscribe.denied", "orders")
    assert w.audit.rows == [revoked, denied]  # the record lists `admit`'s refusal only
    assert w.counted() == {(ch, "account_scope_denied"): 1 for ch in ("orders", "positions")}


@pytest.mark.parametrize("fault", [RuntimeError, asyncio.CancelledError])
async def test_a_raise_or_cancellation_after_the_change_still_releases_what_was_taken(
    fault: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the change it takes its hold and lease, then its upstream open fails or it is cancelled
    there; its socket then ends (1011, or a cancelled handler), and that teardown's `release_all`
    cannot see a subscription the change already ended. With no reply, nothing is counted, not
    even `positions`, accepted before the fault (§6.2)."""
    w = _World()
    entered, go = _gate(monkeypatch, w.authz, BARS)
    task = w.subscribe(POSITIONS_A, BARS)
    await _within(entered.wait())
    await w.revoke(NO_MD)
    if fault is RuntimeError:
        w.sink.fail = RuntimeError("down")  # no refusal `_upstream` maps: it propagates
    else:
        w.sink.gate = "bars"
    go.set()
    if fault is asyncio.CancelledError:
        await _within(w.sink.entered.wait())
        task.cancel()
    with pytest.raises(fault):
        await _within(task)
    assert (w.bars.taken, w.held()) == (["hold", "lease"], (0, 0, 0))
    assert [f["t"] for f in w.out] == ["permission_change", "revoked"]
    assert w.counted() == {}


async def test_a_topic_narrowed_in_its_subscribe_upstream_is_answered_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Still the one registered (§9.5: a narrowing continues in place): `ok: true`, kept account."""
    w = _World()
    entered, go = _gate(monkeypatch, w.authz, "positions")
    accounts = [str(ACC_A), str(ACC_B)]
    task = w.subscribe({"ch": "positions", "opts": {"exchange_account_ids": accounts}})
    await _within(entered.wait())
    await w.revoke(principal(ACC_A))
    go.set()
    await _within(task)
    (result,) = w.out[2]["p"]["results"]
    kept = result["effective"]["exchange_account_ids"]
    assert w.out[1]["p"]["resubscribe_allowed"] is True
    assert (result["ok"], result["sub_id"], kept) == (True, "s_01", [str(ACC_A)])


#: How `bars` ends while it waits, and the frames before its `sub_ok`: the socket's end
#: (`release_all`, as an eviction or a disable ends it), or a revocation a later change undoes.
_ENDINGS: dict[str, list[tuple[str, str | None]]] = {
    "socket-end": [],
    "given-back": [("permission_change", None), ("revoked", BARS), ("permission_change", None)],
}


@pytest.mark.parametrize("ending", list(_ENDINGS))
async def test_a_topic_nothing_refuses_after_its_end_is_still_refused(
    ending: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ended_result`'s fallback: `forbidden`, never `ok: true`. What it took after its end is
    released, and it draws nothing (on the base the socket's end left (1, 1, 1) held)."""
    w = _World()
    entered, go = _gate(monkeypatch, w.authz, BARS)
    task = w.subscribe(BARS)
    await _within(entered.wait())
    if ending == "socket-end":
        w.registry.unregister(w.authz)
    else:
        await w.revoke(NO_MD)
        await w.revoke(principal(ACC_A, ACC_B))
    go.set()
    assert await w.answered(task) == [*_ENDINGS[ending], ("sub_ok", None)]
    assert w.out[-1]["p"]["results"] == [_refused(BARS, "forbidden")]
    assert (w.bars.taken, w.held(), len(w.authz.rebuilds._all)) == (["hold", "lease"], (0, 0, 0), 0)


@pytest.mark.parametrize("cancel", [False, True], ids=["return", "cancel"])
async def test_a_release_that_raises_is_logged_and_neither_reply_nor_raise_changes(
    cancel: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2735: the series loses its leases while `bars` waits in its upstream open, after the change,
    so releasing its lease raises: one error line, the rest released, and the refusal (no draw) or
    the cancellation goes out as it would without that raise."""
    w = _World()
    entered, go = _gate(monkeypatch, w.authz, BARS)
    task = w.subscribe(BARS)
    await _within(entered.wait())
    await w.revoke(NO_MD)
    w.sink.gate = "bars"
    go.set()
    await _within(w.sink.entered.wait())  # its hold and lease are taken; its upstream open waits
    w.bars.lose()
    with capture_logs() as logs:
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await _within(task)
        else:
            w.sink.go.set()
            told = [("permission_change", None), ("revoked", BARS), ("sub_ok", None)]
            assert await w.answered(task) == told
            assert w.out[2]["p"]["results"] == [_refused(BARS, "forbidden")]
    failed = [(e["event"], e["consumer"]) for e in logs if e["log_level"] == "error"]
    assert failed == [("ws subscription release failed", f"{w.authz.connection_id}/s_01")]
    assert (w.held(), len(w.authz.rebuilds._all)) == ((0, 0, 0), 0)


async def test_a_replay_topic_ended_while_the_denial_record_is_written_keeps_its_rs() -> None:
    """§5.2: each result of a replay `sub` carries `rs`, refused ones too. `positions` cannot be
    replayed (refused, and kept in the record); `marketdata:read` goes while that is written."""
    w = _World()
    w.audit.hold = go = asyncio.Event()
    task = w.subscribe("positions", "trades.BTCUSDT", replay_session_id=RS)
    await _within(w.audit.entered.wait())
    await w.revoke(NO_MD)
    go.set()
    told = [("permission_change", None), ("revoked", "trades.BTCUSDT"), ("sub_ok", None)]
    assert await w.answered(task) == told
    private, refused = w.out[2]["p"]["results"]
    assert (private["error"]["code"], private["rs"], w.out[1]["rs"]) == ("invalid_options", RS, RS)
    assert refused == {**_refused("trades.BTCUSDT", "forbidden"), "rs": RS}
