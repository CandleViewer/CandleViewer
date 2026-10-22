"""Fair scheduling between WS connections and constant-time subscription cap checks (#415).

The reader yields after each frame it handles and `handle_sub` after every `SUB_ENTRIES_PER_STEP`
entries; `ConnectionAuthz.held_symbols` always equals its recount from `by_id`, whatever the hold
and release paths; at 200 subscriptions a new topic is refused before it is parsed or authorised,
and each cap refusal keeps its code, message, `field`, metric and audit row. Fakes only: no sleeps,
no network."""

from __future__ import annotations

import asyncio
import collections
import json
import math
import uuid
from collections.abc import Callable, Coroutine, Generator
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.observability.context import spawn
from candleviewer.ws import permissions
from candleviewer.ws.limits import MAX_SYMBOLS_PER_CONNECTION
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    cv_ws_subscribe_total,
    handle_ctl,
    handle_unsub,
)
from candleviewer.ws.topics import parse_topic
from candleviewer.ws.upstream import UpstreamKey, UpstreamRefs
from tests.unit.ws._auth_rig import Rig, Sock, hang_up

USER = uuid.UUID(int=0x415)
A = uuid.UUID(int=0xA)
B = uuid.UUID(int=0xB)
MARKET, ORDERS = Permission.MARKETDATA_READ, Permission.ORDERS_READ
POSITIONS = Permission.POSITIONS_READ
EVERY = frozenset({MARKET, ORDERS, POSITIONS})
SYMBOLS = [f"S{i:02d}USDT" for i in range(90)]
#: 40 subscriptions, one per symbol: a connection at the 40-symbol cap.
FORTY = [f"trades.{s}" for s in SYMBOLS[:40]]
OVER = [f"trades.{s}" for s in SYMBOLS[40:90]]  # 50 topics, each past the 40-symbol cap
#: 200 subscriptions on one symbol: a connection at the 200-subscription cap. `footprint` takes no
#: bar service here (none is wired), as in the other cap tests.
TWO_HUNDRED = [f"footprint.BTCUSDT.tick.{n}" for n in range(1, 201)]


def _principal(
    perms: frozenset[Permission] = EVERY, accounts: tuple[uuid.UUID, ...] = (A, B)
) -> PrincipalSnapshot:
    grants = tuple(AccountGrant(a, True, False, False) for a in accounts)
    return PrincipalSnapshot(USER, frozenset({"manager"}), perms, grants)


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


def _authz(audit: _Audit | None = None) -> ConnectionAuthz:
    return ConnectionAuthz(_principal(), SubscriptionServices(upstream=UpstreamRefs(), audit=audit))


async def _sub(authz: ConnectionAuthz, *entries: Any) -> list[dict[str, Any]]:
    """One `sub` frame of `entries`; its results, in order."""
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    await permissions.handle_sub(authz, {"t": "sub", "id": "s", "p": {"topics": [*entries]}}, send)
    (reply,) = sent
    results: list[dict[str, Any]] = reply["p"]["results"]
    return results


async def _hold(authz: ConnectionAuthz, topics: list[str]) -> None:
    for i in range(0, len(topics), 50):
        assert all(r["ok"] for r in await _sub(authz, *topics[i : i + 50]))


def _orders(*accounts: uuid.UUID, symbols: tuple[str, ...] = (), ch: str = "orders") -> Any:
    """An `orders` (or `positions`) entry on `accounts`, filtered to `symbols` when given."""
    opts: dict[str, Any] = {"exchange_account_ids": [str(a) for a in accounts]}
    return {"ch": ch, "opts": opts | ({"symbols": [*symbols]} if symbols else {})}


def _recount(authz: ConnectionAuthz) -> dict[str, int]:
    """The multiset made again from the live subscriptions."""
    return dict(collections.Counter(s for sub in authz.by_id.values() for s in sub.symbols))


def _counts() -> dict[tuple[str, str], float]:
    samples = [s for m in cv_ws_subscribe_total.collect() for s in m.samples if "_total" in s.name]
    return {(s.labels["topic"], s.labels["result"]): s.value for s in samples}


# -- fair scheduling --------------------------------------------------------------------------


class _Logged(Sock):
    """Logs each send in a log the sockets share, with how many frames `first` still has queued."""

    def __init__(self, name: str, log: list[tuple[str, dict[str, Any], int]]) -> None:
        super().__init__()
        self.name, self.log = name, log
        self.first: Sock = self

    async def send_text(self, text: str) -> None:
        await super().send_text(text)
        self.log.append((self.name, json.loads(text), self.first.inbound.qsize()))


async def test_a_pong_is_written_while_another_connection_still_has_frames_queued() -> None:
    """A has 20 `sub` frames queued, each refused by the 40-symbol cap, and B one `ping` queued
    after them: B's `pong` is written while A still has frames queued, and A's replies keep A's
    order."""
    rig, log = Rig(), list[tuple[str, dict[str, Any], int]]()
    a, b = _Logged("a", log), _Logged("b", log)
    b.first = a
    handlers = [await rig.open(a), await rig.open(b)]
    assert [(await rig.auth(s, f"good-{n}"))["t"] for n, s in enumerate((a, b))] == ["auth_ok"] * 2
    a.feed({"t": "sub", "id": "fill", "p": {"topics": FORTY}})
    assert all(r["ok"] for r in (await a.sent.get())["p"]["results"])
    log.clear()
    for i in range(20):
        a.feed({"t": "sub", "id": f"x{i}", "p": {"topics": [f"trades.{SYMBOLS[40 + i]}"]}})
    b.feed({"t": "ping", "id": "p"})
    replies = [await a.sent.get() for _ in range(20)]
    assert (await b.sent.get())["t"] == "pong"
    ((at, (_, pong, queued)),) = [(i, e) for i, e in enumerate(log) if e[0] == "b"]
    assert pong["t"] == "pong" and queued > 0  # A's queue was not drained first
    assert at < len(log) - 1  # written before A's last reply
    assert [f["id"] for f in replies] == [f"x{i}" for i in range(20)]  # each connection's order
    assert {r["p"]["results"][0]["error"]["code"] for r in replies} == {"subscription_limit"}
    for sock, handler in zip((a, b), handlers, strict=True):
        hang_up(sock)
        await handler


class _Turns:
    """Awaits a coroutine and calls `on_turn` at each bare yield it hands the loop (one step)."""

    def __init__(self, coro: Coroutine[Any, Any, Any], on_turn: Callable[[], None]) -> None:
        self.coro, self.on_turn = coro, on_turn

    def __await__(self) -> Generator[Any, None, Any]:
        steps = self.coro.__await__()
        while True:
            try:
                handed = steps.send(None)
            except StopIteration as stop:
                return stop.value
            if handed is None:
                self.on_turn()
            yield handed


@pytest.mark.parametrize("held", [FORTY, []], ids=["refused-at-the-40-symbol-cap", "accepted"])
async def test_one_50_entry_sub_reads_at_most_n_entries_per_task_step(
    held: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One `sub` of 50 entries yields at least ceil(50/N) - 1 times, and no step reads more than N
    entries, N = `SUB_ENTRIES_PER_STEP`: refused at the cap or accepted."""
    n = permissions.SUB_ENTRIES_PER_STEP
    authz = _authz()
    await _hold(authz, held)
    entries = OVER if held else FORTY + [f"book.{s}.50" for s in SYMBOLS[:10]]
    per_step = [0]
    admit = authz.admit

    def counted(*args: Any, **kwargs: Any) -> Any:
        per_step[-1] += 1
        return admit(*args, **kwargs)

    monkeypatch.setattr(authz, "admit", counted)
    results = await _Turns(_sub(authz, *entries), lambda: per_step.append(0))
    assert len(per_step) - 1 >= math.ceil(len(entries) / n) - 1  # the yields
    assert max(per_step) <= n and sum(per_step) == len(entries) == 50
    assert [r["ok"] for r in results] == [not held] * 50


def test_a_sub_step_reads_at_most_ten_entries() -> None:
    """The test above reads N from the constant, so its ceiling is pinned here (C-2.17)."""
    assert permissions.SUB_ENTRIES_PER_STEP <= 10


# -- the caps ---------------------------------------------------------------------------------


async def test_at_200_subscriptions_an_entry_is_refused_before_it_is_parsed_or_authorised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the cap a new topic, private or not, an entity included, is refused before it is parsed
    or authorised. Entries that add no subscription are answered as below the cap: a topic held
    already is `duplicate_subscription`, and `system` (§6.2) stays attached; an entry with an
    unknown field keeps that refusal."""
    authz = _authz()
    await _hold(authz, TWO_HUNDRED)
    read: list[str] = []

    def spy(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def called(*args: Any, **kwargs: Any) -> Any:
            read.append(name)
            return real(*args, **kwargs)

        return called

    monkeypatch.setattr(permissions, "parse_topic", spy("parse", parse_topic))
    monkeypatch.setattr(authz, "_authorise", spy("authorise", authz._authorise))
    monkeypatch.setattr(authz, "_authorise_entity", spy("entity", authz._authorise_entity))
    new = ["trades.ETHUSDT", _orders(A), "machines.book:ETHUSDT.state"]
    odd = {"ch": "trades.ETHUSDT", "opt": {}}
    results = await _sub(authz, *new, odd, TWO_HUNDRED[0], "system")
    codes = [
        (r["ok"], r.get("error", {}).get("code"), r.get("error", {}).get("field")) for r in results
    ]
    assert codes == [(False, "subscription_limit", None)] * 3 + [
        (False, "invalid_options", "topics"),
        (False, "duplicate_subscription", None),
        (True, None, None),
    ]
    assert read == ["parse", "authorise", "parse"]  # the held topic, then `system`


@pytest.mark.parametrize(
    ("held", "entries", "message"),
    [
        (TWO_HUNDRED, ["trades.ETHUSDT", _orders(A)], "200 subscriptions reached."),
        (
            FORTY,
            [f"trades.{SYMBOLS[40]}", _orders(A, symbols=(SYMBOLS[41],))],
            "40 symbols per connection reached.",
        ),
    ],
    ids=["200-subscription-cap", "40-symbol-cap"],
)
async def test_each_cap_refusal_keeps_its_code_message_field_metric_and_audit_row(
    held: list[str], entries: list[Any], message: str
) -> None:
    """A public and a private topic past a cap: `subscription_limit` with the cap's message and no
    `field`, one count per family, and one `ws.subscribe.denied` row, the private topic's, which
    names its socket (#415, E17-R-16)."""
    audit = _Audit()
    authz = _authz(audit)
    await _hold(authz, held)
    before = _counts()
    results = await _sub(authz, *entries)
    error = {"code": "subscription_limit", "message": message, "retryable": True}
    assert results == [
        {"ch": e if isinstance(e, str) else e["ch"], "ok": False, "error": error} for e in entries
    ]
    counted = {k: n - before.get(k, 0) for k, n in _counts().items() if n != before.get(k, 0)}
    assert counted == {("trades", "subscription_limit"): 1, ("orders", "subscription_limit"): 1}
    assert audit.records == [
        {
            "action": "ws.subscribe.denied",
            "actor_label": "ws",
            "actor_user_id": USER,
            "session_id": None,
            "object_kind": "ws_topic",
            "object_id": "orders",
            "outcome": AuditOutcome.DENIED,
            "severity": Severity.WARNING,
            "reason": "subscription_limit",
            "after_state": {"connection_id": authz.connection_id},
            "request_id": authz.request_id,  # its socket's upgrade id ([AUDIT-REQUEST-ID])
        }
    ]
    assert len(authz.by_id) == len(held)  # nothing subscribed past the cap


async def test_a_subscription_ended_while_it_subscribes_releases_its_symbols_once() -> None:
    """#2896: one ended during its upstream open is dropped then, and again once the open returns:
    its symbol is released once, and another subscription's hold on it stays counted."""
    entered, go = asyncio.Event(), asyncio.Event()

    class _Sink:
        async def open(self, key: UpstreamKey) -> None:
            if key[1] == "trades":
                entered.set()
                await go.wait()

        async def drop(self, key: UpstreamKey) -> None: ...

    authz = ConnectionAuthz(_principal(), SubscriptionServices(upstream=UpstreamRefs(_Sink())))
    await _hold(authz, ["ticker.S00USDT"])
    trades = "trades.S00USDT"
    task = spawn(_sub(authz, trades), name="sub-in-flight")
    await entered.wait()
    sub = authz.find("trades.S00USDT")
    assert sub is not None and authz.held_symbols == {"S00USDT": 2}
    authz.revoke(sub, "resync_rate_limited", 1)
    go.set()
    (result,) = await task
    assert not result["ok"] and authz.held_symbols == _recount(authz) == {"S00USDT": 1}


# -- the held-symbol multiset -----------------------------------------------------------------

_symbol = st.sampled_from(SYMBOLS[:44])  # past the 40-symbol cap
_entry = st.one_of(
    _symbol.map(lambda s: f"trades.{s}"),
    _symbol.map(lambda s: f"book.{s}.50"),
    st.lists(_symbol, min_size=1, max_size=12, unique=True).map(
        lambda ss: {"ch": "ticker", "opts": {"symbols": ss}}
    ),
    st.builds(
        lambda ch, accounts, ss: _orders(*accounts, symbols=tuple(ss), ch=ch),
        st.sampled_from(["orders", "positions"]),
        st.lists(st.sampled_from([A, B]), min_size=1, max_size=2, unique=True),
        st.lists(_symbol, max_size=2, unique=True),
    ),
    _symbol.map(lambda s: f"machines.book:{s}.state"),
    _symbol.map(lambda s: f"bars.{s}.time.1"),  # recorded, then refused: the bar service is off
    st.just("system"),
)
_op = st.one_of(
    st.tuples(st.just("sub"), st.lists(_entry, min_size=1, max_size=12)),
    st.tuples(st.sampled_from(["unsub", "revoke", "ctl"]), st.integers(0, 99)),
    st.tuples(
        st.sampled_from(["grants", "reauth"]),
        st.sets(st.sampled_from([MARKET, ORDERS, POSITIONS])).map(frozenset),
        st.lists(st.sampled_from([A, B]), max_size=2, unique=True).map(tuple),
    ),
)
#: Every path, whatever is drawn: the holds of a `sub` and a refused bar topic's drop, an unsub, a
#: revoke, a ctl, a grant change that narrows `orders` and withdraws `positions`' only account, a
#: re-auth that withdraws market data (`book` and both entities go), then the teardown.
EVERY_PATH: list[tuple[Any, ...]] = [
    (
        "sub",
        [
            "trades.S00USDT",
            {"ch": "ticker", "opts": {"symbols": ["S00USDT", "S01USDT"]}},
            _orders(A, B, symbols=("S02USDT",)),
            _orders(B, symbols=("S03USDT",), ch="positions"),
            "machines.book:S04USDT.state",
            "machines.book:S05USDT.state",
            "bars.S06USDT.time.1",
            "book.S07USDT.50",
        ],
    ),
    ("unsub", 0),
    ("revoke", 0),
    ("ctl", 0),
    ("grants", EVERY, (A,)),
    ("reauth", frozenset({ORDERS}), (A,)),
]


async def _play(ops: list[tuple[Any, ...]]) -> None:
    """`ops` on one registered connection; after each, the multiset equals the recount."""
    principal = [_principal()]

    async def resolve(_user: uuid.UUID) -> PrincipalSnapshot:
        return principal[0]

    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    services = SubscriptionServices(upstream=UpstreamRefs(), clock=lambda: 0.0, bars_off=True)
    registry = ConnectionRegistry(resolve, lambda: 1, services=services)
    authz = ConnectionAuthz(principal[0], services)
    registry.register(authz, send)
    for op in ops:
        live = sorted(authz.by_id.values(), key=lambda s: s.sub_id)
        if op[0] == "sub":
            await permissions.handle_sub(authz, {"t": "sub", "p": {"topics": op[1]}}, send)
        elif op[0] in ("grants", "reauth"):
            principal[0] = _principal(op[1], op[2])
            if op[0] == "grants":  # a narrowing, a withdrawn grant or permission (§9.5)
                await registry.grants_changed(USER)
            else:  # the gateway's in-place re-auth
                await registry.apply(authz, await registry.resolve(USER), 1, event="reauth")
        elif live:
            sub = live[op[1] % len(live)]
            if op[0] == "unsub":
                handle_unsub(authz, {"t": "unsub", "p": {"topics": [sub.ch]}}, 1)
            elif op[0] == "revoke":
                authz.revoke(sub, "resync_rate_limited", 1)
            else:
                handle_ctl(authz, {"t": "ctl", "ch": sub.ch, "p": {"throttle_ms": 500}}, 1)
        assert authz.held_symbols == _recount(authz), op
        assert len(authz.held_symbols) <= MAX_SYMBOLS_PER_CONNECTION
    registry.unregister(authz)  # the socket's teardown
    assert authz.by_id == {} and authz.held_symbols == {}


@settings(max_examples=150, deadline=None, derandomize=True, database=None)
@given(ops=st.lists(_op, min_size=1, max_size=10))
@example(ops=EVERY_PATH)
def test_the_held_symbol_multiset_always_equals_the_recount(ops: list[tuple[Any, ...]]) -> None:
    asyncio.run(_play(ops))
