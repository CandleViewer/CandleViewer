"""The audit export signing key's rotation (#889 S7; ADR-0039 decisions 4 to 6, Q3): M2's side of
`rotateAuditSigningKey`, as `SigningKeyRotator`, minted once in `admin.wiring`; a closure only that
answers with public key material (C-2.7, C-3.2). `SecretsService._rotate_export_key` answers in
22's order:
1. the idempotency lookup, at any age and read with its Owner only (21 Sec.3.1.5b): the stored
   rotation, `idempotency_key_reuse`, or `idempotency_in_flight` for the same request running;
2. the refusals, which rotate nothing: `kek_unavailable`, `rate_limited` past the environment's
   rotations in a rolling hour (only those that start count, a failed one too; the caller counts
   the refusal), `conflict` while a rotation or an export job runs or with no key to retire. Each
   but `rate_limited` writes `security.audit_signing_key_rotation_refused` first, naming why
   (`REFUSAL_REASONS`);
3. the next key made as boot makes the first (`_export_custody.new_key`), then one transaction
   retires the active key, destroys its seed (Q3) and commits the new key with
   `security.audit_signing_key_rotated` (C-2.9). A raced retry reads step 1 again, and so does a
   store failure, whose COMMIT may have landed with its answer lost; one that did not commit
   appends `security.audit_signing_key_rotation_failed`, naming why (`FAILURE_REASONS`);
4. once committed, the active key read back is checked (`check_key`): passing, M2 remembers it and
   export is available again with no restart; failing, it is latched as at boot.
`verified` marks only the active key the directory names, the key M2 checked (decision 4). Logs
carry no value."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, final
from uuid import UUID

from candleviewer.secrets._export_custody import _check, _io, _log, new_key
from candleviewer.secrets._export_key import fingerprint
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.broker import _m2_only
from candleviewer.secrets.errors import CredentialUnavailable, ExportKeyRotationError
from candleviewer.secrets.export_signer import _usable, _uuid
from candleviewer.secrets.store import RETIRED_REASONS, ExportKeyStore

ROTATED: Final = "security.audit_signing_key_rotated"
REFUSED: Final = "security.audit_signing_key_rotation_refused"
FAILED: Final = "security.audit_signing_key_rotation_failed"
#: M10's typed failures of a rotation, told apart by `code` as `broker._io` reads them (I1).
_TAKEN: Final = "STORAGE_EXPORT_KEY_REQUEST_TAKEN"
_UNWRITTEN: Final = "STORAGE_EXPORT_KEY_AUDIT_NOT_WRITTEN"
#: Why a rotation was refused, its record's `reason`: the closed set. The answer is
#: `kek_unavailable` for the first, `conflict` for the others.
NO_KEK: Final = "kek_unavailable"
ROTATING: Final = "rotation_in_progress"
EXPORTING: Final = "export_in_progress"
NO_KEY: Final = "no_active_key"
REFUSAL_REASONS: Final = frozenset({NO_KEK, ROTATING, EXPORTING, NO_KEY})
#: Why a rotation that started did not commit, its record's `reason` and its `503`'s code.
STORE_DOWN: Final = "store_unavailable"
UNRECORDED: Final = "audit_unavailable"
FAILURE_REASONS: Final = frozenset({STORE_DOWN, UNRECORDED})
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: A rotation's answer: `active`, the key it made as it was then, and `retired`, the key it
#: retired, each a public record (`EXPORT_KEY_PUBLIC`) with its `verified` mark.
Rotation = dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Request:
    """A checked call: the rotation's reason, the Owner and the `Idempotency-Key` as UUID text,
    and the request's fingerprint (`api.idempotency.request_fingerprint`)."""

    reason: str
    owner: str
    ref: str
    body_sha256: str

    def fields(self, **named: str) -> dict[str, str]:
        """A record's members: the acting Owner, then `named`."""
        return {"actor_kind": "user", "actor_role": "owner", "actor_user_id": self.owner, **named}


def request(reason: object, owner: object, ref: object, body_sha256: object) -> Request:
    """The call, checked before any read or record. Only our own route calls, so a malformed one is
    a defect and raises (`ValueError`, `TypeError`)."""
    if not isinstance(reason, str) or reason not in RETIRED_REASONS:
        raise ValueError("a rotation's reason: scheduled, compromise or unrecoverable")
    if not isinstance(body_sha256, str) or _SHA256.fullmatch(body_sha256) is None:
        raise ValueError("a request fingerprint: 64 lowercase hex")
    return Request(reason, _uuid(owner), _uuid(ref), body_sha256)


async def replayed(keys: ExportKeyStore | None, env_name: str, req: Request) -> Rotation | None:
    """Step 1: the rotation `req`'s Owner and key made, if any; `idempotency_key_reuse` for another
    fingerprint, `store_unavailable` when it cannot be read."""
    made, failed = None, False
    if keys is not None and env_name:
        owner = UUID(req.owner)
        try:
            made = await _io(keys.rotation(env_name, created_by=owner, client_ref=req.ref))
        except Exception as exc:
            _log().error("secrets.export_key_rotation_lookup_failed", error=type(exc).__name__)
            failed = True
    if failed:
        raise ExportKeyRotationError(STORE_DOWN)  # after the handler: nothing chained
    if made is not None and made.pop("client_body_sha256") != req.body_sha256:
        raise ExportKeyRotationError("idempotency_key_reuse")
    return made


async def rotate(
    keys: ExportKeyStore, kek: LoadedKek, req: Request, old: Mapping[str, Any]
) -> Rotation | None:
    """Step 3's transaction: the key one version above `old`, the active one, with its record; None,
    nothing written, once `old` is no longer active. A failure raises as the store raised it."""
    record = new_key(kek, old["version"] + 1)
    record |= {"created_by": UUID(req.owner), "client_ref": req.ref}
    record["client_body_sha256"] = req.body_sha256
    fields = req.fields(
        env=kek.env_name, reason=req.reason, active_key_id=record["key_id"],
        retired_key_id=old["key_id"], active_fingerprint_sha256=fingerprint(record["public_key"]),
        retired_fingerprint_sha256=fingerprint(old["public_key"]),
        retired_material_destroyed="true",
    )  # fmt: skip
    audit = (ROTATED, fields)
    made = await _io(keys.rotate(record, retire=old["key_id"], reason=req.reason, audit=audit))
    if made is not None:
        made.pop("client_body_sha256")
    return made


def outcome(exc: BaseException) -> str:
    """A failed step 3: `taken` for a retry that raced its first try (step 1 again),
    `audit_unavailable` for a record not written, so nothing committed, else `store_unavailable`,
    which step 1 reads again before it is recorded."""
    code = getattr(exc, "code", None)
    if code == _TAKEN:
        return "taken"
    return UNRECORDED if code == _UNWRITTEN else STORE_DOWN


async def checked(
    keys: ExportKeyStore, keks: tuple[LoadedKek, ...]
) -> tuple[str | None, str | None]:
    """Step 4: `(None, its key id)` once the active key, read back, opens under the held KEK of
    its version and derives its public key (`check_key`); else `(boot's reason why export is
    unavailable, None)`."""
    usable = await _usable(keys, keks)
    if usable is None:
        return "export_key_store_unavailable", None
    try:
        _check(usable[1], usable[0])
    except CredentialUnavailable as exc:
        mismatch = str(exc) == "export_key_mismatch"
        return ("export_key_mismatch" if mismatch else "export_key_unopenable"), None
    return None, usable[0]["key_id"]


def marked(record: Mapping[str, Any], active_id: str | None) -> dict[str, Any]:
    """`record` with its `verified` mark: true only for the active key the directory names, which
    is the key M2 checked."""
    return {**record, "verified": record["status"] == "active" and record["key_id"] == active_id}


@final
class SigningKeyRotator:
    """`rotateAuditSigningKey`'s capability, M2's side (#889 S7): minted once by
    `mint_signing_key_rotator` in `admin.wiring` for `admin` alone. It holds a closure only (C-3.2)
    and answers with public key material, never a seed."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__rotate",)

    def __init__(self, rotate: Callable[..., Awaitable[tuple[Rotation, bool]]]) -> None:
        self.__rotate = rotate

    async def rotate(
        self,
        reason: str,
        *,
        actor_user_id: UUID,
        client_ref: UUID,
        client_body_sha256: str,
        export_running: Callable[[], bool],
    ) -> tuple[Rotation, bool]:
        """The rotation's answer and whether it is a repeat, after the module docstring's steps;
        else `ExportKeyRotationError`: a refusal rotated nothing, and a `503` may be sent again."""
        call = (reason, actor_user_id, client_ref, client_body_sha256, export_running)
        return await self.__rotate(*call)
