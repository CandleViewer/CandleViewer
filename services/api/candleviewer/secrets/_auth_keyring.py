"""Auth keyring core (#2152, ADR-0009 Amendment 4). Private to M2; unused until S4 and S5b.

The keyring is two 256-bit keys per environment, `totp_seal` (AES-256-GCM over TOTP seeds) and
`recovery_hmac` (HMAC-SHA256 over recovery codes), plaintext only here and at rest only as
`auth_keys` rows wrapped under the environment's KEK (`21-database-schema.md` §3.1.5a). Callers
get seals, seeds and digests, never a key. New seals and digests bind the user; the env keys' old
formats are read only on an imported keyring (D3). Errors carry reason codes only (C-12.6), and
a failure leaves no key, seed or code in a frame's locals and chains nothing (`scrub_frames`).
SR-009 residual: `AESGCM` and `hmac` hold immutable key copies `zero()` cannot wipe.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, NoReturn, final
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from pydantic import SecretStr

from candleviewer.secrets import _envelope as env
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import _m2_only
from candleviewer.secrets.errors import AuthKeyEnvForbidden, AuthKeyringUnavailable, AuthSealInvalid
from candleviewer.secrets.signing import scrub_frames

TOTP, RECOVERY = env.AUTH_PURPOSES
GENERATED, IMPORTED = "generated", "imported_env"
#: D3: the old env keys are imported once, on these environments only; `live` always generates.
IMPORT_ENVIRONMENTS = frozenset({"demo", "testnet"})
#: `secret_key_ref` of a seal under the old env key, with no AAD (imported keyrings only).
LEGACY_TOTP_REF = "local-dev-v1"
_CODE_MAX = 512  # bytes; a 64-character contract code normalises to <= 384 (U+0390 -> 6 bytes)
_ORIGIN_SETS = ({GENERATED}, {IMPORTED})  # a mixed keyring is a tampered one
Records = list[dict[str, Any]]


def normalise_code(code: str) -> bytes:
    """`auth.recovery_codes.normalize_recovery_code` (M2 cannot import M18), as UTF-8."""
    out = code.strip().upper().replace("-", "").replace(" ", "").encode()
    if len(out) > _CODE_MAX:
        raise ValueError("recovery code too long")
    return out


@final
class LoadedAuthKeyring:
    """One environment's auth keys in memory. Renders as `***`, refuses pickling and copying;
    `close()` zeroes both keys and every later call refuses (`auth_keyring_closed`)."""

    __slots__ = ("_ak_closed", "_ak_env", "_ak_imported", "_rc_key", "_totp_key", "_totp_ref")

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    def __init__(
        self, env_name: str, *, imported: bool, totp_id: UUID, totp: bytearray, recovery: bytearray
    ) -> None:
        if env_name not in env.ENVIRONMENTS or {len(totp), len(recovery)} != {env.KEY_LEN}:
            env.zero(totp)
            env.zero(recovery)
            raise ValueError("auth keyring shape")
        self._ak_env, self._ak_imported, self._ak_closed = env_name, imported, False
        self._totp_ref, self._totp_key, self._rc_key = f"akey:{totp_id}", totp, recovery

    def available(self) -> bool:
        return not self._ak_closed

    def _require_open(self) -> None:
        if self._ak_closed:
            raise AuthKeyringUnavailable("auth_keyring_closed")

    def seal_totp_seed(self, seed: bytes | bytearray, user_id: UUID) -> tuple[bytes, str]:
        """`(secret_enc, secret_key_ref)` of a new seal, bound to the environment and user."""
        if not seed:
            raise ValueError("empty TOTP seed")
        try:
            self._require_open()
            aad = env.totp_aad(self._ak_env, user_id)
            return env.seal(self._totp_key, seed, aad), self._totp_ref
        except BaseException as exc:
            scrub_frames(exc)  # `env.seal`'s frame holds the key
            del seed  # and this one the seed
            raise

    def open_totp_seed(self, blob: bytes, key_ref: str, user_id: UUID) -> bytearray:
        """The seed, as a `bytearray` the caller zeroes. `AuthSealInvalid` when a seal under a
        key held here fails authentication (a wrong code); `auth_key_not_held` for any other."""
        self._require_open()
        if key_ref == self._totp_ref:
            aad = env.totp_aad(self._ak_env, user_id)
        elif key_ref == LEGACY_TOTP_REF and self._ak_imported:
            aad = b""
        else:
            raise AuthKeyringUnavailable("auth_key_not_held")
        try:
            return env.open_(self._totp_key, blob, aad)
        except BaseException as exc:
            scrub_frames(exc)  # `env.open_`'s frame holds the key
            if not isinstance(exc, InvalidTag | ValueError):
                raise
        raise AuthSealInvalid("auth_seal_invalid")  # after the handler: nothing chained

    def recovery_code_digests(self, code: str, user_id: UUID) -> tuple[str, ...]:
        """Hex digests of `code` for `user_id`: the one to store (bound to the user), then, on an
        imported keyring only, the env key's old digest, which a lookup also accepts. Over the cap
        (no contract body is), `ValueError`: S5's adapter counts that as a wrong code."""
        try:
            self._require_open()
            norm = normalise_code(code)
        except BaseException as exc:
            scrub_frames(exc)  # `normalise_code`'s frame holds the code
            del code  # and so does this one
            raise
        out = [hmac.new(self._rc_key, env.rc_preimage(user_id, norm), sha256).hexdigest()]
        if self._ak_imported:
            out.append(hmac.new(self._rc_key, norm, sha256).hexdigest())
        return tuple(out)

    def close(self) -> None:
        self._ak_closed = True
        env.zero(self._totp_key)
        env.zero(self._rc_key)

    def __repr__(self) -> str:
        return "***"

    __str__ = __repr__

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("LoadedAuthKeyring cannot be pickled")


def generate_keyring(kek: LoadedKek) -> tuple[Records, LoadedAuthKeyring]:
    """AC1: two random keys, wrapped under `kek`, in any environment."""
    return _new_keyring(kek, env.new_dek(), env.new_dek(), GENERATED)


def import_keyring(
    kek: LoadedKek, totp_hex: SecretStr, recovery_hex: SecretStr
) -> tuple[Records, LoadedAuthKeyring]:
    """D3: the one-time import of `CV_AUTH_TOTP_KEY_HEX` and `CV_AUTH_RECOVERY_HMAC_KEY_HEX`."""
    if kek.env_name not in IMPORT_ENVIRONMENTS:
        raise AuthKeyEnvForbidden("auth_key_env_forbidden")
    totp = _decode(totp_hex)
    try:
        recovery = _decode(recovery_hex)
    except ValueError:
        env.zero(totp)
        raise
    return _new_keyring(kek, totp, recovery, IMPORTED)


def _decode(setting: SecretStr) -> bytearray:
    try:
        key = bytearray.fromhex(setting.get_secret_value())
    except ValueError:
        key = bytearray()
    if len(key) != env.KEY_LEN:
        env.zero(key)
        raise ValueError("an auth key setting must be 32-byte hex")
    return key


def _new_keyring(
    kek: LoadedKek, totp: bytearray, recovery: bytearray, origin: str
) -> tuple[Records, LoadedAuthKeyring]:
    keys, ids = {TOTP: totp, RECOVERY: recovery}, {TOTP: uuid4(), RECOVERY: uuid4()}
    try:
        refs = {p: wrap_verified(kek, keys[p], ids[p], p) for p in keys}
    except BaseException:
        env.zero(totp)
        env.zero(recovery)
        raise
    records = [
        {"id": ids[p], "env": kek.env_name, "purpose": p, "key_version": 1, "origin": origin,
         "dek_ref": refs[p], "kek_version": kek.version}
        for p in keys
    ]  # fmt: skip
    ring = LoadedAuthKeyring(
        kek.env_name, imported=origin == IMPORTED, totp_id=ids[TOTP], totp=totp, recovery=recovery
    )
    return records, ring


def wrap_verified(kek: LoadedKek, key: bytearray, key_id: UUID, purpose: str) -> str:
    """Wrap `key`, then prove (in constant time) the wrap opens to it before anyone stores it."""
    ref = kek.wrap_auth_key(key, key_id=key_id, purpose=purpose)
    check = kek.unwrap_auth_key(ref, key_id=key_id, purpose=purpose)
    try:
        if not hmac.compare_digest(check, key):
            raise AuthKeyringUnavailable("auth_keyring_mismatch")
    finally:
        env.zero(check)
    return ref


def load_keyring(
    kek: LoadedKek, rows: Sequence[Mapping[str, Any]], *, prev: LoadedKek | None = None
) -> LoadedAuthKeyring:
    """Unwrap the environment's two rows (`prev`: the previous KEK at a rotation boot). Fails
    closed, never regenerates: `auth_keyring_stranded` for a row at a KEK version this process
    does not hold, else `auth_keyring_mismatch` (a missing, extra, moved or tampered row)."""
    by_purpose = {r["purpose"]: r for r in rows}
    origins = {r["origin"] for r in rows}
    imported = origins == {IMPORTED}
    if len(rows) != 2 or set(by_purpose) != {TOTP, RECOVERY} or origins not in _ORIGIN_SETS:
        raise AuthKeyringUnavailable("auth_keyring_mismatch")
    if imported and kek.env_name not in IMPORT_ENVIRONMENTS:  # D3: no old format is read in live
        raise AuthKeyringUnavailable("auth_keyring_mismatch")
    totp = _unwrap(by_purpose[TOTP], kek, prev)
    try:
        recovery = _unwrap(by_purpose[RECOVERY], kek, prev)
    except BaseException:
        env.zero(totp)
        raise
    totp_id = by_purpose[TOTP]["id"]
    return LoadedAuthKeyring(
        kek.env_name, imported=imported, totp_id=totp_id, totp=totp, recovery=recovery
    )


def _holder(version: int, kek: LoadedKek, prev: LoadedKek | None) -> LoadedKek | None:
    """The KEK of the version a row names: a row opens only under that version."""
    return next((k for k in (kek, prev) if k is not None and k.version == version), None)


def _unwrap(row: Mapping[str, Any], kek: LoadedKek, prev: LoadedKek | None) -> bytearray:
    if row["env"] != kek.env_name:
        raise AuthKeyringUnavailable("auth_keyring_mismatch")
    holder = _holder(row["kek_version"], kek, prev)
    if holder is None and row["kek_version"] < kek.version:
        raise AuthKeyringUnavailable("auth_keyring_stranded")
    if holder is None:
        raise AuthKeyringUnavailable("auth_keyring_mismatch")
    try:
        return holder.unwrap_auth_key(row["dek_ref"], key_id=row["id"], purpose=row["purpose"])
    except BaseException as exc:
        scrub_frames(exc)  # `env.open_`'s frame holds the KEK
        if not isinstance(exc, InvalidTag | ValueError):
            raise
    raise AuthKeyringUnavailable("auth_keyring_mismatch")  # after the handler: nothing chained
