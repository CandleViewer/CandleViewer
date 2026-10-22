"""The audit export signing key at boot (#889 S6a-2b; ADR-0039 decisions 2, 4, 6 and Q3). M2 only.

`open_at_boot` runs once the KEK is published and answers None when the environment's active key
opens to its public key, else why export is unavailable; the caller degrades `secrets` and pages,
and latches no order entry (decision 2). A store, unwrap or check failure is a reason; anything
else it raises, a record M2 cannot read say, the caller reads as `export_key_unopenable`, and a
cancellation propagates. In order:
1. Q3: a retired key still holding its seed is a finding; its destroy is retried with its record.
2. No active key: version 1 is generated, its DEK's wrap proven to open, and stored with
   `security.audit_signing_key_generated` in one transaction (C-2.9); then read again, so another
   boot's key, if it won a race, is checked like ours, and keys with none active are never
   generated over.
3. The rotation boot re-wraps a key under the previous KEK, the new wrap proven before the
   compare-and-set commits its record. A failure of step 1 or 3 is logged and counted
   (`cv_audit_signing_key_boot_failures_total{step}`); the KEK re-wrap's count waits for what it
   left (decision 6).
4. `check_key` opens the seed under the KEK its row names and compares its public key.
Each DEK is zeroed after use and a failure's frames cleared (`scrub_frames`); a log names a
failure's class, never a value (C-12.6).
"""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Awaitable, Mapping
from typing import Any
from uuid import uuid4

import structlog

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._export_key import SealedExportKey, check_key, fingerprint, generate
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import _IO_TIMEOUT_S
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.signing import scrub_frames
from candleviewer.secrets.store import ExportKeyStore

GENERATED = "security.audit_signing_key_generated"
REWRAPPED = "security.audit_signing_key_rewrapped"
DESTROYED = "security.audit_signing_key_material_destroyed"
UNAVAILABLE = "security.audit_signing_key_unavailable"  # the caller's, at error (it pages)
_ACTOR = {"actor_kind": "system", "actor_role": "secrets"}


def _log() -> Any:
    return structlog.get_logger(__name__)


async def _io[T](aw: Awaitable[T]) -> T:
    async with asyncio.timeout(_IO_TIMEOUT_S):
        return await aw


def sealed(rec: Mapping[str, Any]) -> SealedExportKey:
    """A store's sealed record as S5's core opens it: its own environment, checked at the open."""
    return SealedExportKey(rec["env"], rec["key_id"], rec["public_key"], rec["sealed_seed"])


def _fields(rec: Mapping[str, Any], **extra: str) -> dict[str, str]:
    """A key's record: who, where and which key, by names the audit redactor keeps."""
    key = {"env": rec["env"], "key_id": rec["key_id"]}
    return {**_ACTOR, **key, "fingerprint_sha256": fingerprint(rec["public_key"]), **extra}


def _wrap_verified(kek: LoadedKek, dek: bytearray, key_id: str) -> str:
    """`dek` wrapped under `kek`, proven in constant time to open to it before anyone stores it,
    as `_auth_keyring.wrap_verified` proves an auth key's wrap; the opened copy is zeroed."""
    check = bytearray()
    try:
        ref = kek.wrap_export_dek(dek, key_id=key_id)
        check = kek.unwrap_export_dek(ref, key_id=key_id)
        if not hmac.compare_digest(check, dek):
            raise CredentialUnavailable("export_key_wrap_mismatch")
    except BaseException as exc:
        scrub_frames(exc)  # the frames below hold the KEK and the DEK
        del dek  # and this one did: the caller zeroes it
        raise
    finally:
        env.zero(check)
    return ref


def _check(holder: LoadedKek, rec: Mapping[str, Any]) -> None:
    """Open `rec`'s seed under `holder`, the KEK of its version, and check its public key (step
    4): `check_key`'s refusal, or `credential_unavailable` for a wrap or a row that does not
    open, raised with nothing chained once the frames below are cleared."""
    dek = bytearray()
    try:
        dek = holder.unwrap_export_dek(rec["dek_ref"], key_id=rec["key_id"])
        check_key(dek, sealed(rec), env_name=holder.env_name)
        return
    except CredentialUnavailable:
        raise  # `check_key`'s own, scrubbed, nothing chained
    except BaseException as exc:
        scrub_frames(exc)  # `env.open_`'s frame holds the KEK
        if not isinstance(exc, Exception):
            raise
    finally:
        env.zero(dek)
    raise CredentialUnavailable("credential_unavailable")  # after the handler: nothing chained


async def _generate(store: ExportKeyStore, kek: LoadedKek) -> None:
    """Step 2: version 1, stored with its generation record, or nothing stored."""
    dek = env.new_dek()
    try:
        key = generate(dek, env_name=kek.env_name, version=1)
        ref = _wrap_verified(kek, dek, key.key_id)
    except BaseException as exc:
        scrub_frames(exc)  # the frames below held the KEK, the DEK and the seed
        raise
    finally:
        env.zero(dek)
    record = {"id": uuid4(), "env": key.env_name, "version": 1, "key_id": key.key_id}
    record |= {"public_key": key.public_key, "sealed_seed": key.sealed_seed, "dek_ref": ref}
    record["kek_version"] = kek.version
    audit = (GENERATED, _fields(record, version="1"))
    if not await _io(store.insert_first(record, audit=audit)):
        _log().debug("secrets.export_key_generation_lost")  # another boot's key: read next


async def _rewrap(
    store: ExportKeyStore, rec: dict[str, Any], prev: LoadedKek, kek: LoadedKek
) -> dict[str, Any]:
    """Step 3: `rec` moved from `prev` to `kek`, its new wrap proven before the compare-and-set;
    the row as stored, or `rec` when another boot moved it first."""
    dek = bytearray()
    try:
        dek = prev.unwrap_export_dek(rec["dek_ref"], key_id=rec["key_id"])
        ref = _wrap_verified(kek, dek, rec["key_id"])
        check_key(dek, sealed(rec), env_name=kek.env_name)
    except BaseException as exc:
        scrub_frames(exc)  # the frames below held both KEKs, the DEK and the seed
        raise
    finally:
        env.zero(dek)
    moved = {"from": str(prev.version), "to": str(kek.version)}
    cas = store.rewrap(
        rec["key_id"], env=kek.env_name, from_version=prev.version, dek_ref=ref,
        kek_version=kek.version, audit=(REWRAPPED, _fields(rec, **moved)),
    )  # fmt: skip
    return {**rec, "dek_ref": ref, "kek_version": kek.version} if await _io(cas) else rec


async def _destroy_retired(store: ExportKeyStore, env_name: str) -> None:
    """Step 1, Q3: the finding logged and the destroy retried with its record."""
    held = await _io(store.count_retired_with_seed(env_name))
    if held:
        _log().error("secrets.export_key_retired_with_seed", retired_with_seed=held)
        fields = {**_ACTOR, "env": env_name, "destroyed": str(held)}
        fields["retired_material_destroyed"] = "true"
        await _io(store.destroy_retired_seeds(env_name, audit=(DESTROYED, fields)))


def _failed(step: str, exc: Exception) -> None:
    """Step 1 or 3 failed: it degrades nothing, so it is counted for an alert (#889 S6b)."""
    m.export_key_boot_failures_total.labels(step=step).inc()
    _log().error("secrets.export_key_boot_step_failed", step=step, error=type(exc).__name__)


async def open_at_boot(store: ExportKeyStore, kek: LoadedKek, prev: LoadedKek | None) -> str | None:
    """None when the environment's active key opens and matches, else why export is unavailable:
    `export_key_` and `store_unavailable`, `generation_failed`, `inactive`, `stranded`,
    `unopenable` or `mismatch`. Steps 1 to 4 of the module docstring."""
    name, reason = kek.env_name, "export_key_store_unavailable"
    try:
        await _destroy_retired(store, name)
    except Exception as exc:  # the re-wrap's count still waits for the seed (decision 6)
        _failed("destroy", exc)
    try:
        rec = await _io(store.active(name))
        if rec is None:
            reason = "export_key_generation_failed"
            await _generate(store, kek)
            reason = "export_key_store_unavailable"
            rec = await _io(store.active(name))
    except Exception as exc:
        _log().error("secrets.export_key_open_failed", reason=reason, error=type(exc).__name__)
        return reason
    if rec is None:
        return "export_key_inactive"
    if prev is not None and rec["kek_version"] == prev.version:
        try:
            rec = await _rewrap(store, rec, prev, kek)  # proven to open before it is stored
        except Exception as exc:
            _failed("rewrap", exc)
    version = rec["kek_version"]
    holder = next((k for k in (kek, prev) if k is not None and k.version == version), None)
    if holder is None:  # below the KEK's version stranded, above it a mismatch, as `_auth_keyring`
        return "export_key_stranded" if version < kek.version else "export_key_mismatch"
    try:
        _check(holder, rec)
    except CredentialUnavailable as exc:
        mismatch = str(exc) == "export_key_mismatch"
        return "export_key_mismatch" if mismatch else "export_key_unopenable"
    return None
