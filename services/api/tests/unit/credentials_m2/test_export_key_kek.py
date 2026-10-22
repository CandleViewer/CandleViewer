"""The KEK's coverage of the audit export signing keys (#889 S6a-2a; ADR-0039 decision 6, Q3).

At a boot that enrols a KEK version, the signing key is part of the KEK's no-trust-on-first-use
proof only when no API key row is evidence at that version: its failed trial unwrap is then
`kek_mismatch`, and a store that cannot be read `kcv_store_unavailable`, both KEK failures that
latch order entry. When an API key row proved the KEK, the signing key is not trialled. On M2's
in-memory stores, with the fixed test KEKs; every signing key is generated in-process (C-13.5)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _export_key
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryCredentialStore, InMemoryExportKeyStore
from tests.unit.credentials_m2._service_fakes import _boot, _counted, _ctx, _Src, _store_one, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog, kek
from tests.unit.credentials_m2.test_export_key_store import GENERATED

DAMAGED = {"dek_ref": "ek1:" + "00" * 60}  # a signing key's wrap that opens under no KEK


def _real(version: int, under: LoadedKek, env_name: str = "demo") -> dict[str, Any]:
    """A key of `version` generated in-process for `env_name`, its DEK wrapped under `under`."""
    dek = env.new_dek()
    key = _export_key.generate(dek, env_name=env_name, version=version)
    ref = under.wrap_export_dek(dek, key_id=key.key_id)
    env.zero(dek)
    named = {"id": uuid4(), "env": env_name, "version": version, "key_id": key.key_id}
    sealed = {"sealed_seed": key.sealed_seed, "dek_ref": ref, "kek_version": under.version}
    return named | {"public_key": key.public_key} | sealed


async def _signing_key(**change: Any) -> InMemoryExportKeyStore:
    """An environment's signing key, version 1, wrapped under KEK v1, its row then `change`d."""
    keys = InMemoryExportKeyStore()
    assert await keys.insert_first(_real(1, kek(KEK_V1, 1)), audit=GENERATED)
    keys.rows[0] |= change
    return keys


async def _enrolling(
    keys: Any, src: _Src, store: Any = None, prev: _Src | None = None
) -> tuple[SecretsService, Any]:
    """A boot whose KEK version is not enrolled yet (a fresh lineage, or its row lost)."""
    stores = _counted() | {"export_keys": keys}
    svc, ctx = _svc(src, prev, store=store or InMemoryCredentialStore(), **stores), _ctx()
    await svc.start(ctx)
    return svc, ctx


async def test_with_no_api_key_row_the_signing_key_is_the_kek_s_proof() -> None:
    """A wrong KEK fails the signing key's trial unwrap: `kek_mismatch`, latched, nothing
    enrolled, so it never pins the lineage. The right one enrols."""
    keys, store = await _signing_key(), InMemoryCredentialStore()
    svc, ctx = await _enrolling(keys, _Src(KEK_V2, 1), store)  # another KEK, as v1
    assert (svc.health().detail, ctx.oms_read_only_gate.is_read_only) == ("kek_mismatch", True)
    assert store.kcvs == {}
    svc, ctx = await _enrolling(keys, _Src(KEK_V1, 1), store)
    assert (svc.health().status, list(store.kcvs)) == (HealthStatus.OK, [("demo", 1)])


async def test_a_signing_key_store_unreadable_at_enrolment_latches_with_the_store_reason() -> None:
    keys = await _signing_key()

    async def down(env: str) -> dict[str, Any] | None:
        raise RuntimeError("store down")

    setattr(keys, "active", down)  # noqa: B010 -- the signing keys cannot be read
    svc, ctx = await _enrolling(keys, _Src(KEK_V1, 1))
    assert (svc.health().detail, ctx.oms_read_only_gate.reason_code) == (
        "kcv_store_unavailable", "secrets.kek_unavailable"
    )  # fmt: skip


async def test_with_an_api_key_row_as_evidence_the_signing_key_is_not_trialled() -> None:
    """The API key row proves the KEK; a signing key whose wrap opens under none is not read
    at the enrolment, so the KEK enrols and nothing latches: the boot's own check of the key
    then makes export alone unavailable (#889 S6a-2b)."""
    store = InMemoryCredentialStore()
    await _store_one(await _boot(store, _Src(KEK_V1, 1)))
    store.kcvs.clear()  # its enrolment lost: this boot must prove its KEK again
    svc, ctx = await _enrolling(await _signing_key(**DAMAGED), _Src(KEK_V1, 1), store)
    assert (list(store.kcvs), ctx.oms_read_only_gate.is_read_only) == ([("demo", 1)], False)
    assert (await svc.verify_kek_possession()).kcv_ok
    assert svc.health().detail == "export_key_unopenable"


@pytest.mark.parametrize("change", [{}, DAMAGED], ids=["opens", "damaged"])
async def test_a_known_kek_never_trials_the_signing_key(change: dict[str, Any]) -> None:
    """Once its KCV is enrolled, no boot reads the signing key to prove the KEK again."""
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    _, ctx = await _enrolling(await _signing_key(**change), _Src(KEK_V1, 1), store)
    assert not ctx.oms_read_only_gate.is_read_only


async def test_a_signing_key_wrapped_at_another_version_is_not_trialled() -> None:
    """The rotation boot enrols v2 while the key is still wrapped at v1: v2 cannot open it and is
    not asked to, so v2 enrols and nothing latches."""
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))  # v1 enrolled, no API key row
    keys = await _signing_key()
    _, ctx = await _enrolling(keys, _Src(KEK_V2, 2), store, prev=_Src(KEK_V1, 1))
    assert (sorted(store.kcvs), ctx.oms_read_only_gate.is_read_only) == (
        [("demo", 1), ("demo", 2)], False
    )  # fmt: skip


async def test_a_cancelled_trial_propagates_and_is_never_a_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = await _signing_key()

    def cancelled(*_: object, **__: object) -> bytearray:
        raise asyncio.CancelledError

    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", cancelled)
    broker = RotatingBroker(InMemoryCredentialStore(), AuditLog(), kek(KEK_V1, 1))
    with pytest.raises(asyncio.CancelledError):
        await broker._trial_export(kek(KEK_V1, 1), keys)
