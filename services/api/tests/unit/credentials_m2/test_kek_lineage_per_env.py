"""Per-environment KEK lineage (#2338): no process under non-live custody can unwrap a live DEK.

Two `SecretsService`s share one `InMemoryCredentialStore`, the stand-in for the shared Postgres
(the real one: `tests/integration/storage/test_kek_lineage_shared_db.py`). Synthetic KEKs only.
"""

from __future__ import annotations

from typing import Any

import pytest
from cryptography.exceptions import InvalidTag

from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import _envelope as env
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import SecretsService
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _Spy
from tests.unit.credentials_m2._service_fakes import KEK_V3, _borrow, _ctx, _Src, _svc, _zeroed
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
    API_KEY,
    API_SECRET,
    KEK_LIVE,
    KEK_V1,
    KEK_V2,
    SNAPSHOT,
    AuditLog,
    kek,
)


async def _start(
    store: InMemoryCredentialStore,
    env_name: str,
    *srcs: _Src,
    audit: AuditLog | None = None,
    hardened: bool = True,
    **settings: Any,
) -> tuple[SecretsService, Any]:
    svc = _svc(*srcs, store=store, audit=audit, hardened=hardened)
    ctx = _ctx(environment=env_name, **settings)
    await svc.start(ctx)
    return svc, ctx


async def _stored(svc: SecretsService, env_name: str) -> Any:
    """One signable credential at version 1, stored by `svc` in its own environment."""
    broker = svc._require()
    meta = await broker.store(env_name, ACCOUNT, "k", Secret(API_KEY), Secret(API_SECRET), SNAPSHOT)
    broker._store.activate(meta.key_id)  # type: ignore[attr-defined]  # in-memory fake helper
    return meta.key_id


async def _lineages(store: InMemoryCredentialStore) -> list[tuple[str, int]]:
    return sorted((e, v) for e, v, _, _ in await store.kcv_versions())


def _opens(raw: bytes, dek_ref: str, aad: bytes) -> bool:
    try:
        env.open_(raw, bytes.fromhex(dek_ref.partition(":")[2]), aad)
    except InvalidTag:
        return False
    return True


def _to_v1(store: InMemoryCredentialStore, key_id: Any, raw: bytes) -> None:
    """Re-wrap the row's DEK as before #2338: `v1:`, AAD `cv-dek-v1 ‖ id ‖ version`, no env."""
    row = store.rows[key_id]
    dek = kek(raw).unwrap_dek(row["dek_ref"], credential_id=key_id)
    row["dek_ref"] = "v1:" + env.seal(raw, dek, env.aad(b"cv-dek-v1", key_id.bytes, b"1")).hex()


@pytest.mark.parametrize("env_name", ["demo", "testnet"])
@pytest.mark.parametrize(
    ("cur", "prev"),
    [((KEK_LIVE, 1), None), ((KEK_LIVE, 2), None), ((KEK_V1, 2), (KEK_LIVE, 1))],
    ids=["current-v1", "current-v2", "previous"],
)
async def test_live_kek_refused_outside_live(
    env_name: str, cur: tuple[bytes, int], prev: tuple[bytes, int] | None
) -> None:
    """Threat model AC-02: the live KEK never loads under non-live custody (file, lax hardening)."""
    store = InMemoryCredentialStore()
    await _start(store, "live", _Src(KEK_LIVE, 1))
    srcs = [_Src(*cur)] + ([_Src(*prev)] if prev else [])
    audit = AuditLog()
    svc, ctx = await _start(store, env_name, *srcs, audit=audit, hardened=False, kek_source="file")
    assert svc.health().detail == "kek_reused"
    assert ctx.oms_read_only_gate.is_read_only and all(_zeroed(s) for s in srcs)
    fields = {"actor_kind": "system", "actor_role": "secrets", "reason": "kek_reused"}
    assert audit.records == [("security.kek_load_failed", {**fields, "env": env_name})]
    assert await _lineages(store) == [("live", 1)]


async def test_other_environment_versions_do_not_affect_a_live_boot() -> None:
    """Threat model AC-31: a demo lineage that moved on (and retired its v1) never blocks live."""
    store = InMemoryCredentialStore()
    setup = [
        await _start(store, "live", _Src(KEK_LIVE, 1)),
        await _start(store, "demo", _Src(KEK_V1, 1)),
        await _start(store, "demo", _Src(KEK_V2, 2), _Src(KEK_V1, 1)),
    ]
    store.retired.add(("demo", 1))  # runbook step 3, set by hand after the demo rotation
    audit = AuditLog()
    svc, ctx = await _start(store, "live", _Src(KEK_LIVE, 1), audit=audit)
    # The outcome first, so the run at f8886389 fails on the defect, not on the setup.
    assert svc.health().status is HealthStatus.OK, svc.health().detail
    assert audit.actions() == ["security.kek_loaded"] and not ctx.oms_read_only_gate.is_read_only
    assert [s.health().status for s, _ in setup] == [HealthStatus.OK] * 3
    assert await _lineages(store) == [("demo", 1), ("demo", 2), ("live", 1)]


@pytest.mark.parametrize("other", ["demo", "testnet"])
@pytest.mark.parametrize("live_first", [True, False])
async def test_empty_database_each_environment_starts_its_own_lineage(
    other: str, live_first: bool
) -> None:
    store = InMemoryCredentialStore()
    boots = [("live", KEK_LIVE), (other, KEK_V1)]
    for env_name, raw in boots if live_first else boots[::-1]:
        audit = AuditLog()
        svc, _ = await _start(store, env_name, _Src(raw, 1), audit=audit)
        assert svc.health().status is HealthStatus.OK
        assert [(a, f["env"]) for a, f in audit.records] == [
            ("security.kek_enrolled", env_name),
            ("security.kek_loaded", env_name),
        ]
    assert await _lineages(store) == sorted([("live", 1), (other, 1)])


async def test_non_live_process_with_its_own_kek_cannot_open_a_live_row() -> None:
    store = InMemoryCredentialStore()
    live, _ = await _start(store, "live", _Src(KEK_LIVE, 1))
    key_id = await _stored(live, "live")
    demo, _ = await _start(store, "demo", _Src(KEK_V1, 1), hardened=False, kek_source="file")
    assert demo.health().status is HealthStatus.OK
    for env_name in ("live", "demo"):  # the demo KEK under either wrap AAD
        with pytest.raises(InvalidTag):
            kek(KEK_V1, 1, env_name).unwrap_dek(store.rows[key_id]["dek_ref"], credential_id=key_id)
    assert await store.get(key_id, "demo") is None
    with pytest.raises(CredentialUnavailable):
        await _borrow(demo, key_id)


async def test_kek_enrolled_outside_live_never_joins_the_live_lineage() -> None:
    store = InMemoryCredentialStore()
    await _start(store, "demo", _Src(KEK_V1, 1))
    live, ctx = await _start(store, "live", _Src(KEK_V1, 1))
    assert live.health().detail == "kek_reused" and ctx.oms_read_only_gate.is_read_only
    assert await _lineages(store) == [("demo", 1)]


async def _live_v1_v2(store: InMemoryCredentialStore) -> None:
    await _start(store, "live", _Src(KEK_LIVE, 1))
    await _start(store, "live", _Src(KEK_V2, 2), _Src(KEK_LIVE, 1))
    assert await _lineages(store) == [("live", 1), ("live", 2)]


async def test_version_sequence_still_holds_inside_one_environment() -> None:
    store = InMemoryCredentialStore()
    await _live_v1_v2(store)
    svc, _ = await _start(store, "live", _Src(KEK_V3, 4))
    assert svc.health().detail == "kek_version_out_of_sequence"


async def test_retired_version_stays_retired_inside_its_environment() -> None:
    store = InMemoryCredentialStore()
    await _live_v1_v2(store)
    store.retired.add(("live", 1))
    svc, _ = await _start(store, "live", _Src(KEK_LIVE, 1))
    assert svc.health().detail == "kek_retired"


async def test_no_trust_on_first_use_while_rows_exist_per_environment() -> None:
    store = InMemoryCredentialStore()
    live_row = await _stored((await _start(store, "live", _Src(KEK_LIVE, 1)))[0], "live")
    demo_row = await _stored((await _start(store, "demo", _Src(KEK_V1, 1)))[0], "demo")
    del store.kcvs[("demo", 1)]
    reads: list[tuple[Any, str]] = []
    real_get = store.get

    async def get(key_id: Any, env: str) -> Any:  # the port's parameter names
        reads.append((key_id, env))
        return await real_get(key_id, env)

    store.get = get  # type: ignore[method-assign]  # record the trial unwrap's reads
    wrong, _ = await _start(store, "demo", _Src(KEK_V2, 1))
    assert wrong.health().detail == "kek_mismatch" and await _lineages(store) == [("live", 1)]
    assert reads == [(demo_row, "demo")] and live_row != demo_row


async def test_wrap_binds_the_process_environment() -> None:
    store = InMemoryCredentialStore()
    key_id = await _stored((await _start(store, "live", _Src(KEK_LIVE, 1)))[0], "live")
    ref = store.rows[key_id]["dek_ref"]
    assert ref.startswith("v2:")
    assert _opens(KEK_LIVE, ref, env.aad(b"cv-dek-v2", b"live", key_id.bytes, b"1"))
    assert not _opens(KEK_LIVE, ref, env.aad(b"cv-dek-v2", b"demo", key_id.bytes, b"1"))
    with pytest.raises(InvalidTag):
        kek(KEK_LIVE, 1, "demo").unwrap_dek(ref, credential_id=key_id)


async def test_legacy_v1_wrap_fails_closed_on_borrow(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryCredentialStore()
    svc, _ = await _start(store, "demo", _Src(KEK_V1, 1))
    key_id = await _stored(svc, "demo")
    _to_v1(store, key_id, KEK_V1)
    spy = _Spy(monkeypatch)
    with pytest.raises(CredentialUnavailable):
        await _borrow(svc, key_id)
    assert spy.bufs == []  # nothing opened: no DEK, no plaintext


async def test_legacy_v1_wrap_fails_closed_in_the_boot_trial_unwrap() -> None:
    store = InMemoryCredentialStore()
    key_id = await _stored((await _start(store, "demo", _Src(KEK_V1, 1)))[0], "demo")
    _to_v1(store, key_id, KEK_V1)
    del store.kcvs[("demo", 1)]  # rows at version 1 and no KCV: the trial unwrap decides
    svc, _ = await _start(store, "demo", _Src(KEK_V1, 1))  # the right KEK
    assert svc.health().detail == "kek_mismatch" and await _lineages(store) == []
