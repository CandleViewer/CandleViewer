"""#415 (E17-X02, `23-ws-protocol.md` §9.5): a withdrawn grant's queued frames are dropped before
`permission_change`, whatever the backpressure flag, on both subprotocols, and a permission that a
role change removes is withdrawn the same way (C-12.4). M1 holds A and B; the writer is parked in a
send (a reader that stopped), frames of B, of A and of a public topic queue behind it, and B is
withdrawn: its grant removed or frozen, its topics' permission removed, both at once, or B narrowed
out of a subscription that keeps A. The real router runs behind `_Wire` on the test's loop: a fake
clock, no sleeps, every wait bounded.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, NamedTuple

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant
from candleviewer.bars.errors import BarsError
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import OUTBOUND_QUEUE_MAX, _Connection
from candleviewer.ws.metrics import SAMPLE_EVERY
from candleviewer.ws.outbound import PRIORITY_FAMILIES, QUEUE_FRAMES
from candleviewer.ws.permissions import ConnectionAuthz, Subscription
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws._seq_support import ACC_A, ACC_B, PERMS, USER
from tests.unit.ws.test_pipeline_invalidation import _RS, _STRUCTURED, _connected, _held
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _ENCODINGS,
    _JSON,
    _MSGPACK,
    _closes,
    _overflow,
    _Rig,
    _Wire,
)

_EACH = pytest.mark.parametrize(
    ("flag", "encoding"),
    [
        pytest.param(flag, encoding, id=f"flag-{'on' if flag else 'off'}-{encoding[6:]}")
        for flag in (False, True)
        for encoding in (_JSON, _MSGPACK)
    ],
)
_PRIVATE = ("orders", "positions", "executions", "wallet")
#: B's two topics: `orders` rides the priority lane with the flag on, `positions` the normal one.
_OF_B = ("orders", "positions")
Sent = list[tuple[str, str | None]]
_REVOKED: Sent = [("revoked", "orders"), ("revoked", "positions")]
_CHANGE: Sent = [("permission_change", None), *_REVOKED]
Planned = list[tuple[str, uuid.UUID | None]]
#: How B is withdrawn: its grant removed or frozen, the permission of its two topics removed by a
#: role change, or both in one change (reported `permission_revoked`: the permission is checked
#: first).
_HOW = ["removed", "frozen", "role", "both"]


def _grants(*accounts: uuid.UUID, frozen: tuple[uuid.UUID, ...] = ()) -> tuple[AccountGrant, ...]:
    return tuple(AccountGrant(account, True, False, account in frozen) for account in accounts)


def _body(family: str, *accounts: uuid.UUID, at: int = 1) -> dict[str, Any]:
    """One row per account, keyed as the family's §8.2 merge reads it."""
    rows = [{"exchange_account_id": str(a), "updated_at_ms": at} for a in accounts]
    if family == "wallet":  # per (account, coin)
        return {"balances": [row | {"coin": "USDT", "equity": "1"} for row in rows]}
    return {family: [row | {"id": f"{family}-{row['exchange_account_id']}-{at}"} for row in rows]}


def _rig(flag: bool, monkeypatch: pytest.MonkeyPatch, max_frames: int = QUEUE_FRAMES) -> _Rig:
    """A rig whose user reads the four private families on A and B, audited; a private snapshot
    holds one row per account of its subscription as it is when it is built."""
    rig = _Rig(BackpressureConfig(max_frames=max_frames) if flag else None)
    rig.perms, rig.grants = PERMS | {Permission.ACCOUNTS_READ}, _grants(ACC_A, ACC_B)
    rig.registry.services.audit = rig.audit
    build = rig.source.build

    def by_account(sub: Subscription) -> SnapshotBody | None:
        family = sub.topic.family.family
        if family not in _PRIVATE:
            return build(sub)
        return SnapshotBody(_body(family, *sorted(sub.accounts)))

    monkeypatch.setattr(rig.source, "build", by_account)
    return rig


def _withdraw(rig: _Rig, how: str) -> None:
    """The user's next principal read lacks B, as `how` says (`_HOW`)."""
    if how != "role":
        rig.grants = _grants(ACC_A, ACC_B, frozen=(ACC_B,)) if how == "frozen" else _grants(ACC_A)
    if how in ("role", "both"):
        rig.perms = rig.perms - {Permission.ORDERS_READ, Permission.POSITIONS_READ}


def _publish(rig: _Rig, plan: Planned, step: float = 0.6) -> Sent:
    """One update per `(family, account)` of `plan`, a book delta for `(_BOOK, None)`, `step`
    seconds apart (a book delta paces itself, 50 ms after the last), so with the flag on each
    leaves its window at once (D12): one queued `d` each. Returns them as (`d`, ch), in the order
    they were queued."""
    for i, (ch, account) in enumerate(plan):
        if account is None:
            assert rig.book_delta(i) == 1
        else:
            rig.clock.now += step
            assert rig.sequencing.publish(ch, _body(ch, account, at=i + 2), account=account) == 1
    return [("d", ch) for ch, _ in plan]


def _order(flag: bool, queued: Sent) -> Sent:
    """How the writer sends `queued` once it is released: as queued with the flag off; with it on,
    the priority lane first: control frames, `orders` and `executions` (§8.4 Lanes)."""

    def first(q: tuple[str, str | None]) -> bool:
        return not flag or q[0] not in ("d", "snap") or q[1] in PRIORITY_FAMILIES

    return [q for q in queued if first(q)] + [q for q in queued if not first(q)]


def _rows(frames: list[dict[str, Any]], account: uuid.UUID) -> list[dict[str, Any]]:
    """The rows of `frames`' data payloads that name `account`."""
    lists = [v for f in frames if f["t"] in ("d", "snap") for v in f["p"].values()]
    rows = [r for v in lists if isinstance(v, list) for r in v if isinstance(r, dict)]
    return [r for r in rows if r["exchange_account_id"] == str(account)]


def _sent(frames: list[dict[str, Any]]) -> Sent:
    return [(f["t"], f.get("ch")) for f in frames]


async def _drained(sock: _Wire, conn: _Connection) -> list[dict[str, Any]]:
    """Let the parked writer go and wait until it is quiet: its held frame, then one more while
    anything is still queued. Every frame it sent, for the caller to compare, so a frame too many
    or too few shows as a diff, not as a timeout; with the flag on, the budget's accounting is
    back at zero."""
    sock.release()
    pipe = conn.pipeline
    frames = await sock.next()
    while conn.outbound.qsize() if pipe is None else len(pipe.queue):
        frames += await sock.next()
    frames += [sock.sent.get_nowait() for _ in range(sock.sent.qsize())]
    assert pipe is None or (pipe.queue.bytes, pipe.queue.key_bytes()) == (0, {})
    return frames


async def _parked(rig: _Rig, sock: _Wire, plan: Planned) -> Sent:
    """`orders` and `positions` on B, `executions` and `wallet` on A, and the book; the writer
    parked, then `plan` queued behind it (`_publish`)."""
    for family in _PRIVATE:
        account = ACC_B if family in _OF_B else ACC_A
        await rig.sub(sock, family, exchange_account_ids=[str(account)])
    await rig.sub(sock)
    await _held(rig, sock)
    return _publish(rig, plan)


class _Run(NamedTuple):
    """One withdrawal of B behind the parked writer: what was queued, what the writer sent once
    released, the frames the change counted as dropped, the audit actions it wrote, and how many
    subscriptions an update of B published after it reached."""

    queued: Sent
    frames: list[dict[str, Any]]
    dropped: float
    audited: list[str]
    late: int


async def _withdraw_b(
    flag: bool, encoding: str, monkeypatch: pytest.MonkeyPatch, plan: Planned, how: str = "removed"
) -> _Run:
    rig, sock = _rig(flag, monkeypatch), _Wire(encoding)
    async with _connected(rig, sock) as conn:
        queued = await _parked(rig, sock, plan)
        before, mark = _overflow("withdrawn"), len(rig.audit.records)
        _withdraw(rig, how)
        await rig.registry.roles_changed(USER)  # a grant change takes the same path
        audited = [r["action"] for r in rig.audit.records[mark:]]
        late = sum(rig.sequencing.publish(f, _body(f, ACC_B), account=ACC_B) for f in _OF_B)
        frames = await _drained(sock, conn)
    return _Run(queued, frames, _overflow("withdrawn") - before, audited, late)


#: Two rounds, each a frame of B on both its topics between frames of A and a book delta.
_ROUND: Planned = [("positions", ACC_B), ("executions", ACC_A), ("orders", ACC_B)]
_ROUND += [("wallet", ACC_A), (_BOOK, None)]


@_EACH
@pytest.mark.parametrize("how", _HOW)
async def test_withdrawal_with_bs_frames_queued_drops_them_and_keeps_the_rest_in_order(
    flag: bool, encoding: str, how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B withdrawn while four of its frames wait behind the parked writer, two on each lane with
    the flag on: none of them reaches the client, and each counts as dropped. `permission_change`
    and the two `revoked` do, and A's frames and the book's follow in their own order."""
    run = await _withdraw_b(flag, encoding, monkeypatch, _ROUND * 2, how)
    kept = [q for q in run.queued if q[1] not in _OF_B]
    assert _sent(run.frames) == [("d", "system"), *_order(flag, kept + _CHANGE)]
    assert _rows(run.frames, ACC_B) == [] and len(_rows(run.frames, ACC_A)) == 4
    assert run.dropped == len(run.queued) - len(kept) == 4


@_EACH
@pytest.mark.parametrize("how", _HOW)
async def test_withdrawal_revokes_bs_topics_audited_and_routes_nothing_of_b_after(
    flag: bool, encoding: str, how: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The change itself is unchanged: one `revoked` per topic of B, `account_scope_changed`
    naming B for a grant and `permission_revoked` for a permission (also when both go at once),
    one `ws.subscription.revoked` row each, and no update of B published after it is routed."""
    run = await _withdraw_b(flag, encoding, monkeypatch, _ROUND, how)
    revoked = [f["p"] for f in run.frames if f["t"] == "revoked"]
    grant = how in ("removed", "frozen")
    want = ("account_scope_changed", [str(ACC_B)]) if grant else ("permission_revoked", None)
    assert [(p["reason"], p.get("removed_accounts")) for p in revoked] == [want] * 2
    assert run.audited == ["ws.subscription.revoked"] * 2 and run.late == 0


@_EACH
async def test_withdrawal_keeps_the_sequence_of_every_kept_channel_unbroken(
    flag: bool, encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3: A's channels and the book lose no frame and skip no sequence number. The book queues
    `SAMPLE_EVERY` deltas, so its sampled frame (flag off: a `(received, frame)` pair) is kept."""
    plan = _ROUND * 2 + [(_BOOK, None)] * (SAMPLE_EVERY - 2)
    run = await _withdraw_b(flag, encoding, monkeypatch, plan)
    for ch in ("executions", "wallet", _BOOK):
        n = sum(1 for c, _ in plan if c == ch)
        assert [f["s"] for f in run.frames if f.get("ch") == ch] == list(range(2, n + 2))
    assert SAMPLE_EVERY in [f["s"] for f in run.frames if f.get("ch") == _BOOK]


@_EACH
async def test_withdrawal_with_nothing_of_b_queued_drops_nothing(
    flag: bool, encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B's topics hold nothing in the queue when B is withdrawn: nothing is dropped, and every frame
    of A and of the book is delivered in order with the change."""
    plan = [q for q in _ROUND if q[0] not in _OF_B] * 2
    run = await _withdraw_b(flag, encoding, monkeypatch, plan)
    assert _sent(run.frames) == [("d", "system"), *_order(flag, run.queued + _CHANGE)]
    assert run.dropped == 0


@_EACH
async def test_a_role_change_drops_a_replay_subscriptions_frames_with_its_live_twins(
    flag: bool, encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Market data removed by a role change revokes a public topic live and replay alike. A live
    book subscription and a replay one (`rs` set) hold three queued deltas each: the purge keys
    on `(ch, rs)`, so all six go before `permission_change`."""
    rig, sock = _rig(flag, monkeypatch), _Wire(encoding)
    async with _connected(rig, sock) as conn:
        await rig.sub(sock)
        entry = {"ch": _BOOK, "opts": _STRUCTURED}
        sock.feed({"t": "sub", "id": "r", "p": {"topics": [entry], "replay_session_id": _RS}})
        await sock.next(2)
        await _held(rig, sock)
        for i in range(3):
            assert rig.book_delta(i) == 1
            assert rig.sequencing.publish(_BOOK, {"bids": [], "asks": []}, replay_session_id=_RS)
        before = _overflow("withdrawn")
        rig.perms = rig.perms - {Permission.MARKETDATA_READ}
        await rig.registry.roles_changed(USER)
        frames = await _drained(sock, conn)
    assert [f["t"] for f in frames] == ["d", "permission_change", "revoked", "revoked"]
    revoked = frames[2:]
    assert {f.get("rs") for f in revoked} == {None, _RS}
    assert {f["p"]["reason"] for f in revoked} == {"permission_revoked"}
    assert _overflow("withdrawn") - before == 6


@_EACH
async def test_withdrawal_drops_bs_queued_snaps_and_keeps_their_sub_ok(
    flag: bool, encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `sub` of `orders` and `positions` on B while the writer is parked queues its `sub_ok` and
    a `snap` of each, one on each lane with the flag on; then B is withdrawn. Neither `snap` nor
    any row of B reaches the client, both count as dropped, and the `sub_ok` is delivered."""
    rig, sock = _rig(flag, monkeypatch), _Wire(encoding)
    both, build, built = asyncio.Event(), rig.source.build, []

    def counted(sub: Subscription) -> SnapshotBody | None:
        if sub.accounts == {ACC_B}:  # the last one's frames are queued in the same step
            built.append(sub.ch)
            if len(built) == len(_OF_B):
                both.set()
        return build(sub)

    monkeypatch.setattr(rig.source, "build", counted)
    async with _connected(rig, sock) as conn:
        await rig.sub(sock)
        await _held(rig, sock)
        topics = [{"ch": f, "opts": {"exchange_account_ids": [str(ACC_B)]}} for f in _OF_B]
        sock.feed({"t": "sub", "id": "b", "p": {"topics": topics}})
        await both.wait()
        before = _overflow("withdrawn")
        rig.grants = _grants(ACC_A)
        await rig.registry.grants_changed(USER)
        frames = await _drained(sock, conn)
    assert _sent(frames) == [("d", "system"), ("sub_ok", None), *_CHANGE]
    assert _rows(frames, ACC_B) == [] and _overflow("withdrawn") - before == len(_OF_B)


def _settled(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Set once the registry's next `settle` has run: an in-place re-`auth` queued its frames."""
    settle, done = rig.registry.settle, asyncio.Event()

    async def spy(authz: ConnectionAuthz, close: Any) -> None:
        await settle(authz, close)
        done.set()

    monkeypatch.setattr(rig.registry, "settle", spy)
    return done


@_EACH
@pytest.mark.parametrize("path", ["grant_change", "reauth"])
async def test_narrowing_to_a_drops_the_topics_queued_frames_and_snaps_a_after_revoked(
    flag: bool, encoding: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`orders` and `positions` held on A and B, rows of both queued, B narrowed out mid-stream by
    a grant change or on an in-place re-`auth` (`auth_ok` announces it). A frame is never split,
    so their queued frames all go; each is re-pended `reconfigure`, and its `snap`, built under the
    new scope with A's row only, follows its `revoked`: a new baseline at the next `s`, whose
    `previous_seq` is the last one the dropped frames took. The book's frames keep their order."""
    rig, sock = _rig(flag, monkeypatch), _Wire(encoding)
    async with _connected(rig, sock) as conn:
        for family in _OF_B:
            await rig.sub(sock, family, exchange_account_ids=[str(ACC_A), str(ACC_B)])
        await rig.sub(sock)
        await _held(rig, sock)
        both: Planned = [(f, a) for a in (ACC_A, ACC_B) for f in _OF_B]
        queued = _publish(rig, [*both, (_BOOK, None)] * 2)
        before = _overflow("withdrawn")
        rig.grants = _grants(ACC_A)
        if path == "grant_change":
            await rig.registry.grants_changed(USER)
        else:
            settled = _settled(rig, monkeypatch)
            sock.feed({"t": "auth", "id": "a2", "p": {"access_token": "tok"}})
            await settled.wait()
        frames = await _drained(sock, conn)
    first = "permission_change" if path == "grant_change" else "auth_ok"
    kept = [q for q in queued if q[1] == _BOOK]
    changed: Sent = [(first, None), *_REVOKED, ("snap", "orders"), ("snap", "positions")]
    assert _sent(frames) == [("d", "system"), *_order(flag, kept + changed)]
    revoked = [f["p"] for f in frames if f["t"] == "revoked"]
    assert [(p["removed_accounts"], p["resubscribe_allowed"]) for p in revoked] == [
        ([str(ACC_B)], True)
    ] * 2
    snaps = [f for f in frames if f["t"] == "snap"]  # `s` 6, after the dropped 2 to 5
    reset = [(f["meta"]["reason"], f["s"], f["meta"]["previous_seq"]) for f in snaps]
    assert reset == [("reconfigure", 6, 5)] * 2
    assert [len(_rows([f], ACC_A)) for f in snaps] == [1, 1] and _rows(frames, ACC_B) == []
    assert _overflow("withdrawn") - before == 8


@_ENCODINGS
async def test_flag_off_narrowing_snaps_only_the_topic_whose_frames_were_dropped(
    encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag off, `orders` and `positions` narrowed from A and B to A, frames queued for `positions`
    alone: only it is re-pended and gets its `reconfigure` `snap` (`s` 4, after the dropped 2 and
    3). `orders` goes on in place: its next `d` takes `s` 2, with no `snap`."""
    rig, sock = _rig(False, monkeypatch), _Wire(encoding)
    async with _connected(rig, sock) as conn:
        for family in _OF_B:
            await rig.sub(sock, family, exchange_account_ids=[str(ACC_A), str(ACC_B)])
        await _held(rig, sock)
        _publish(rig, [("positions", ACC_A), ("positions", ACC_B)])
        rig.grants = _grants(ACC_A)
        await rig.registry.grants_changed(USER)
        assert rig.sequencing.publish("orders", _body("orders", ACC_A), account=ACC_A) == 1
        frames = await _drained(sock, conn)
    assert _sent(frames) == [("d", "system"), *_CHANGE, ("snap", "positions"), ("d", "orders")]
    snap, delta = frames[4:]
    meta = snap["meta"]
    assert (meta["reason"], snap["s"], meta["previous_seq"], delta["s"]) == ("reconfigure", 4, 3, 2)


@_EACH
async def test_withdrawal_at_the_queue_bound_queues_the_change_and_stays_open(
    flag: bool, encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.18 with §9.5: the queue holds its bound (1 024 frames flag off, a 12-frame budget flag
    on), all of it B's `orders` frames but one of A's `executions`. The withdrawal frees that room
    before `permission_change` is queued, so the change and its `revoked` are queued and the socket
    stays open: queued first, they would find the bound full and close it `slow_consumer`."""
    bound = 12 if flag else OUTBOUND_QUEUE_MAX
    rig, sock = _rig(flag, monkeypatch, max_frames=bound), _Wire(encoding)
    async with _connected(rig, sock) as conn:
        await rig.sub(sock, "executions", exchange_account_ids=[str(ACC_A)])
        await rig.sub(sock, "orders", exchange_account_ids=[str(ACC_B)])
        await _held(rig, sock)
        plan: Planned = [("executions", ACC_A)]
        plan += [("orders", ACC_B)] * (bound - 1)
        _publish(rig, plan, step=0.0)
        before = _overflow("withdrawn")
        rig.grants = _grants(ACC_A)
        await rig.registry.grants_changed(USER)
        frames = await _drained(sock, conn)
    assert _sent(frames) == [
        ("d", "system"),
        ("d", "executions"),
        ("permission_change", None),
        ("revoked", "orders"),
    ]
    assert sock.closed_with is None and _overflow("withdrawn") - before == bound - 1


def _failing_swap(conn: _Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """The next swap raises at B's first topic (`_drop` -> `BarsError`), before the purge."""
    assert conn.authz is not None
    drop = conn.authz._drop

    def raises(sub: Subscription) -> None:
        drop(sub)
        if sub.ch == "orders":
            raise BarsError("the series was dropped")

    monkeypatch.setattr(conn.authz, "_drop", raises)


@_EACH
async def test_a_swap_that_raises_evicts_the_socket_with_none_of_the_queued_frames(
    flag: bool, encoding: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A swap that raises mid-way never reaches the purge, so the registry evicts the socket. The
    eviction is sealed whatever the flag: the client gets its `bye`, none of B's queued frames and
    nothing else that was queued (a stalled consumer cannot flush anyway)."""
    rig, sock = _rig(flag, monkeypatch), _Wire(encoding)
    async with _connected(rig, sock) as conn:
        await _parked(rig, sock, _ROUND)
        _failing_swap(conn, monkeypatch)
        rig.grants = _grants(ACC_A)
        await rig.registry.grants_changed(USER)
        frames = await _drained(sock, conn)
        closed = sock.closed_with
    assert _sent(frames) == [("d", "system"), ("bye", None)]
    assert (frames[1]["p"]["reason"], closed) == ("slow_consumer", 4429)


@_ENCODINGS
@pytest.mark.parametrize("first", ["shutdown", "slow_consumer"])
async def test_flag_off_eviction_of_a_closing_socket_seals_it_and_counts_no_second_close(
    encoding: str, first: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close is under way, its `bye` queued behind B's frames, when a swap that raises evicts
    the socket. That close stays the connection's one close: counted once, logged once as `ws
    close`, its `bye` sent next (sealed). The eviction logs `ws eviction sealed`, not a close."""
    rig, sock = _rig(False, monkeypatch), _Wire(encoding)
    seen = ("shutdown", "slow_consumer")
    before = {reason: _closes(reason) for reason in seen}
    async with _connected(rig, sock) as conn:
        queued = await _parked(rig, sock, _ROUND)
        _failing_swap(conn, monkeypatch)
        rig.grants = _grants(ACC_A)
        with capture_logs() as logs:
            conn.close_with(first)
            await rig.registry.grants_changed(USER)
        frames = await _drained(sock, conn)
        closed = sock.closed_with
    assert _sent(frames) == [("d", "system"), ("bye", None)]
    assert (frames[1]["p"]["reason"], closed) == (first, frames[1]["p"]["code"])
    assert {r: _closes(r) - before[r] for r in seen} == {r: int(r == first) for r in seen}
    assert [(e["event"], e["reason"]) for e in logs if e["event"].startswith("ws close")] == [
        ("ws close", first)
    ]
    (line,) = [e for e in logs if e["event"] == "ws eviction sealed"]
    assert (line["log_level"], line["dropped"]) == ("info", len(queued))
