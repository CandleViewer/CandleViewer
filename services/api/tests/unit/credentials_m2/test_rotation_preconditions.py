"""KEK re-wrap preconditions inside M2 (#2266 PR D1). `rewrap_deks` acts only in the boot staged
for the rotation the call names, one run at a time; it latches order entry once, before the first
run's opening record, without a KEK page, and audits each refusal, which latches and moves nothing.
The run counts the auth keyring rows, and never reads complete without a keyring store (#3505)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import Mock

import pytest

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.errors import KekRotationError, KekUnavailable
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryCredentialStore
from tests.unit.credentials_m2._service_fakes import (
    KEK_V3,
    _boot,
    _ctx,
    _Src,
    _staged,
    _store_one,
    _svc,
)
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog

_REFUSED, _STARTED = "security.kek_rotation_refused", "security.kek_rotation_started"
_ROTATION = "secrets.kek_rotation"
_OWNER = {"actor_kind": "user", "actor_role": "owner", "actor_user_id": "owner-1"}
_LONG_ENV = "demo" + "x" * 36  # caller text of 40 characters
Booted = tuple[SecretsService, Any, InMemoryCredentialStore]


async def _alone(audit: AuditLog, raw: bytes | None = KEK_V1) -> Booted:
    """A boot with one KEK (`raw`, at v1) and no previous one."""
    store = InMemoryCredentialStore()
    svc, ctx = _svc(_Src(raw, 1), store=store, audit=audit), _ctx()
    await svc.start(ctx)
    return svc, ctx, store


async def _stranded(audit: AuditLog) -> Booted:
    """A key left under v1 and one under v2, then the boot staged for v3 beside v2: the v1 row is
    stranded (#2266 PR C), and a rotation to v3 is staged."""
    store = InMemoryCredentialStore()
    await _store_one(await _boot(store, _Src(KEK_V1, 1)))
    await _store_one(await _boot(store, _Src(KEK_V2, 2), _Src(KEK_V1, 1)))
    srcs, keyring = (_Src(KEK_V3, 3), _Src(KEK_V2, 2)), InMemoryAuthKeyStore()
    svc, ctx = _svc(*srcs, store=store, audit=audit, auth_keys=keyring), _ctx()
    await svc.start(ctx)
    return svc, ctx, store


async def _rewrap(svc: SecretsService, v: int = 2, env: str = "demo") -> Any:
    return await svc.rewrap_deks(v, environment=env, actor_user_id="owner-1", actor_role="owner")


async def test_a_staged_run_latches_order_entry_before_its_opening_record() -> None:
    audit = AuditLog()
    svc, ctx, _ = await _staged(audit, InMemoryAuthKeyStore())
    gate, booted, at_latch = ctx.oms_read_only_gate, len(audit.records), list[int]()
    gate.subscribe(lambda *_: at_latch.append(len(audit.records)))
    await _rewrap(svc)
    assert at_latch == [booted] and audit.actions()[booted] == _STARTED
    assert gate.reason_code == _ROTATION


async def test_a_staged_run_reads_degraded_without_a_kek_page() -> None:
    svc, _, _ = await _staged(AuditLog(), InMemoryAuthKeyStore())
    m.kek_degraded_state.set(0)
    await _rewrap(svc)
    assert (svc.health().status, svc.health().detail) == (HealthStatus.DEGRADED, "kek_rotation")
    assert m.kek_degraded_state._value.get() == 0


async def test_every_record_of_a_staged_run_carries_the_owner() -> None:
    audit = AuditLog()
    svc, _, store = await _staged(audit, InMemoryAuthKeyStore())
    booted = len(audit.records)
    await _rewrap(svc)
    records = audit.records[booted:] + store.rewrap_audit  # opening, two rows, terminal
    assert len(records) == 4 and all(_OWNER.items() <= f.items() for _, f in records)


async def test_a_second_run_does_not_latch_order_entry_again() -> None:
    """The runbook's "repeat until complete" pushes no second read-only notice to clients."""
    svc, ctx, _ = await _staged(AuditLog(), InMemoryAuthKeyStore())
    notices: list[str | None] = []
    ctx.oms_read_only_gate.subscribe(lambda _closed, code, _text: notices.append(code))
    await _rewrap(svc)
    await _rewrap(svc)
    assert notices == [_ROTATION]


@pytest.mark.parametrize(
    ("boot", "to_version", "env", "recorded"),
    [
        (_alone, 1, "demo", "demo"),
        (_staged, 3, "demo", "demo"),
        (_staged, 2, "live", "live"),
        (_staged, 2, _LONG_ENV, "demo" + "x" * 12),  # its first 16 characters
    ],
    ids=["no_previous_kek", "other_version", "other_environment", "long_environment"],
)
async def test_a_call_unlike_the_staged_boot_is_refused_and_audited_once(
    boot: Callable[[AuditLog], Awaitable[Booted]], to_version: int, env: str, recorded: str
) -> None:
    audit = AuditLog()
    svc, ctx, store = await boot(audit)
    with pytest.raises(KekRotationError) as refused:
        await _rewrap(svc, to_version, env)
    assert refused.value.code == "kek_rotation_not_staged"
    assert not ctx.oms_read_only_gate.is_read_only
    assert all(r["kek_version"] == 1 for r in store.rows.values())  # no row moved
    [(action, fields)] = [r for r in audit.records if "rotation" in r[0]]
    expected = {"reason": "kek_rotation_not_staged", "requested_env": recorded, "env": "demo"}
    expected |= {"to_version": str(to_version)}
    assert action == _REFUSED and {**_OWNER, **expected}.items() <= fields.items()


async def test_a_call_while_a_run_is_in_progress_is_refused() -> None:
    audit = AuditLog()
    svc, _, store = await _staged(audit)
    entered, release, real = asyncio.Event(), asyncio.Event(), store.count_at_kek_version

    async def held(version: int, env: str) -> int:
        if not entered.is_set():  # only the first run waits, so a second one never hangs the test
            entered.set()
            await release.wait()
        return await real(version, env)

    store.count_at_kek_version = held  # type: ignore[method-assign]
    first = asyncio.create_task(_rewrap(svc))
    await entered.wait()
    with pytest.raises(KekRotationError) as refused:
        await _rewrap(svc)
    release.set()
    assert refused.value.code == "kek_rotation_in_progress"
    assert ((await first).rewrapped, audit.actions().count(_REFUSED)) == (2, 1)


async def test_a_call_after_a_failed_run_is_not_refused_as_in_progress() -> None:
    """The contract's recovery from every 503: calling again resumes the run."""
    audit = AuditLog()
    svc, _, _ = await _staged(audit, InMemoryAuthKeyStore())
    audit.fail = True
    with pytest.raises(KekRotationError) as stopped:
        await _rewrap(svc)
    assert stopped.value.code == "audit_unavailable"
    audit.fail = False
    rep = await _rewrap(svc)
    assert (rep.rewrapped, rep.complete) == (2, True)


async def test_a_call_after_a_completed_run_is_not_refused_as_in_progress() -> None:
    svc, _, _ = await _staged(AuditLog(), InMemoryAuthKeyStore())
    await _rewrap(svc)
    rep = await _rewrap(svc)
    assert (rep.rewrapped, rep.remaining, rep.complete) == (0, 0, True)


async def test_a_process_without_a_usable_kek_refuses_with_kek_unavailable() -> None:
    audit = AuditLog()
    svc, ctx, _ = await _alone(audit, None)
    with pytest.raises(KekUnavailable):
        await _rewrap(svc)
    assert ctx.oms_read_only_gate.reason_code == "secrets.kek_unavailable"  # the boot's latch
    assert [f["reason"] for a, f in audit.records if a == _REFUSED] == ["kek_unavailable"]


async def test_a_refusal_whose_record_cannot_be_written_answers_audit_unavailable() -> None:
    audit = AuditLog()
    svc, ctx, _ = await _staged(audit)
    audit.fail = True
    with pytest.raises(KekRotationError) as refused:
        await _rewrap(svc, 3)
    assert refused.value.code == "audit_unavailable" and not ctx.oms_read_only_gate.is_read_only


def _audit_down(audit: AuditLog, store: InMemoryCredentialStore) -> None:
    audit.fail = True


def _store_down(audit: AuditLog, store: InMemoryCredentialStore) -> None:
    async def down(version: int, env: str) -> int:
        raise RuntimeError("store down")

    store.count_at_kek_version = down  # type: ignore[method-assign]


@pytest.mark.parametrize(
    ("brake", "code"),
    [(_audit_down, "audit_unavailable"), (_store_down, "store_unavailable")],
    ids=["audit", "store"],
)
async def test_a_run_that_fails_after_the_latch_keeps_it(
    brake: Callable[[AuditLog, InMemoryCredentialStore], None], code: str
) -> None:
    audit = AuditLog()
    svc, ctx, store = await _staged(audit)
    brake(audit, store)
    with pytest.raises(KekRotationError) as stopped:
        await _rewrap(svc)
    assert stopped.value.code == code
    assert ctx.oms_read_only_gate.reason_code == "secrets.kek_rotation"


class _HungAudit(AuditLog):
    """An audit sink whose writes never return once `hung` is set."""

    hung = False

    async def __call__(self, action: str, fields: dict[str, str]) -> None:
        if self.hung:
            await asyncio.Event().wait()
        await super().__call__(action, fields)


async def test_a_run_whose_audit_sink_hangs_answers_audit_unavailable() -> None:
    """The opening record's write hangs until the broker's bound ends it (`audit_timeout`). At 0 it
    fires at the next turn of the loop, before the service's own 2 s bound, with no wall clock."""
    audit = _HungAudit()
    svc, _, _ = await _staged(audit, InMemoryAuthKeyStore())
    audit.hung = True
    svc._require()._timeout = 0  # the broker's I/O bound
    with pytest.raises(KekRotationError) as stopped:
        async with asyncio.timeout(5):  # ends a regression's hang
            await _rewrap(svc)
    assert stopped.value.code == "audit_unavailable"


async def test_a_rotation_on_a_stranded_boot_keeps_kek_rows_stranded_in_health() -> None:
    svc, _, _ = await _stranded(AuditLog())
    await _rewrap(svc, 3)
    health = svc.health()
    assert (health.status, health.detail) == (HealthStatus.DEGRADED, "kek_rows_stranded")


async def test_a_rotation_on_a_stranded_boot_latches_the_reason_rewrap_kek_names() -> None:
    """Unlike `accounts/selfcheck.py`, it replaces the held latch's reason: both are M2's, the
    contract names this one, and health keeps the stranded one."""
    svc, ctx, _ = await _stranded(AuditLog())
    gate = ctx.oms_read_only_gate
    stranded = gate.reason_code
    await _rewrap(svc, 3)
    assert (stranded, gate.reason_code) == ("secrets.kek_rows_stranded", _ROTATION)


async def test_a_run_with_no_keyring_store_never_reads_a_checked_zero() -> None:
    """#3505: every API key row moved, yet with no keyring store wired the run is incomplete."""
    audit = AuditLog()
    svc, _, _ = await _staged(audit)
    rep = await _rewrap(svc)
    assert (rep.rewrapped, rep.remaining, rep.complete) == (2, 0, False)
    action, fields = audit.records[-1]
    assert (action, fields["auth_left"]) == ("security.kek_rotation_incomplete", "unchecked")


async def test_the_keyring_fake_refuses_another_environment_as_the_adapter_does() -> None:
    with pytest.raises(ValueError, match="process environment"):
        await InMemoryAuthKeyStore("demo").count_at_kek_version(1, "live")


def test_the_real_backend_hands_m2_the_keyring_store_of_its_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3505: the production `rewrap_deks` counts the auth keyring rows of its environment."""
    from candleviewer import app
    from candleviewer.admin import wiring
    from candleviewer.settings import Environment, Settings
    from candleviewer.storage.repositories.auth_keys_sqlalchemy import SqlAlchemyAuthKeyStore

    monkeypatch.setattr(wiring, "SecretsService", spy := Mock(wraps=SecretsService))
    settings = Settings(storage_backend="real", environment=Environment.TESTNET)
    app._build_secrets(settings, app._build_audit(settings))
    keyring = spy.call_args.kwargs["auth_keys"]
    assert isinstance(keyring, SqlAlchemyAuthKeyStore) and keyring._env == "testnet"
