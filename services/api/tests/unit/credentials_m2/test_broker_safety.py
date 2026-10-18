"""Broker safety: status gating, destroy fence, plaintext zeroing, timeouts (E27-T02 review)."""

from __future__ import annotations

import asyncio
import traceback
import types
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import (
    CredentialUnavailable,
)
from candleviewer.secrets.secret import Secret
from tests.unit.credentials_m2._helpers import (
    _borrow,
    _h,
    _Spy,
    _store,
    _with,
)
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
    API_KEY,
    API_SECRET,
    KEK_LIVE,
    KEK_V2,
    SNAPSHOT,
    AuditLog,
    FakeClock,
    kek,
)

#: The name the broker gives its `last_used_at` write tasks (#2776).
_TOUCH_TASK = "secrets-credential-touch"
#: A low-entropy key-id marker for the frame-locals check (never a real credential).
_MARK_ID = "storefail" + "0" * 9 + "WXYZ"
#: Low-entropy KEK and DEK markers for the seal-path frame check (never real key material).
_MARK_KEK = b"kekmark" + b"0" * 25
_MARK_DEK = b"dekmark" + b"0" * 25


def _touch_tasks() -> list[asyncio.Task[Any]]:
    """The `last_used_at` write tasks in flight in this test's loop, whether or not the broker
    still tracks them (#2776)."""
    return [t for t in asyncio.all_tasks() if t.get_name() == _TOUCH_TASK]


async def _drain_touches() -> None:
    """Await, never cancel, every in-flight `last_used_at` write of this test's loop (#2776), so
    a write that should not have started still lands before the assertions run."""
    await asyncio.gather(*_touch_tasks(), return_exceptions=True)


def _stalling_touch(clock: FakeClock) -> tuple[list[float], asyncio.Event, Any]:
    """A `touch_last_used` whose first write stalls until cancelled; any later one returns at
    once, so a broker that starts a second write is caught at once instead of waiting it out."""
    writes: list[float] = []
    stalled = asyncio.Event()

    async def touch(key_id: UUID) -> None:
        writes.append(clock.t)
        if len(writes) == 1:
            stalled.set()
            await asyncio.Event().wait()

    return writes, stalled, touch


async def test_broker_audit_timeout_fails_closed(store: Any) -> None:
    async def stall(action: str, fields: dict[str, str]) -> None:
        await asyncio.Event().wait()

    b = CredentialBroker(store, stall, kek(), io_timeout_s=0.01)
    with pytest.raises(CredentialUnavailable) as ei:
        await _store(b)
    assert str(ei.value) == "audit_timeout" and not store.rows


async def test_dek_cache_hit_ttl_and_flush(store: Any, audit: AuditLog, clock: FakeClock) -> None:
    b = CredentialBroker(store, audit, kek(), clock=clock, dek_cache_ttl_s=300)
    meta = await _store(b)
    await _borrow(b, meta.key_id)
    assert len(b._cache) == 1
    clock.t = 299
    store.rows[meta.key_id]["dek_ref"] = "v1:00"  # cache hit bypasses the wrapped DEK
    assert await _borrow(b, meta.key_id) == (API_KEY, API_SECRET)
    clock.t = 301
    with pytest.raises(CredentialUnavailable):
        await _borrow(b, meta.key_id)
    assert len(b._cache) == 0


async def test_last_used_touch_is_debounced(store: Any, audit: AuditLog, clock: FakeClock) -> None:
    touched: list[Any] = []

    async def touch(key_id: Any) -> None:
        touched.append(key_id)

    store.touch_last_used = touch
    b = CredentialBroker(store, audit, kek(), clock=clock)
    meta = await _store(b)
    for t in (0, 59, 61):
        clock.t = t
        await _borrow(b, meta.key_id)
        await _drain_touches()
    assert len(touched) == 2


async def test_last_used_touch_debounce_boundary_is_per_key(
    store: Any, audit: AuditLog, clock: FakeClock
) -> None:
    """#2580: the broker is the only `last_used_at` writer (21 §3.2.2), so the boundary cases
    live here: no write just inside the 60 s window, one at exactly 60 s, a window per key."""
    touched: list[tuple[float, UUID]] = []

    async def touch(key_id: UUID) -> None:
        touched.append((clock.t, key_id))

    store.touch_last_used = touch
    b = CredentialBroker(store, audit, kek(), clock=clock)
    one, two = uuid4(), uuid4()
    for t, key in ((0.0, one), (0.0, two), (59.999999, one), (60.0, one), (60.0, two)):
        clock.t = t
        b._touch(key)
        await _drain_touches()
    assert touched == [(0.0, one), (0.0, two), (60.0, one), (60.0, two)]


async def test_last_used_touch_rearms_each_window(
    store: Any, audit: AuditLog, clock: FakeClock
) -> None:
    """#2580: every write starts a new 60 s window, so a key signing once a second writes
    `last_used_at` once a minute, not once ever and not on every signing."""
    touched: list[float] = []

    async def touch(key_id: UUID) -> None:
        touched.append(clock.t)

    store.touch_last_used = touch
    b = CredentialBroker(store, audit, kek(), clock=clock)
    key = uuid4()
    for second in range(181):
        clock.t = float(second)
        b._touch(key)
        await _drain_touches()
    assert touched == [0.0, 60.0, 120.0, 180.0]


async def test_borrow_with_a_stalled_touch_returns_while_the_write_is_in_flight(
    store: Any, clock: FakeClock
) -> None:
    """#2776: a signing never waits on `last_used_at`. The write stalls and its bound is long
    (60 s), yet the borrow has already returned when the write starts, and the write is still in
    flight."""
    entered = asyncio.Event()

    async def stall(key_id: UUID) -> None:
        entered.set()
        await asyncio.Event().wait()

    store.touch_last_used = stall
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=60.0)
    meta = await _store(b)
    borrow = asyncio.create_task(_borrow(b, meta.key_id))
    await entered.wait()
    assert borrow.done() and borrow.result()[0] == API_KEY
    (write,) = b._touches.values()
    assert not write.done()
    await b.aclose()


async def test_touch_stalled_second_signing_in_window_starts_no_second_write(
    store: Any, clock: FakeClock
) -> None:
    """#2776: while one write for the key stalls, a signing inside its window starts no other."""
    writes, stalled, touch = _stalling_touch(clock)
    store.touch_last_used = touch
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=60.0)
    meta = await _store(b)
    first = asyncio.create_task(_borrow(b, meta.key_id))
    await stalled.wait()
    clock.t = 30.0
    await _borrow(b, meta.key_id)
    assert writes == [0.0] and len(_touch_tasks()) == 1
    await b.aclose()
    assert (await first)[0] == API_KEY


async def test_touch_stalled_past_its_window_keeps_one_write_per_key_in_flight(
    store: Any, clock: FakeClock
) -> None:
    """#2776 (C-2.18): a write that outlives its 60 s window still bounds the key to one write in
    flight, so a signing in the next window starts none while it runs."""
    writes, stalled, touch = _stalling_touch(clock)
    store.touch_last_used = touch
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=600.0)
    meta = await _store(b)
    first = asyncio.create_task(_borrow(b, meta.key_id))
    await stalled.wait()
    clock.t = 61.0
    await _borrow(b, meta.key_id)
    assert writes == [0.0] and len(_touch_tasks()) == 1
    await b.aclose()
    assert (await first)[0] == API_KEY


async def test_touch_failure_is_debounced_like_a_success_and_retried_next_window(
    store: Any, clock: FakeClock
) -> None:
    """#2776: the window is stamped before the write, so a failed write is not retried by the
    next signing: none at 59 s, one at 60 s, none at 61 s. Each failure is counted once."""
    writes: list[float] = []

    async def fail(key_id: UUID) -> None:
        writes.append(clock.t)
        raise RuntimeError("db down")

    store.touch_last_used = fail
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock)
    meta = await _store(b)
    before = m.credential_touch_failures_total._value.get()
    for t in (0.0, 59.0, 60.0, 61.0):
        clock.t = t
        assert (await _borrow(b, meta.key_id))[0] == API_KEY
        await _drain_touches()
    assert writes == [0.0, 60.0]
    assert m.credential_touch_failures_total._value.get() == before + 2


@pytest.mark.parametrize("status", ["pending", "invalid", "expired", "revoked"])
async def test_borrow_refuses_non_signable_status(
    broker: CredentialBroker, store: Any, status: str
) -> None:
    meta = await _store(broker)
    store.activate(meta.key_id, status)
    with pytest.raises(CredentialUnavailable):
        await _borrow(broker, meta.key_id)


async def test_pending_key_borrowable_only_for_verification(
    broker: CredentialBroker, store: Any
) -> None:
    meta = await _store(broker)
    store.activate(meta.key_id, "pending")
    msg = (KEY_ID_SLOT,)
    with pytest.raises(CredentialUnavailable):
        await _h(broker).sign(meta.key_id, msg, purpose="sign_rest")
    out = await _h(broker).sign(meta.key_id, msg, purpose="key_verify")
    assert out.api_key.reveal() == API_KEY


async def test_rotating_key_is_signable(broker: CredentialBroker, store: Any) -> None:
    meta = await _store(broker)
    store.activate(meta.key_id, "rotating")
    assert (await _borrow(broker, meta.key_id))[0] == API_KEY


async def test_destroy_fences_in_flight_borrow(store: Any) -> None:
    gate, release = asyncio.Event(), asyncio.Event()
    order: list[str] = []

    async def audit(action: str, fields: dict[str, str]) -> None:
        order.append(action)
        if action == "security.credential_borrowed":
            gate.set()
            await release.wait()

    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        order.append("plaintext_handed_out")

    borrow = asyncio.create_task(_with(b, meta.key_id, fn))
    await gate.wait()
    await b.destroy(meta.key_id)
    release.set()
    with pytest.raises(CredentialUnavailable):
        await borrow
    assert "plaintext_handed_out" not in order


async def test_destroy_revoke_failure_audited_and_row_stays_live(store: Any) -> None:
    audit = AuditLog()
    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)

    async def boom(key_id: Any) -> None:
        raise RuntimeError("db")

    store.mark_revoked = boom
    with pytest.raises(CredentialUnavailable):  # typed; the raw DB error never leaves M2
        await b.destroy(meta.key_id)
    assert audit.actions()[-2:] == [
        "security.credential_destroyed",
        "security.credential_destroy_failed",
    ]
    assert not store.rows[meta.key_id]["revoked"]
    with pytest.raises(CredentialUnavailable):  # fail closed: stays fenced in this process
        await _borrow(b, meta.key_id)


async def test_destroy_cancelled_during_revoke_propagates_and_stays_fenced(store: Any) -> None:
    started, audit = asyncio.Event(), AuditLog()
    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)

    async def hang(key_id: Any) -> None:
        started.set()
        await asyncio.Event().wait()

    store.mark_revoked = hang
    task = asyncio.create_task(b.destroy(meta.key_id))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert audit.actions()[-1] == "security.credential_destroy_failed"
    with pytest.raises(CredentialUnavailable):
        await _borrow(b, meta.key_id)


async def test_destroy_failure_audit_error_keeps_original(store: Any) -> None:
    audit = AuditLog()
    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)

    async def boom(key_id: Any) -> None:
        audit.fail = True
        raise RuntimeError("db")

    store.mark_revoked = boom
    with pytest.raises(CredentialUnavailable) as ei:
        await b.destroy(meta.key_id)
    assert str(ei.value) == "store_unavailable"


async def test_store_insert_failure_audited_and_typed(store: Any) -> None:
    audit = AuditLog()
    b = CredentialBroker(store, audit, kek())

    async def refuse(record: Any) -> None:
        raise ValueError("exchange account missing or environment mismatch")

    store.insert = refuse
    with pytest.raises(CredentialUnavailable) as ei:
        await _store(b)
    assert str(ei.value) == "store_unavailable"
    assert audit.actions() == ["security.credential_stored", "security.credential_store_failed"]


async def test_a_failed_store_leaves_no_key_id_in_its_frame_locals(store: Any) -> None:
    """C-12.6: a failing insert's traceback, rendered with frame locals, shows no pasted key id:
    `store()` binds no local to it, as for the API secret."""

    async def refuse(record: Any) -> None:
        raise ValueError("db down")

    store.insert = refuse
    b = CredentialBroker(store, AuditLog(), kek())
    with pytest.raises(CredentialUnavailable) as ei:
        await b.store("demo", ACCOUNT, "l", Secret(_MARK_ID), Secret(API_SECRET), SNAPSHOT)
    shown = traceback.TracebackException.from_exception(ei.value, capture_locals=True)
    rendered = "".join(shown.format())
    assert ", in store\n" in rendered and _MARK_ID not in rendered


@pytest.mark.parametrize("failing", [1, 2, 3], ids=["dek_wrap", "key_id_seal", "secret_seal"])
async def test_a_failed_seal_leaves_no_key_material_in_its_frame_locals(
    store: Any, monkeypatch: pytest.MonkeyPatch, failing: int
) -> None:
    """C-12.6: a seal that fails inside `env.seal` (the DEK wrap under the KEK, or either half of
    the pasted pair) renders with frame locals no KEK, DEK, key id or secret: `_seal_new` scrubs
    the frames below it, as `request_signature` does."""
    calls = 0

    class Refusing:  # AES-GCM whose `failing`-th encryption raises
        def __init__(self, key: bytes) -> None:
            self.aead = AESGCM(key)

        def encrypt(self, nonce: bytes, data: bytes, aad: bytes) -> bytes:
            nonlocal calls
            calls += 1
            if calls == failing:
                raise ValueError("seal refused")
            return self.aead.encrypt(nonce, data, aad)

    monkeypatch.setattr(env, "AESGCM", Refusing)
    monkeypatch.setattr(env, "new_dek", lambda: bytearray(_MARK_DEK))
    b = CredentialBroker(store, AuditLog(), kek(_MARK_KEK))
    with pytest.raises(ValueError, match="seal refused") as failed:
        await b.store("demo", ACCOUNT, "l", Secret(_MARK_ID), Secret(API_SECRET), SNAPSHOT)
    shown = traceback.TracebackException.from_exception(failed.value, capture_locals=True)
    rendered = "".join(shown.format())
    marks = (_MARK_KEK.decode(), _MARK_DEK.decode(), _MARK_ID, API_SECRET)
    assert (", in seal\n" in rendered, [x for x in marks if x in rendered]) == (True, [])


async def test_store_refuses_other_environment(store: Any) -> None:
    b = CredentialBroker(store, AuditLog(), kek(), env_name="demo")
    with pytest.raises(CredentialUnavailable) as ei:
        await b.store("live", ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    assert str(ei.value) == "environment_mismatch" and not store.rows


def _rewrap_for(store: Any, key_id: Any, to: LoadedKek) -> None:
    """Re-wrap a live row's DEK for `to`, as only a holder of both KEKs could, to test the
    layers behind the environment-bound wrap (#2338)."""
    row = store.rows[key_id]
    dek = kek(KEK_LIVE, 1, "live").unwrap_dek(row["dek_ref"], credential_id=key_id)
    row["dek_ref"] = to.wrap_dek(dek, credential_id=key_id)


def test_broker_refuses_a_kek_loaded_for_another_environment(store: Any) -> None:
    live = kek(env="live")
    with pytest.raises(ValueError, match="another environment"):
        CredentialBroker(store, AuditLog(), live, env_name="demo")
    current, previous = kek(KEK_V2, 2), kek(env="testnet")
    with pytest.raises(ValueError, match="another environment"):
        CredentialBroker(store, AuditLog(), current, prev_kek=previous)
    assert [not any(k._key) for k in (live, current, previous)] == [True, True, True]  # zeroed


async def test_demo_bound_broker_never_reads_a_live_row(store: Any) -> None:
    live = CredentialBroker(store, AuditLog(), kek(KEK_LIVE, 1, "live"), env_name="live")
    meta = await live.store("live", ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    store.activate(meta.key_id)
    _rewrap_for(store, meta.key_id, kek())  # the wrap opens for demo: only the env fences remain
    demo = CredentialBroker(store, AuditLog(), kek(), env_name="demo")
    with pytest.raises(CredentialUnavailable):
        await _borrow(demo, meta.key_id)  # env-namespaced read: the row is invisible
    store.rows[meta.key_id]["env"] = "demo"  # even if a DB writer relabels it
    with pytest.raises(CredentialUnavailable):
        await _borrow(demo, meta.key_id)  # the AAD is bound to the *process* env: tag fails


async def test_plaintext_zeroed_when_second_field_fails(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    b = CredentialBroker(store, AuditLog(), kek(), dek_cache_ttl_s=0)
    meta = await _store(b)
    spy = _Spy(monkeypatch, fail_on=3)  # 1: dek unwrap, 2: key_id, 3: secret
    with pytest.raises(CredentialUnavailable):
        await _borrow(b, meta.key_id)
    assert spy.all_zero()


async def test_plaintext_zeroed_on_fn_cancel(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    b = CredentialBroker(store, AuditLog(), kek(), dek_cache_ttl_s=0)
    meta = await _store(b)
    spy = _Spy(monkeypatch)
    started = asyncio.Event()

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        started.set()
        await asyncio.Event().wait()

    t = asyncio.create_task(_with(b, meta.key_id, fn))
    await started.wait()
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    assert spy.all_zero()


async def test_touch_failure_is_best_effort_and_counted(store: Any, clock: FakeClock) -> None:
    async def stall(key_id: Any) -> None:
        await asyncio.Event().wait()

    store.touch_last_used = stall
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=0.01)
    meta = await _store(b)
    before = m.credential_touch_failures_total._value.get()
    assert (await _borrow(b, meta.key_id))[0] == API_KEY  # signing never blocked by metadata
    await _drain_touches()  # the write times out at io_timeout_s, off the signing path
    assert m.credential_touch_failures_total._value.get() == before + 1


async def test_broker_aclose_cancels_a_stalled_touch_without_counting_a_failure(
    store: Any, clock: FakeClock
) -> None:
    """#2776: shutdown cancels and awaits the in-flight write. Cancellation is not a failure, and
    no task is left pending."""
    entered, unwound = asyncio.Event(), asyncio.Event()

    async def stall(key_id: UUID) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            unwound.set()

    store.touch_last_used = stall
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=60.0)
    meta = await _store(b)
    before = m.credential_touch_failures_total._value.get()
    await _borrow(b, meta.key_id)
    await entered.wait()
    (write,) = b._touches.values()
    await b.aclose()
    assert write.cancelled() and unwound.is_set() and not b._touches
    assert asyncio.all_tasks() == {asyncio.current_task()}
    assert m.credential_touch_failures_total._value.get() == before


async def test_broker_aclose_before_a_touch_starts_cancels_it_cleanly(
    store: Any, clock: FakeClock
) -> None:
    """#2776: a write cancelled before its first step never reaches the store, and leaves no
    never-awaited coroutine behind (the suite runs with `-W error`)."""
    writes: list[UUID] = []

    async def touch(key_id: UUID) -> None:
        writes.append(key_id)

    store.touch_last_used = touch
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock)
    b._touch(uuid4())
    (write,) = b._touches.values()
    await b.aclose()
    assert write.cancelled() and writes == [] and not b._touches


async def test_broker_aclose_is_idempotent_and_later_signings_start_no_touch(
    store: Any, clock: FakeClock
) -> None:
    """#2776: a closed broker still signs, but starts no write a later shutdown could miss."""
    writes: list[float] = []

    async def touch(key_id: UUID) -> None:
        writes.append(clock.t)

    store.touch_last_used = touch
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock)
    meta = await _store(b)
    await b.aclose()
    await b.aclose()
    assert (await _borrow(b, meta.key_id))[0] == API_KEY
    await _drain_touches()
    assert writes == [] and not b._touches


async def test_broker_aclose_with_a_wedged_write_cleanup_recancels_until_it_ends(
    store: Any, clock: FakeClock
) -> None:
    """#2776 review: a cancelled write whose cleanup stalls again and again (the UPDATE, then a
    rollback, then a close, on a connection that never answers) cannot hold shutdown forever:
    `aclose` cancels what still runs every `io_timeout_s`, so each stalled step ends, the write
    ends, nothing is left pending, and cancellation is still not counted as a failure."""
    entered = asyncio.Event()
    steps: list[str] = []

    async def wedged(step: str) -> None:
        steps.append(step)
        await asyncio.Event().wait()  # never answers: only a cancellation ends this step

    async def write(key_id: UUID) -> None:
        entered.set()
        try:
            try:
                await wedged("update")
            finally:
                await wedged("rollback")
        finally:
            await wedged("close")

    store.touch_last_used = write
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=0.01)
    meta = await _store(b)
    before = m.credential_touch_failures_total._value.get()
    await _borrow(b, meta.key_id)
    await entered.wait()
    (task,) = b._touches.values()
    await b.aclose()
    assert task.cancelled() and steps == ["update", "rollback", "close"] and not b._touches
    assert asyncio.all_tasks() == {asyncio.current_task()}
    assert m.credential_touch_failures_total._value.get() == before


async def test_touch_done_callback_with_a_newer_entry_for_the_key_keeps_it(
    store: Any, clock: FakeClock
) -> None:
    """#2776 review: an ending write removes its own entry only (by identity), never a newer
    write's, so the one-write-per-key bound cannot silently reopen."""
    writes, stalled, touch = _stalling_touch(clock)
    store.touch_last_used = touch
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=60.0)
    key = uuid4()
    b._touch(key)
    old = b._touches[key]
    await stalled.wait()

    async def later_write() -> None:
        await asyncio.Event().wait()

    newer = asyncio.create_task(later_write(), name=_TOUCH_TASK)
    b._touches[key] = newer  # stands in for a later write of the same key
    old.cancel()
    await asyncio.gather(old, return_exceptions=True)
    assert old.cancelled() and b._touches == {key: newer} and writes == [0.0]
    await b.aclose()
    assert newer.cancelled()


async def test_touch_task_with_a_stalled_write_holds_no_broker(
    store: Any, clock: FakeClock
) -> None:
    """#2776 review: the write task's frame holds the store's write, the key id and the bound,
    never the broker, so its KEK and DEK cache are not reachable from the task."""
    entered = asyncio.Event()

    async def stall(key_id: UUID) -> None:
        entered.set()
        await asyncio.Event().wait()

    store.touch_last_used = stall
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=60.0)
    key = uuid4()
    b._touch(key)
    await entered.wait()
    (task,) = b._touches.values()
    coro = task.get_coro()
    assert isinstance(coro, types.CoroutineType) and coro.cr_frame is not None
    assert dict(coro.cr_frame.f_locals) == {"write": stall, "key_id": key, "timeout_s": 60.0}
    await b.aclose()


async def test_destroy_cancels_only_that_keys_in_flight_touch(store: Any, clock: FakeClock) -> None:
    """#2776: `destroy` fences the key, then cancels its pending `last_used_at` write; another
    key's write is untouched."""
    entered: dict[UUID, asyncio.Event] = {}

    async def stall(key_id: UUID) -> None:
        entered[key_id].set()
        await asyncio.Event().wait()

    store.touch_last_used = stall
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=60.0)
    doomed, kept = (await _store(b)).key_id, (await _store(b)).key_id
    entered.update({doomed: asyncio.Event(), kept: asyncio.Event()})
    for key in (doomed, kept):
        await _borrow(b, key)
    for key in (doomed, kept):
        await entered[key].wait()
    doomed_write, kept_write = b._touches[doomed], b._touches[kept]
    await b.destroy(doomed)
    await asyncio.gather(doomed_write, return_exceptions=True)
    assert doomed_write.cancelled() and not kept_write.done()
    assert list(b._touches) == [kept]
    await b.aclose()


async def test_borrow_fenced_by_destroy_starts_no_touch(store: Any) -> None:
    """#2776: the write starts only once the post-audit fence re-check passes, so a key destroyed
    while its borrow awaited the write-ahead audit is never touched after its fence."""
    gate, release = asyncio.Event(), asyncio.Event()
    writes: list[UUID] = []

    async def audit(action: str, fields: dict[str, str]) -> None:
        if action == "security.credential_borrowed":
            gate.set()
            await release.wait()

    async def touch(key_id: UUID) -> None:
        writes.append(key_id)

    store.touch_last_used = touch
    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)
    borrow = asyncio.create_task(_borrow(b, meta.key_id))
    await gate.wait()
    await b.destroy(meta.key_id)
    release.set()
    with pytest.raises(CredentialUnavailable):
        await borrow
    await _drain_touches()
    assert writes == [] and not b._touches


async def test_store_load_timeout_is_typed(store: Any) -> None:
    b = CredentialBroker(store, AuditLog(), kek(), io_timeout_s=0.01)
    meta = await _store(b)

    async def stall(key_id: Any, env: str) -> Any:
        await asyncio.Event().wait()

    store.get = stall
    with pytest.raises(CredentialUnavailable) as ei:
        await _borrow(b, meta.key_id)
    assert str(ei.value) == "store_unavailable"


async def test_internal_borrow_rejects_unknown_caller_and_purpose(
    broker: CredentialBroker,
) -> None:
    meta = await _store(broker)

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        return None

    for caller, purpose in (("admin", "sign_rest"), ("exchange_adapter", "anything")):
        with pytest.raises(CredentialUnavailable):
            await broker._borrow(meta.key_id, fn, caller, purpose)


async def test_idle_dek_is_swept_on_any_cache_access(store: Any, clock: FakeClock) -> None:
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, dek_cache_ttl_s=300)
    a = await _store(b)
    other = await _store(b, "OTHERKEY0000QQQQ")
    await _borrow(b, a.key_id)
    cached = b._cache._items[a.key_id][1]
    clock.t = 301
    await _borrow(b, other.key_id)  # touches the cache for a *different* key
    assert a.key_id not in b._cache._items and not any(cached)


async def test_broker_has_no_separate_decrypt_method(broker: CredentialBroker) -> None:
    """Structural: `open_` is called only from `_borrow`, which runs the caller check, fence
    and write-ahead audit in the same frame (C-2.9)."""
    import ast
    import inspect

    import candleviewer.secrets.broker as mod

    tree = ast.parse(inspect.getsource(mod))
    callers = {
        f.name
        for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)
        for n in ast.walk(f)
        if isinstance(n, ast.Attribute) and n.attr == "open_"
    }
    assert callers == {"_borrow"}
    assert not hasattr(broker, "_decrypt_and_call") and not hasattr(broker, "_tickets")


async def test_env_layers_refuse_a_live_row_without_relabelling(store: Any) -> None:
    """A demo broker whose store *ignores* the env filter still refuses a live row it reads
    unmodified: `_check_row` refuses the env mismatch before any audit or decrypt."""
    live = CredentialBroker(store, AuditLog(), kek(KEK_LIVE, 1, "live"), env_name="live")
    meta = await live.store("live", ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    store.activate(meta.key_id)

    async def unfiltered(key_id: Any, env_: str) -> Any:  # broken store env filter
        row = store.rows.get(key_id)
        return dict(row) if row is not None else None

    store.get = unfiltered
    audit = AuditLog()
    demo = CredentialBroker(store, audit, kek(), env_name="demo")
    with pytest.raises(CredentialUnavailable):
        await _borrow(demo, meta.key_id)
    assert audit.actions() == []  # refused before the borrow record (nothing decrypted)


async def test_aad_binds_the_sealing_env(store: Any) -> None:
    """With both env checks satisfied by a relabelled row (DB writer) whose wrap even opens for
    demo, the data AAD still binds the environment the row was sealed for, so GCM refuses it."""
    live = CredentialBroker(store, AuditLog(), kek(KEK_LIVE, 1, "live"), env_name="live")
    meta = await live.store("live", ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    store.activate(meta.key_id)
    _rewrap_for(store, meta.key_id, kek())
    store.rows[meta.key_id]["env"] = "demo"  # relabelled: passes read filter and row check
    demo = CredentialBroker(store, AuditLog(), kek(), env_name="demo")
    with pytest.raises(CredentialUnavailable):
        await _borrow(demo, meta.key_id)


async def test_destroy_fences_before_its_audit_completes(store: Any) -> None:
    """While destroy's write-ahead audit is in flight, a *new* borrow is already refused."""
    in_audit, release = asyncio.Event(), asyncio.Event()

    async def audit(action: str, fields: dict[str, str]) -> None:  # does not serialise writes
        if action == "security.credential_destroyed":
            in_audit.set()
            await release.wait()

    b = CredentialBroker(store, audit, kek())
    meta = await _store(b)
    destroy = asyncio.create_task(b.destroy(meta.key_id))
    await in_audit.wait()
    with pytest.raises(CredentialUnavailable):
        await _borrow(b, meta.key_id)
    release.set()
    await destroy


async def test_borrow_traceback_frame_locals_hold_no_plaintext(store: Any) -> None:
    """An exception through a borrow, rendered with frame locals (structlog `dict_tracebacks`
    / `capture_locals=True`), shows neither the plaintext nor the DEK (round-5 frames)."""
    import traceback

    b = CredentialBroker(store, AuditLog(), kek(), dek_cache_ttl_s=0)
    meta = await _store(b)

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError) as info:
        await _with(b, meta.key_id, fn)
    tb = info.value.__traceback__
    frames = []
    while tb is not None:
        frames.append(tb.tb_frame)
        tb = tb.tb_next
    borrow = [f for f in frames if f.f_code.co_name == "_borrow"]
    assert borrow
    for name in ("key", "secret", "dek", "k_s", "s_s"):
        assert borrow[0].f_locals[name] is None, name
    text = "".join(
        traceback.TracebackException.from_exception(info.value, capture_locals=True).format()
    )
    assert API_KEY not in text and API_SECRET not in text


@pytest.mark.parametrize("name", ["CredentialBroker", "BorrowHandle"])
def test_broker_classes_refuse_subclass_outside_secrets(name: str) -> None:
    import candleviewer.secrets.broker as broker_mod

    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (getattr(broker_mod, name),), {"__module__": "candleviewer.oms.evil"})
