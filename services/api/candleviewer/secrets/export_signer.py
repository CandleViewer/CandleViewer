"""The audit export signer and its key directory (#889 S6b; ADR-0039 decisions 3, 4 and 7): M2's
side of `audit`'s `Signer` and `SigningKeyDirectory`. Each is minted once in `admin.wiring`, which
maps a refusal to `audit`'s error, and holds a closure only (C-3.2). The signer is bounded as the
HMAC signer is (ADR-0009 Amendment 2), so it is no general-purpose signing oracle: it signs only
`cv.audit.export.v1:` and the hex of 32 digest bytes, with the environment's active key only. Its
checks run in this order, the first three before any decrypt or record:
1. exactly 32 digest bytes, a well-formed key id, and the job and the Owner as UUIDs, else
   `export_request_invalid`;
2. a KEK held (the caller's `kek_unavailable`), a key boot found usable, and the active key read
   under a KEK this process holds, else `export_key_unavailable`;
3. `key_id` is the active key's, else `signing_key_rotated`;
4. `security.audit_export_signed` written ahead, naming the job, the Owner, `sha256`, `key_id` and
   `fingerprint_sha256`, else `audit_unavailable`;
5. the DEK unwrapped, `sign_export` signing, and the DEK zeroed;
6. a failure after the record appends `security.audit_export_sign_failed` with its bounded
   `reason` and leaves as a typed `CredentialUnavailable`, nothing chained and the frames below
   cleared (C-12.6); a cancellation propagates, scrubbed, after that record.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final, final
from uuid import UUID

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._export_custody import _io, _log, sealed
from candleviewer.secrets._export_key import check_digest, fingerprint, sign_export
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import _failure_reason, _m2_only
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.signing import scrub_frames
from candleviewer.secrets.store import _KEY_ID, AuditSink, ExportKeyStore

SIGNED: Final = "security.audit_export_signed"
SIGN_FAILED: Final = "security.audit_export_sign_failed"
#: `exportAuditLog` is the Owner's alone (22, `audit:export`).
_OWNER: Final = {"actor_kind": "user", "actor_role": "owner"}
#: A checked request: the key id, a copy of the digest, and the job and the Owner as UUID text.
Request = tuple[str, bytes, dict[str, str]]
#: The active key's public material: its id, raw public key and fingerprint.
PublicKey = tuple[str, bytes, str]


def _uuid(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if type(value) is not str:
        raise TypeError("a UUID")
    return str(UUID(value))


def request(key_id: object, digest: object, job_id: object, actor_user_id: object) -> Request:
    """Check 1, before any read, decrypt or record; else `export_request_invalid`."""
    try:
        if type(key_id) is not str or not _KEY_ID.fullmatch(key_id):
            raise ValueError("an export key id")
        named = {"job_id": _uuid(job_id), "actor_user_id": _uuid(actor_user_id)}
        return key_id, check_digest(digest), named
    except (TypeError, ValueError):
        pass
    raise CredentialUnavailable("export_request_invalid")  # after the handler: nothing chained


async def _written(audit: AuditSink, action: str, fields: dict[str, str]) -> bool:
    try:
        await audit(action, fields)
    except Exception:
        return False
    return True


async def _usable(
    keys: ExportKeyStore, keks: tuple[LoadedKek, ...]
) -> tuple[dict[str, Any], LoadedKek, str] | None:
    """Check 2's read: the active key, the held KEK of its version and its fingerprint, or None
    when one is missing or cannot be read."""
    try:
        rec = await _io(keys.active(keks[0].env_name))
        for kek in keks:
            if rec is not None and kek.version == rec["kek_version"]:
                return rec, kek, fingerprint(rec["public_key"])
    except Exception as exc:
        _log().error("secrets.export_key_read_failed", error=type(exc).__name__)
    return None


async def sign(
    keys: ExportKeyStore, keks: tuple[LoadedKek, ...], audit: AuditSink, checked: Request
) -> bytes:
    """Checks 2 to 6 of the module docstring, once the caller found a KEK held (`keks`, the
    current first) and a key boot found usable."""
    key_id, digest, named = checked
    usable = await _usable(keys, keks)
    if usable is None:
        raise CredentialUnavailable("export_key_unavailable")
    rec, holder, fp = usable
    if rec["key_id"] != key_id:
        raise CredentialUnavailable("signing_key_rotated")
    fields = {**_OWNER, **named, "env": rec["env"], "key_id": key_id, "fingerprint_sha256": fp}
    fields["sha256"] = digest.hex()
    if not await _written(audit, SIGNED, fields):
        raise CredentialUnavailable("audit_unavailable")
    code, dek = "credential_unavailable", bytearray()
    try:
        try:
            dek = holder.unwrap_export_dek(rec["dek_ref"], key_id=key_id)
            return sign_export(dek, sealed(rec), digest, env_name=holder.env_name)
        finally:
            env.zero(dek)
    except BaseException as exc:
        scrub_frames(exc)  # the frames below held the KEK, the DEK and the seed
        if isinstance(exc, CredentialUnavailable):
            code = str(exc)  # `sign_export`'s own refusal
        reason = code if isinstance(exc, Exception) else _failure_reason(exc)
        if not await _written(audit, SIGN_FAILED, {**fields, "reason": reason}):
            m.credential_outcome_audit_failures_total.inc()
        if not isinstance(exc, Exception):
            raise
    raise CredentialUnavailable(code)  # after the handler: nothing chained


async def active_key(keys: ExportKeyStore, keks: tuple[LoadedKek, ...]) -> PublicKey | None:
    """The key `sign` would use, as public material only, or None (check 2): no seed is opened."""
    usable = await _usable(keys, keks)
    return None if usable is None else (usable[0]["key_id"], usable[0]["public_key"], usable[2])


@final
class ExportSigner:
    """`audit`'s `Signer`, M2's side (`sign_audit_export`): minted once by `mint_export_signer`
    in `admin.wiring`. It holds a closure only (C-3.2)."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__sign",)

    def __init__(self, sign: Callable[[object, object, object, object], Awaitable[bytes]]) -> None:
        self.__sign = sign

    async def sign_audit_export(
        self, key_id: str, digest: bytes, job_id: UUID | str, actor_user_id: UUID | str
    ) -> bytes:
        """The 64-byte Ed25519 signature over `cv.audit.export.v1:` and `digest`'s hex, after
        the module docstring's checks; else a typed `SecretsError`, and nothing is signed."""
        return await self.__sign(key_id, digest, job_id, actor_user_id)


@final
class SigningKeys:
    """`audit`'s `SigningKeyDirectory`, M2's side: the active key's id, public key and fingerprint,
    or None while export is unavailable; never its seed. Minted once by `mint_signing_keys`."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__active",)

    def __init__(self, active: Callable[[], Awaitable[PublicKey | None]]) -> None:
        self.__active = active

    async def active(self) -> PublicKey | None:
        return await self.__active()
