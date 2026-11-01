"""The auth keyring at boot (#2152 S4; ADR-0009 Amendment 4 "Provisioning" and "KEK rotation",
D3, 21 Sec.3.1.5a). M2 only.

`open_at_boot` runs once the KEK is published, and only when the composition seam turns the
keyring on (`SecretsService(auth_keyring=...)`, BQ-7). It answers the environment's opened
keyring, else why MFA is unavailable; the caller degrades `secrets`, pages and latches nothing
(D4). In order:
1. The environment's rows are read.
2. Rows exist. At a rotation boot each row at the previous KEK version is re-wrapped under the
   current one, its new wrap proven to open before the compare-and-set commits
   `security.auth_keyring_rewrapped` with it (BQ-4, as `_export_custody` step 3). A failed one is
   logged and counted (`cv_auth_keyring_boot_failures_total{step="rewrap"}`) and still opens under
   the previous KEK on this boot; the KEK re-wrap run's `auth_left` holds `kek_rotated` back. Then
   the rows are opened (`load_keyring`): `auth_keyring_stranded` and `_mismatch` fail closed, and
   nothing is ever generated over them (AC8). Env settings still set are ignored, with a warning
   that names them (AC3).
3. No rows, demo or testnet, both env settings set: they are imported once as `imported_env`
   wraps, committed with `security.auth_keyring_imported` (D3, AC3). One setting alone is
   `auth_keyring_missing`, with a critical log that names the other (BQ-2). `start()` refuses
   either setting in live before any KEK is loaded (`refuse_env_keys_in_live`, AC2's backstop).
4. No rows, no setting, and nothing a new key would strand (`count_mfa_material`, every
   environment): a keyring is generated, committed with `security.auth_keyring_enrolled` (AC1).
   Material left: `auth_keyring_missing`, and nothing is generated (AC7).
A boot that lost its insert to another boot opens that boot's rows. Each key is zeroed after use
and a failure's frames cleared (`scrub_frames`); a log names a failure's class and a count, never
a value (C-12.6). Never deletes MFA material (BQ-9).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import SecretStr

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._auth_keyring import (
    IMPORT_ENVIRONMENTS,
    RECOVERY,
    TOTP,
    LoadedAuthKeyring,
    Records,
    generate_keyring,
    import_keyring,
    load_keyring,
    wrap_verified,
)
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import _IO_TIMEOUT_S, _failure_reason
from candleviewer.secrets.errors import AuthKeyEnvForbidden, AuthKeyringUnavailable
from candleviewer.secrets.signing import scrub_frames
from candleviewer.secrets.store import AuditSink, AuthKeyStore

if TYPE_CHECKING:
    from candleviewer.settings import Settings

LOADED = "security.auth_keyring_loaded"
IMPORTED_ACTION = "security.auth_keyring_imported"
ENROLLED = "security.auth_keyring_enrolled"
REWRAPPED = "security.auth_keyring_rewrapped"
LOAD_FAILED = "security.auth_keyring_load_failed"  # the caller's, at error (it pages)
#: The env settings D3 imports once, by name: a log names a setting, never its value.
SETTINGS = ("CV_AUTH_TOTP_KEY_HEX", "CV_AUTH_RECOVERY_HMAC_KEY_HEX")
MISSING = "auth_keyring_missing"
#: The keyring's store failed at boot, or a record did (a write's, or the load's through the
#: sink): a restart retries.
STORE_DOWN, AUDIT_DOWN = "auth_keyring_store_unavailable", "auth_keyring_audit_unavailable"
#: The caller's, when `open_at_boot` raises what it does not expect: the open reached no verdict
#: on the rows, so its remediation is never a restore from a backup (as `export_key_unopenable`).
UNOPENABLE = "auth_keyring_unopenable"
#: M10's typed failure of a write's record, told apart by `code` as `export_rotator` tells its
#: own (no `storage` import, C-3.2): the write rolled back with it.
_UNWRITTEN = "STORAGE_AUTH_KEY_AUDIT_NOT_WRITTEN"
_ACTOR = {"actor_kind": "system", "actor_role": "secrets"}
EnvKeys = tuple[SecretStr | None, SecretStr | None]


def _log() -> Any:
    return structlog.get_logger(__name__)


class _Unavailable(Exception):
    """Why this boot opens no keyring: the reason `open_at_boot` answers, nothing chained."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _io[T](aw: Awaitable[T]) -> T:
    """A bounded store call. A write whose record M10 did not write is
    `auth_keyring_audit_unavailable`; any other failure but a cancellation is
    `auth_keyring_store_unavailable`. Each is logged by its class (a typed refusal of M10 names
    no row)."""
    try:
        async with asyncio.timeout(_IO_TIMEOUT_S):
            return await aw
    except Exception as exc:
        _log().error("secrets.auth_keyring_store_failed", error=type(exc).__name__)
        reason = AUDIT_DOWN if getattr(exc, "code", None) == _UNWRITTEN else STORE_DOWN
    raise _Unavailable(reason)  # after the handler: nothing chained


def env_keys(settings: Settings) -> EnvKeys:
    """The two old env settings, as `SecretStr` (D3): read here, in M2, and nowhere else."""
    return settings.auth_totp_key_hex, settings.auth_recovery_hmac_key_hex


def refuse_env_keys_in_live(env_name: str, keys: EnvKeys) -> None:
    """AC2's backstop in M2: either setting outside demo and testnet refuses the start
    (`auth_key_env_forbidden`), before any KEK is loaded; from #2152's switch-over `Settings`
    refuses it before any module starts."""
    if env_name not in IMPORT_ENVIRONMENTS and any(k is not None for k in keys):
        raise AuthKeyEnvForbidden("auth_key_env_forbidden")


def _keyring_fields(records: Sequence[Mapping[str, Any]], origin: str) -> dict[str, str]:
    """A keyring's record: where, which rows by purpose, their versions and origin (BQ-8)."""
    ids = {r["purpose"]: str(r["id"]) for r in records}
    first, keyring = records[0], {"totp_seal_id": ids[TOTP], "recovery_hmac_id": ids[RECOVERY]}
    versions = {"key_version": str(first["key_version"]), "kek_version": str(first["kek_version"])}
    return {**_ACTOR, "env": first["env"], "origin": origin, **versions, **keyring}


def _failed(step: str, exc: Exception) -> None:
    """A boot step failed and degrades nothing: counted for an alert and logged with its class and
    its bounded reason, an M2 refusal's code: constants only."""
    m.auth_keyring_boot_failures_total.labels(step=step).inc()
    error, code = type(exc).__name__, _failure_reason(exc)
    _log().error("secrets.auth_keyring_boot_step_failed", step=step, error=error, code=code)


async def _rewrap(
    store: AuthKeyStore, row: Mapping[str, Any], prev: LoadedKek, kek: LoadedKek
) -> dict[str, Any]:
    """`row` moved from `prev` to `kek`, its new wrap proven before the compare-and-set commits
    its record; the row as stored, or `row` when another boot moved it first."""
    key = bytearray()
    try:
        key = prev.unwrap_auth_key(row["dek_ref"], key_id=row["id"], purpose=row["purpose"])
        ref = wrap_verified(kek, key, row["id"], row["purpose"])
    except BaseException as exc:
        scrub_frames(exc)  # the frames below held both KEKs and the key
        raise
    finally:
        env.zero(key)
    named = {"env": kek.env_name, "auth_key_id": str(row["id"]), "purpose": row["purpose"]}
    fields = {**_ACTOR, **named, "from": str(prev.version), "to": str(kek.version)}
    cas = store.rewrap(
        row["id"], env=kek.env_name, from_version=prev.version, dek_ref=ref,
        kek_version=kek.version, audit=(REWRAPPED, fields),
    )  # fmt: skip
    async with asyncio.timeout(_IO_TIMEOUT_S):  # a failure is the caller's counted step
        moved = await cas
    return {**row, "dek_ref": ref, "kek_version": kek.version} if moved else dict(row)


async def _rewrapped(
    store: AuthKeyStore, rows: list[dict[str, Any]], kek: LoadedKek, prev: LoadedKek | None
) -> list[dict[str, Any]]:
    """The rotation boot's re-wrap of every row at `prev`'s version (BQ-4)."""
    if prev is None:
        return rows
    out = []
    for row in rows:
        if row["kek_version"] == prev.version:
            try:
                row = await _rewrap(store, row, prev, kek)
            except Exception as exc:  # it still opens under `prev` on this boot
                _failed("rewrap", exc)
        out.append(row)
    return out


def _made(kek: LoadedKek, keys: EnvKeys) -> tuple[str, Records, LoadedAuthKeyring]:
    """The keyring this boot makes: imported from both settings, else generated. A setting that
    is not 32-byte hex is named, never shown."""
    totp, recovery = keys
    importing = totp is not None and recovery is not None
    try:
        if totp is not None and recovery is not None:
            return IMPORTED_ACTION, *import_keyring(kek, totp, recovery)
        return ENROLLED, *generate_keyring(kek)
    except Exception as exc:
        scrub_frames(exc)  # the frames below held the KEK and the keys
        named = {"settings": list(SETTINGS)} if importing else {}
        _log().critical("secrets.auth_keyring_not_made", error=type(exc).__name__, **named)
    raise _Unavailable(MISSING)  # after the handler: nothing chained


def _one_alone(keys: EnvKeys) -> str | None:
    """BQ-2, both settings or neither: the name of the one missing when the other is set."""
    totp, recovery = keys
    if (totp is None) == (recovery is None):
        return None
    return SETTINGS[0] if totp is None else SETTINGS[1]


async def _nothing_held_back(store: AuthKeyStore) -> bool:
    """AC7: no unrevoked TOTP method and no unused recovery code in any environment, so a new
    keyring strands nothing; else the count is logged (a count, never a row)."""
    material = await _io(store.count_mfa_material())
    if material:
        _log().critical("secrets.auth_keyring_material_without_keyring", material=material)
    return not material


async def _provision(
    store: AuthKeyStore, kek: LoadedKek, keys: EnvKeys
) -> LoadedAuthKeyring | None:
    """Steps 3 and 4: the keyring this boot made and stored, or None when another boot stored its
    keyring first (the caller opens that one), or `_Unavailable`."""
    if (missing := _one_alone(keys)) is not None:
        _log().critical("secrets.auth_keyring_setting_missing", missing=missing)
        raise _Unavailable(MISSING)
    if keys[0] is None and not await _nothing_held_back(store):
        raise _Unavailable(MISSING)  # never generated over what a key would strand
    action, records, ring = _made(kek, keys)
    try:
        audit = (action, _keyring_fields(records, records[0]["origin"]))
        if await _io(store.insert_keyring(records, audit=audit)):
            return ring
    except BaseException:
        ring.close()
        raise
    ring.close()  # another boot's keyring won: ours is never used
    _log().debug("secrets.auth_keyring_insert_lost")
    return None


async def open_at_boot(
    store: AuthKeyStore,
    kek: LoadedKek,
    prev: LoadedKek | None,
    keys: EnvKeys,
    audit: AuditSink,
) -> tuple[LoadedAuthKeyring | None, str | None]:
    """`(the opened keyring, None)`, else `(None, why MFA is unavailable)`: `auth_keyring_` and
    `missing`, `mismatch`, `stranded`, `store_unavailable` or `audit_unavailable`. Steps 1 to 4 of
    the module docstring; a cancellation propagates, any keyring it held zeroed."""
    try:
        rows = await _io(store.rows_for(kek.env_name))
        if not rows:
            made = await _provision(store, kek, keys)
            if made is not None:
                return made, None
            rows = await _io(store.rows_for(kek.env_name))  # the boot that won
        elif any(k is not None for k in keys):  # AC3: a later boot warns and ignores them
            named = [n for n, k in zip(SETTINGS, keys, strict=True) if k is not None]
            _log().warning("secrets.auth_keyring_env_settings_ignored", settings=named)
        rows = await _rewrapped(store, rows, kek, prev)
    except _Unavailable as exc:
        return None, exc.reason
    try:
        ring = load_keyring(kek, rows, prev=prev)
    except AuthKeyringUnavailable as exc:
        return None, exc.reason
    try:
        fields = _keyring_fields(rows, rows[0]["origin"])  # one origin: `load_keyring` checked
        await audit(LOADED, fields | {"kek_version": str(kek.version)})
    except BaseException as exc:
        ring.close()  # a keyring is never used unrecorded
        if not isinstance(exc, Exception):
            raise
        return None, AUDIT_DOWN
    return ring, None
