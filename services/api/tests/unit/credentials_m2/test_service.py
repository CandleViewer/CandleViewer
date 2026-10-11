"""SecretsService lifecycle: KEK load, KCV, fail-closed degraded mode, live refusal."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.net.binding_check import BindingCheckResult
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import SecretsService
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.errors import KekLoadError, KekSourceNotPermitted, KekUnavailable
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import REMEDIATION
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment, Settings
from tests.unit.credentials_m2.conftest import ACCOUNT, KEK_V1, KEK_V2, SNAPSHOT, AuditLog

_PASS = BindingCheckResult(safe=True, bound_addresses=(), reason_code="ok", reason_text="ok")


class _Src:
    def __init__(self, raw: bytes | None, version: int = 1) -> None:
        self.raw, self.version = raw, version

    def load(self) -> LoadedKek:
        if self.raw is None:
            raise KekLoadError("kek_unavailable")
        return LoadedKek(bytearray(self.raw), self.version)


class _Kcv:
    def __init__(self) -> None:
        self.kcvs: dict[int, bytes] = {}

    async def kcv_for(self, version: int) -> bytes | None:
        return self.kcvs.get(version)

    async def record_kcv(self, version: int, kcv: bytes) -> None:
        self.kcvs[version] = kcv


def _ctx(**kw: Any) -> Any:
    settings = Settings(_env_file=None, **kw)  # type: ignore[call-arg]  # pydantic-settings kwarg
    return SimpleNamespace(settings=settings, oms_read_only_gate=ReadOnlyGate())


def _svc(raw: bytes | None, *, prev: bytes | None = None, kcv: _Kcv | None = None,
         audit: AuditLog | None = None) -> SecretsService:  # fmt: skip
    def factory(settings: Settings, *, previous: bool = False) -> _Src:
        return _Src(prev, 1) if previous else _Src(raw, settings.kek_version)

    return SecretsService(
        store=InMemoryCredentialStore(), kcv_store=kcv or _Kcv(), audit=audit or AuditLog(),
        source_factory=factory, harden=lambda: None,
    )  # fmt: skip


async def test_start_with_kek_is_ok_and_audited() -> None:
    audit = AuditLog()
    svc, ctx = _svc(KEK_V1, audit=audit), _ctx()
    await svc.start(ctx)
    assert svc.health().status is HealthStatus.OK
    assert not ctx.oms_read_only_gate.is_read_only
    assert audit.actions() == ["security.kek_loaded"]
    res = await svc.verify_kek_possession()
    assert (res.version, res.kcv_ok, res.reason) == (1, True, None)
    meta = await svc.broker.store(ACCOUNT, "l", Secret("ABCD1234"), Secret("s"), SNAPSHOT)

    async def fn(k: Secret[str], s: Secret[str]) -> str:
        return k.reveal()

    assert await svc.with_credentials(meta.key_id, fn, caller_module="m", purpose="p") == "ABCD1234"
    await svc.stop(0.1)
    assert svc.health().status is HealthStatus.STOPPED


async def test_kek_unavailable_degrades_and_latches_gate(caplog: pytest.LogCaptureFixture) -> None:
    audit = AuditLog()
    svc, ctx = _svc(None, audit=audit), _ctx()
    await svc.start(ctx)
    rep = svc.health()
    assert rep.status is HealthStatus.DEGRADED and rep.detail == "kek_unavailable"
    gate = ctx.oms_read_only_gate
    assert gate.is_read_only and gate.reason_code == "secrets.kek_unavailable"
    assert gate.reason_text == REMEDIATION.format(reason="kek_unavailable")
    gate.clear(check_result=_PASS)  # hourly mesh check passing must NOT un-degrade
    assert gate.is_read_only
    gate.trip(reason_code="net.other", reason_text="x")
    assert gate.reason_code == "secrets.kek_unavailable"
    assert audit.actions() == ["security.kek_load_failed"]
    with pytest.raises(KekUnavailable):
        _ = svc.broker
    res = await svc.verify_kek_possession()
    assert (res.kcv_ok, res.reason) == (False, "kek_unavailable")


async def test_kcv_mismatch_degrades() -> None:
    kcv = _Kcv()
    first = _svc(KEK_V1, kcv=kcv)
    await first.start(_ctx())
    svc, ctx = _svc(KEK_V2, kcv=kcv), _ctx()
    await svc.start(ctx)
    assert svc.health().detail == "kek_mismatch" and ctx.oms_read_only_gate.is_read_only


async def test_prev_kek_loaded_and_rewrap_reports_counts() -> None:
    kcv = _Kcv()
    store = InMemoryCredentialStore()
    v1 = _svc(KEK_V1, kcv=kcv)
    v1._store = store
    await v1.start(_ctx())
    await v1.broker.store(ACCOUNT, "l", Secret("ABCD1234"), Secret("s"), SNAPSHOT)
    v2 = _svc(KEK_V2, prev=KEK_V1, kcv=kcv)
    v2._store = store
    await v2.start(_ctx(kek_version=2, kek_prev_handle="/p"))
    rep = await v2.rewrap_deks(2)
    assert (rep.rewrapped, rep.remaining) == (1, 0)


async def test_wrong_prev_kek_degrades() -> None:
    kcv = _Kcv()
    await _svc(KEK_V1, kcv=kcv).start(_ctx())
    svc = _svc(KEK_V2, prev=bytes(32), kcv=kcv)
    await svc.start(_ctx(kek_version=2, kek_prev_handle="/p"))
    assert svc.health().detail == "kek_mismatch"


async def test_audit_outage_during_degrade_stays_degraded() -> None:
    audit = AuditLog()
    audit.fail = True
    svc, ctx = _svc(None, audit=audit), _ctx()
    await svc.start(ctx)
    assert ctx.oms_read_only_gate.is_read_only


async def test_runtime_kek_loss_fails_closed() -> None:
    svc, ctx = _svc(KEK_V1), _ctx()
    await svc.start(ctx)
    meta = await svc.broker.store(ACCOUNT, "l", Secret("ABCD1234"), Secret("s"), SNAPSHOT)
    await svc.lose_kek(ctx)
    assert ctx.oms_read_only_gate.is_read_only

    async def fn(k: Secret[str], s: Secret[str]) -> None:
        return None

    with pytest.raises(KekUnavailable):
        await svc.with_credentials(meta.key_id, fn, caller_module="m", purpose="p")


async def test_file_source_in_live_is_fatal() -> None:
    svc = SecretsService(store=InMemoryCredentialStore(), audit=AuditLog(), harden=lambda: None)
    with pytest.raises(KekSourceNotPermitted):
        await svc.start(_ctx(environment=Environment.LIVE, kek_source="file"))


async def test_no_store_fake_backend_disabled_not_degraded() -> None:
    svc, ctx = SecretsService(harden=lambda: None), _ctx(kek_source="none")
    await svc.start(ctx)
    assert not ctx.oms_read_only_gate.is_read_only
    assert svc.health().status is HealthStatus.DEGRADED
    with pytest.raises(KekUnavailable):
        _ = svc.broker


async def test_no_store_in_live_degrades() -> None:
    svc = SecretsService(harden=lambda: None)
    ctx = _ctx(environment=Environment.LIVE, kek_source="none")
    await svc.start(ctx)
    assert ctx.oms_read_only_gate.is_read_only


async def test_no_audit_sink_refuses() -> None:
    svc = SecretsService(store=InMemoryCredentialStore(), harden=lambda: None,
                         source_factory=lambda s, previous=False: _Src(KEK_V1))  # fmt: skip
    with pytest.raises(KekUnavailable):
        await svc.start(_ctx())


def test_health_before_start_is_stopped() -> None:
    assert SecretsService().health().status is HealthStatus.STOPPED


async def test_degraded_blocks_order_placement() -> None:
    from candleviewer.oms.validator import OrderPlacementRefused, Validator

    svc, ctx = _svc(None), _ctx()
    await svc.start(ctx)
    with pytest.raises(OrderPlacementRefused) as ei:
        Validator(read_only_gate=ctx.oms_read_only_gate).assert_order_placement_allowed()
    assert ei.value.reason_code == "secrets.kek_unavailable"


async def test_degraded_publishes_system_notice() -> None:
    import asyncio

    from candleviewer.net.system_topic import register_system_topic_subscriber

    published: list[Any] = []

    class _Bus:
        async def publish(self, topic: Any, payload: Any) -> None:
            published.append((topic, payload))

    svc, ctx = _svc(None), _ctx()
    pub = register_system_topic_subscriber(
        bus=_Bus(),  # type: ignore[arg-type]  # structural fake bus
        env="demo",
        read_only_gate=ctx.oms_read_only_gate,
    )
    await svc.start(ctx)
    await asyncio.gather(*pub._pending)
    assert published and published[0][1]["reason_code"] == "secrets.kek_unavailable"
    assert published[0][1]["severity"] == "critical" and published[0][1]["read_only"] is True
