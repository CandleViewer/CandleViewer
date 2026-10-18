"""KEK re-wrap preconditions inside M2 (#2266 PR D1). `rewrap_deks` acts only in the boot staged
for the rotation the call names, one run at a time; it latches order entry before the run's opening
record, without a KEK page, and audits each refusal, which latches and moves nothing. The run counts
the auth keyring rows, and never reads complete without a wired keyring store (#3505)."""

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
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _staged, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, AuditLog

_REFUSED, _STARTED = "security.kek_rotation_refused", "security.kek_rotation_started"
_OWNER = {"actor_kind": "user", "actor_role": "owner", "actor_user_id": "owner-1"}
Booted = tuple[SecretsService, Any, InMemoryCredentialStore]


async def _alone(audit: AuditLog, raw: bytes | None = KEK_V1) -> Booted:
    """A boot with one KEK (`raw`, at v1) and no previous one."""
    store = InMemoryCredentialStore()
    svc, ctx = _svc(_Src(raw, 1), store=store, audit=audit), _ctx()
    await svc.start(ctx)
    return svc, ctx, store


async def _rewrap(svc: SecretsService, v: int = 2, env: str = "demo") -> Any:
    return await svc.rewrap_deks(v, environment=env, actor_user_id="owner-1", actor_role="owner")


async def test_a_staged_run_latches_order_entry_before_its_opening_record() -> None:
    audit = AuditLog()
    svc, ctx, store = await _staged(audit, InMemoryAuthKeyStore())
    gate, booted, at_latch = ctx.oms_read_only_gate, len(audit.records), list[int]()
    gate.subscribe(lambda *_: at_latch.append(len(audit.records)))
    m.kek_degraded_state.set(0)
    rep = await _rewrap(svc)
    assert (rep.rewrapped, rep.remaining, rep.complete) == (2, 0, True)
    assert at_latch == [booted] and audit.actions()[booted] == _STARTED
    assert gate.reason_code == "secrets.kek_rotation" and m.kek_degraded_state._value.get() == 0
    assert (svc.health().status, svc.health().detail) == (HealthStatus.DEGRADED, "kek_rotation")
    records = audit.records[booted:] + store.rewrap_audit  # the actor is on every record
    assert len(records) == 4 and all(_OWNER.items() <= f.items() for _, f in records)


@pytest.mark.parametrize(
    ("boot", "to_version", "env"),
    [(_alone, 1, "demo"), (_staged, 3, "demo"), (_staged, 2, "live")],
    ids=["no_previous_kek", "other_version", "other_environment"],
)
async def test_a_call_unlike_the_staged_boot_is_refused_and_audited_once(
    boot: Callable[[AuditLog], Awaitable[Booted]], to_version: int, env: str
) -> None:
    audit = AuditLog()
    svc, ctx, store = await boot(audit)
    with pytest.raises(KekRotationError) as refused:
        await _rewrap(svc, to_version, env)
    assert refused.value.code == "kek_rotation_not_staged"
    assert not ctx.oms_read_only_gate.is_read_only
    assert all(r["kek_version"] == 1 for r in store.rows.values())  # no row moved
    [(action, fields)] = [r for r in audit.records if "rotation" in r[0]]
    expected = {"reason": "kek_rotation_not_staged", "requested_env": env, "env": "demo"}
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
