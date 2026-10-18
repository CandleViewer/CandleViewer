"""SecretsService lifecycle: start, failure paths, zeroing, ack, degraded mode."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._kek import LoadedKek, PathKekSource
from candleviewer.secrets.errors import KekLoadError, KekUnavailable
from candleviewer.secrets.service import REMEDIATION, SecretsService, mint_borrower
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment
from tests.unit.credentials_m2._service_fakes import (
    _PASS,
    _borrow,
    _ctx,
    _Src,
    _store_one,
    _svc,
    _zeroed,
)
from tests.unit.credentials_m2._vectors import ACCOUNT, KEK_V1, AuditLog


async def test_start_with_kek_is_ok_and_audited_with_enrolment() -> None:
    audit, store = AuditLog(), InMemoryCredentialStore()
    svc, ctx = _svc(_Src(KEK_V1, 1), store=store, audit=audit), _ctx()
    await svc.start(ctx)
    assert svc.health().status is HealthStatus.OK and not ctx.oms_read_only_gate.is_read_only
    assert [a for a, _ in store.kcv_audit] == ["security.kek_enrolled"]  # with its row (#2266)
    assert audit.actions() == ["security.kek_loaded"]
    loaded = audit.records[0][1]
    assert loaded["env"] == "demo"
    assert loaded["kcv"] == LoadedKek(bytearray(KEK_V1), 1, env_name="demo").kcv().hex()
    res = await svc.verify_kek_possession()
    assert (res.version, res.kcv_ok, res.reason) == (1, True, None)
    meta = await _store_one(svc)
    assert await _borrow(svc, meta.key_id) == "ABCD1234"
    await svc.stop(0.1)
    assert svc.health().status is HealthStatus.STOPPED


async def test_kek_unavailable_degrades_latches_and_sets_state_gauge() -> None:
    audit = AuditLog()
    svc, ctx = _svc(_Src(None, 1), audit=audit), _ctx()
    await svc.start(ctx)
    rep = svc.health()
    assert rep.status is HealthStatus.DEGRADED and rep.detail == "kek_unavailable"
    gate = ctx.oms_read_only_gate
    assert gate.is_read_only and gate.reason_code == "secrets.kek_unavailable"
    assert gate.reason_text == REMEDIATION.format(reason="kek_unavailable")
    gate.clear(check_result=_PASS)
    assert gate.is_read_only
    assert m.kek_degraded_state._value.get() == 1
    assert audit.actions() == ["security.kek_load_failed"]
    with pytest.raises(KekUnavailable):
        await _borrow(svc, ACCOUNT)


async def test_kcv_store_error_degrades_with_typed_reason_and_zeroes() -> None:
    store = InMemoryCredentialStore()

    async def boom() -> list[Any]:
        raise RuntimeError("db down")

    store.kcv_versions = boom  # type: ignore[method-assign]
    src = _Src(KEK_V1, 1)
    svc, ctx = _svc(src, store=store), _ctx()
    await svc.start(ctx)
    assert svc.health().detail == "kcv_store_unavailable" and _zeroed(src)
    assert ctx.oms_read_only_gate.is_read_only


async def test_kek_loaded_audit_failure_zeroes_and_degrades() -> None:
    audit = AuditLog()
    audit.fail = True
    src = _Src(KEK_V1, 1)
    svc, ctx = _svc(src, audit=audit), _ctx()
    await svc.start(ctx)
    assert svc.health().detail == "audit_unavailable" and _zeroed(src)


async def test_cancelled_boot_latches_without_failure_audit() -> None:
    audit = AuditLog()
    gate = threading.Event()
    src = _Src(KEK_V1, 1, gate=gate)
    svc, ctx = _svc(src, audit=audit), _ctx()
    task = asyncio.create_task(svc.start(ctx))
    await asyncio.sleep(0)
    for _ in range(50):
        if task.done():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ctx.oms_read_only_gate.is_read_only and audit.actions() == []
    for _ in range(100):  # the abandoned worker finishes; its KEK is reaped
        if src.handed and _zeroed(src):
            break
        await asyncio.sleep(0.01)
    assert not src.handed or _zeroed(src)


async def test_load_timeout_degrades_and_reaps_late_kek(tmp_path: Path) -> None:
    gate = threading.Event()
    src = _Src(KEK_V1, 1, gate=gate)
    svc, ctx = _svc(src, timeout=0.05), _ctx()
    await svc.start(ctx)
    assert svc.health().detail == "kek_unavailable"
    gate.set()
    for _ in range(200):
        if src.handed:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    assert _zeroed(src)


async def test_abandoned_path_source_never_acks(tmp_path: Path) -> None:
    """A real PathKekSource abandoned on timeout zeroes its bytes and writes no ack."""
    k = tmp_path / "k"
    k.write_bytes(KEK_V1)
    k.chmod(0o400)
    src = PathKekSource(k, 1, allow_fifo=False, env_name="demo")
    src.abandoned.set()
    with pytest.raises(KekLoadError):
        src.load()


async def test_hardening_failure_degrades_in_live_only() -> None:
    live = _svc(_Src(KEK_V1, 1), hardened=False)
    await live.start(_ctx(environment=Environment.LIVE, kek_source="none"))
    assert live.health().detail == "process_hardening_failed"
    demo = _svc(_Src(KEK_V1, 1), hardened=False)
    await demo.start(_ctx())
    assert demo.health().status is HealthStatus.OK


async def test_live_fifo_without_ack_path_degrades() -> None:
    svc = _svc(_Src(KEK_V1, 1, fifo=True))
    await svc.start(_ctx(environment=Environment.LIVE, kek_source="none"))
    assert svc.health().detail == "kek_handle_permissions"


async def test_audit_outage_during_degrade_stays_degraded() -> None:
    audit = AuditLog()
    audit.fail = True
    svc, ctx = _svc(_Src(None, 1), audit=audit), _ctx()
    await svc.start(ctx)
    assert ctx.oms_read_only_gate.is_read_only


async def test_stop_zeroes_and_fails_closed() -> None:
    svc, ctx = _svc(_Src(KEK_V1, 1)), _ctx()
    await svc.start(ctx)
    meta = await _store_one(svc)
    await svc.stop(0.1)
    with pytest.raises(KekUnavailable):
        await _borrow(svc, meta.key_id)


async def test_stop_zeroes_then_cancels_the_brokers_in_flight_touch() -> None:
    """#2776: the service owns the broker, so its stop cancels and awaits the broker's in-flight
    `last_used_at` write, after the KEK is already zeroed; no task is left pending."""
    store: Any = InMemoryCredentialStore()
    entered = asyncio.Event()
    kek_gone_at_cancel: list[bool] = []
    svc = _svc(_Src(KEK_V1, 1), store=store)
    await svc.start(_ctx())
    broker = svc._require()

    async def stall(key_id: Any) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            kek_gone_at_cancel.append(broker._kek is None)

    meta = await _store_one(svc)
    store.touch_last_used = stall
    await _borrow(svc, meta.key_id)
    await entered.wait()
    (write,) = broker._touches.values()
    await svc.stop(0.1)
    assert write.cancelled() and kek_gone_at_cancel == [True] and not broker._touches
    assert asyncio.all_tasks() == {asyncio.current_task()}


def test_health_before_start_is_stopped() -> None:
    assert SecretsService().health().status is HealthStatus.STOPPED


def test_mint_borrower_rejects_unknown_caller() -> None:
    with pytest.raises(ValueError):
        mint_borrower(SecretsService(), "admin")


@pytest.mark.parametrize("name", ["SecretsService", "CredentialBorrower"])
def test_service_classes_refuse_subclass_outside_secrets(name: str) -> None:
    import candleviewer.secrets.service as service_mod

    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (getattr(service_mod, name),), {"__module__": "candleviewer.oms.evil"})


def test_rotating_broker_subclass_inside_secrets_allowed() -> None:
    from candleviewer.secrets._rotation import RotatingBroker
    from candleviewer.secrets.broker import CredentialBroker

    assert issubclass(RotatingBroker, CredentialBroker)
