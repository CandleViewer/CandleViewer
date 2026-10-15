"""Offline break-glass KEK proof (E09-S11 #2119, decision O1): metadata only, never enrols.

`prove_kek_possession` runs `SecretsService.start()`'s custody path (hardening, handle drain and
nonce-ack, version policy) but refuses a KEK whose KCV is not already in `kek_versions`, in every
environment. It audits, latches and publishes nothing, and zeroes every KEK it loaded. Hardening
is always faked here: the real one must not leak into the pytest process (test_kek_harden.py).
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from candleviewer.secrets import KekCheckResult, prove_kek_possession
from candleviewer.secrets._source import KekSources
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment
from tests.unit.credentials_m2._service_fakes import KEK_V3, _boot, _settings, _Src, _zeroed
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2


async def _prove(
    store: InMemoryCredentialStore,
    cur: _Src,
    prev: _Src | None = None,
    *,
    hardened: bool = True,
    **settings: Any,
) -> KekCheckResult:
    return await prove_kek_possession(
        _settings(**settings), store,
        sources=lambda s: KekSources(cur, prev, None), harden=lambda: hardened,
    )  # fmt: skip


async def _enrolled_v1() -> InMemoryCredentialStore:
    """`kek_versions` as a cv-api boot left it: KEK_V1 enrolled at version 1."""
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    return store


async def test_proof_returns_metadata_only() -> None:
    store = await _enrolled_v1()
    before = dict(store.kcvs)
    res = await _prove(store, _Src(KEK_V1, 1))
    assert res == KekCheckResult(1, True, None)
    assert [f.name for f in dataclasses.fields(res)] == ["version", "kcv_ok", "reason"]
    assert not any(isinstance(v, bytes | bytearray) for v in dataclasses.astuple(res))
    assert store.kcvs == before


async def test_proof_never_enrols_unknown_kek() -> None:
    """Both shapes `start()` enrols (`verify_kcv(must_exist=False)`) are refused instead: a
    fresh `kek_versions` table, and version max+1 supplied beside the enrolled previous KEK."""
    fresh = InMemoryCredentialStore()
    assert await _prove(fresh, _Src(KEK_V1, 1)) == KekCheckResult(None, False, "kek_not_enrolled")
    assert fresh.kcvs == {}
    store = await _enrolled_v1()
    res = await _prove(store, _Src(KEK_V2, 2), _Src(KEK_V1, 1))
    assert res == KekCheckResult(None, False, "kek_not_enrolled")
    assert set(store.kcvs) == {1}


@pytest.mark.parametrize(
    ("raw", "retired", "environment", "reason"),
    [
        (KEK_V2, set(), Environment.DEMO, "kek_mismatch"),
        (KEK_V1, {1}, Environment.DEMO, "kek_retired"),
        (KEK_V1, set(), Environment.LIVE, "kek_source_not_permitted"),
    ],
    ids=["mismatch", "retired", "live_file"],
)
async def test_proof_refuses_mismatch_retired_live_file(
    tmp_path: Path, raw: bytes, retired: set[int], environment: Environment, reason: str
) -> None:
    """Real settings → sources → file loader; `file` in live is refused before any read (the
    Settings validator is bypassed with `model_copy`, as `validate_kek_settings` is the check)."""
    store = await _enrolled_v1()
    store.retired |= retired
    key = tmp_path / "kek"
    key.write_bytes(raw)
    key.chmod(0o400)
    settings = _settings(kek_source="file", kek_handle=str(key))
    settings = settings.model_copy(update={"environment": environment})
    before = dict(store.kcvs)
    res = await prove_kek_possession(settings, store, harden=lambda: True)
    assert res == KekCheckResult(None, False, reason)
    assert store.kcvs == before


@pytest.mark.parametrize(
    ("environment", "result", "loads"),
    [
        (Environment.LIVE, KekCheckResult(None, False, "process_hardening_failed"), 0),
        (Environment.DEMO, KekCheckResult(1, True, None), 1),
    ],
)
async def test_proof_needs_hardening_in_live(
    environment: Environment, result: KekCheckResult, loads: int
) -> None:
    """SR-009 as at boot: unhardened is fatal in live before the KEK is read, a warning
    elsewhere."""
    src = _Src(KEK_V1, 1)
    res = await _prove(
        await _enrolled_v1(), src, hardened=False, environment=environment, kek_source="none"
    )
    assert res == result and len(src.handed) == loads


@pytest.mark.parametrize(
    ("raw", "ok"), [(KEK_V1, True), (KEK_V2, False)], ids=["proven", "refused"]
)
async def test_proof_zeroes_kek(raw: bytes, ok: bool) -> None:
    src = _Src(raw, 1)
    res = await _prove(await _enrolled_v1(), src)
    assert res.kcv_ok is ok and _zeroed(src)


async def test_proof_checks_and_zeroes_the_previous_kek() -> None:
    store = InMemoryCredentialStore()
    await _boot(store, _Src(KEK_V1, 1))
    await _boot(store, _Src(KEK_V2, 2), _Src(KEK_V1, 1))  # rotation: v2 enrolled beside v1
    cur, wrong_prev = _Src(KEK_V2, 2), _Src(KEK_V3, 1)
    res = await _prove(store, cur, wrong_prev)
    assert res == KekCheckResult(None, False, "kek_mismatch")
    assert _zeroed(cur) and _zeroed(wrong_prev)
    assert await _prove(store, _Src(KEK_V2, 2), _Src(KEK_V1, 1)) == KekCheckResult(2, True, None)


async def test_proof_live_fifo_without_handoff_nonce_is_refused() -> None:
    src = _Src(KEK_V1, 1, fifo=True)
    res = await _prove(await _enrolled_v1(), src, environment=Environment.LIVE, kek_source="none")
    assert res == KekCheckResult(None, False, "kek_handle_permissions") and _zeroed(src)


async def test_proof_kcv_store_outage_refuses_and_zeroes() -> None:
    store = await _enrolled_v1()

    async def boom() -> list[Any]:
        raise RuntimeError("db down")

    store.kcv_versions = boom  # type: ignore[method-assign]
    src = _Src(KEK_V1, 1)
    res = await _prove(store, src)
    assert res == KekCheckResult(None, False, "kcv_store_unavailable") and _zeroed(src)


async def test_proof_unexpected_error_fails_closed() -> None:
    res = await _prove(await _enrolled_v1(), _Src(KEK_V1, 1, exc=OSError("handle read")))
    assert res == KekCheckResult(None, False, "kek_unavailable")


async def test_proof_cancellation_propagates_and_zeroes() -> None:
    store = await _enrolled_v1()
    entered = asyncio.Event()

    async def hang() -> list[Any]:
        entered.set()
        await asyncio.Event().wait()
        return []

    store.kcv_versions = hang  # type: ignore[method-assign]
    src = _Src(KEK_V1, 1)
    task = asyncio.create_task(_prove(store, src))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _zeroed(src)
