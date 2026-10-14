"""Broker safety: status gating, destroy fence, plaintext zeroing, timeouts (E27-T02 review)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from candleviewer.secrets import KEY_ID_SLOT
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
    SNAPSHOT,
    AuditLog,
    FakeClock,
    kek,
)


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
    assert len(touched) == 2


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


async def test_store_refuses_other_environment(store: Any) -> None:
    b = CredentialBroker(store, AuditLog(), kek(), env_name="demo")
    with pytest.raises(CredentialUnavailable) as ei:
        await b.store("live", ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    assert str(ei.value) == "environment_mismatch" and not store.rows


async def test_demo_bound_broker_never_reads_a_live_row(store: Any) -> None:
    live = CredentialBroker(store, AuditLog(), kek(), env_name="live")
    meta = await live.store("live", ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    store.activate(meta.key_id)
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
    from candleviewer.secrets import _metrics as m

    async def stall(key_id: Any) -> None:
        await asyncio.Event().wait()

    store.touch_last_used = stall
    b = CredentialBroker(store, AuditLog(), kek(), clock=clock, io_timeout_s=0.01)
    meta = await _store(b)
    before = m.credential_touch_failures_total._value.get()
    assert (await _borrow(b, meta.key_id))[0] == API_KEY  # signing never blocked by metadata
    assert m.credential_touch_failures_total._value.get() == before + 1


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
    live = CredentialBroker(store, AuditLog(), kek(), env_name="live")
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
    """With both env checks satisfied by a relabelled row (DB writer), the AAD still binds
    the environment the row was sealed for, so GCM refuses it."""
    live = CredentialBroker(store, AuditLog(), kek(), env_name="live")
    meta = await live.store("live", ACCOUNT, "l", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    store.activate(meta.key_id)
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
