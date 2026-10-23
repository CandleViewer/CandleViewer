"""The audit export signer and its key directory (#889 S6b; ADR-0039 decisions 3, 4 and 7;
SR-E42-15): its checks in order, each refusal before any decrypt or record, and its two records.
Every key is generated in-process or is an RFC 8032 Sec.7.1 vector (C-13.5)."""

from __future__ import annotations

import asyncio
import hashlib
import traceback
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from structlog.testing import capture_logs

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _export_key
from candleviewer.secrets import _metrics as m
from candleviewer.secrets import export_signer as signer
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.errors import CredentialUnavailable, KekUnavailable, SecretsError
from candleviewer.secrets.export_signer import ExportSigner, SigningKeys
from candleviewer.secrets.service import mint_export_signer, mint_signing_keys
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryExportKeyStore
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, RFC8032, AuditLog, kek
from tests.unit.credentials_m2.test_export_key_store import GENERATED

DIGEST = hashlib.sha256(b"an audit export file").digest()
JOB, OWNER = uuid4(), uuid4()
#: The 83 bytes a signature over DIGEST covers (24 Sec.15.7), written out independently.
MESSAGE = b"cv.audit.export.v1:" + DIGEST.hex().encode()


class _Booted:
    """A demo process booted under KEK v1, its signer and directory minted as wiring mints them."""

    def __init__(self, keys: InMemoryExportKeyStore) -> None:
        self.keys, self.audit = keys, AuditLog()
        self.svc = _svc(_Src(KEK_V1, 1), audit=self.audit, auth_keys=InMemoryAuthKeyStore(),
                        export_keys=keys)  # fmt: skip
        self.signer, self.directory = mint_export_signer(self.svc), mint_signing_keys(self.svc)

    async def start(self) -> _Booted:
        await self.svc.start(_ctx())
        self.booted, self.key = len(self.audit.records), self.keys.rows[-1]
        return self

    def written(self) -> list[tuple[str, dict[str, str]]]:
        return self.audit.records[self.booted :]  # what the signer wrote, after the boot's

    async def sign(self, **change: Any) -> bytes:
        call = {"key_id": self.key["key_id"], "digest": DIGEST, "job_id": JOB} | change
        return await self.signer.sign_audit_export(actor_user_id=OWNER, **call)


async def _booted(keys: InMemoryExportKeyStore | None = None) -> _Booted:
    return await _Booted(keys or InMemoryExportKeyStore()).start()


async def _down(*_: object) -> Any:
    raise RuntimeError("store down")


async def _unavailable(b: _Booted, process: str) -> None:
    """After a good boot: no KEK, no active key, a key found unusable, no store or no audit."""
    if process == "stopped":
        await b.svc.stop(1.0)
    elif process == "retired":
        b.key["status"] = "retired"
    elif process == "unopenable":
        b.svc._export_reason = "export_key_unopenable"  # what a boot whose check failed sets
    elif process == "unreadable":
        setattr(b.keys, "active", _down)  # noqa: B010 -- the store cannot be read
    elif process == "audit_down":
        b.audit.fail = True


def _unwraps(monkeypatch: pytest.MonkeyPatch) -> list[bytearray]:
    """Each export DEK unwrapped from now on: the decrypt no refusal may reach."""
    seen, unwrap = [], LoadedKek.unwrap_export_dek

    def spied(self: LoadedKek, ref: str, *, key_id: str) -> bytearray:
        seen.append(unwrap(self, ref, key_id=key_id))
        return seen[-1]

    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", spied)
    return seen


async def test_the_record_is_written_before_the_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """The write-ahead spy: when `sign_export` runs, its record is already written, naming the
    job, the Owner, the digest and the key (24 Sec.15.7's chain cross-check)."""
    b, at_sign, sign = await _booted(), [], signer.sign_export

    def spied(*args: Any, **kw: Any) -> bytes:
        at_sign.append(list(b.written()))
        return sign(*args, **kw)

    monkeypatch.setattr(signer, "sign_export", spied)
    deks, signature = _unwraps(monkeypatch), await b.sign()
    assert [bytes(dek) for dek in deks] == [bytes(32)]  # the one DEK opened, zeroed after use
    owner = {"actor_kind": "user", "actor_role": "owner", "actor_user_id": str(OWNER)}
    named = {"job_id": str(JOB), "env": "demo", "sha256": DIGEST.hex(), "key_id": b.key["key_id"]}
    record = (signer.SIGNED, owner | named | {"fingerprint_sha256": b.key["fingerprint_sha256"]})
    assert at_sign == [[record]] == [b.written()]
    Ed25519PublicKey.from_public_bytes(b.key["public_key"]).verify(signature, MESSAGE)


#: Each refusal before any decrypt or record: the call's change, the process, the code.
REFUSED: dict[str, tuple[dict[str, Any], str, str]] = {
    "digest_31": ({"digest": DIGEST[:31]}, "", "export_request_invalid"),
    "digest_hex": ({"digest": DIGEST.hex()}, "", "export_request_invalid"),
    "key_id_malformed": ({"key_id": "cv-audit-export-v1:XYZ"}, "", "export_request_invalid"),
    "key_id_not_str": ({"key_id": None}, "", "export_request_invalid"),
    "job_not_a_uuid": ({"job_id": "job-1"}, "", "export_request_invalid"),
    "job_not_str": ({"job_id": 7}, "", "export_request_invalid"),
    "not_the_active_key": ({"key_id": "cv-audit-export-v9:" + "0" * 16}, "", "signing_key_rotated"),
    "no_kek": ({}, "stopped", "kek_unavailable"),
    "no_active_key": ({}, "retired", "export_key_unavailable"),
    "unusable_at_boot": ({}, "unopenable", "export_key_unavailable"),
    "store_unreadable": ({}, "unreadable", "export_key_unavailable"),
    "record_not_written": ({}, "audit_down", "audit_unavailable"),  # and nothing signed
}


@pytest.mark.parametrize(("change", "process", "code"), REFUSED.values(), ids=list(REFUSED))
async def test_a_refusal_comes_before_any_decrypt_or_record(
    change: dict[str, Any], process: str, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = await _booted()
    await _unavailable(b, process)
    unwrapped = _unwraps(monkeypatch)
    with pytest.raises(SecretsError, match=f"^{code}$") as refused:
        await b.sign(**change)
    kind = KekUnavailable if process == "stopped" else CredentialUnavailable
    assert type(refused.value) is kind and refused.value.__context__ is None
    assert (unwrapped, b.written()) == ([], [])


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ({"sealed_seed": bytes(60)}, "credential_unavailable"),
        ({"dek_ref": "ek1:" + "00" * 60}, "credential_unavailable"),
        ({}, "signing_failed"),  # `sign_export`'s own typed refusal
    ],
    ids=["seal", "wrap", "signing"],
)
async def test_a_failure_after_the_record_appends_sign_failed(
    damage: dict[str, Any], code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It leaves typed, `sign_export`'s own code kept, nothing chained, and closes its record."""
    b = await _booted()
    b.key |= damage
    if not damage:
        monkeypatch.setattr(signer, "sign_export", Mock(side_effect=CredentialUnavailable(code)))
    with pytest.raises(CredentialUnavailable, match=f"^{code}$") as failed:
        await b.sign()
    assert failed.value.__context__ is None and failed.value.__cause__ is None
    (signed, fields), closed = b.written()
    assert (signed, closed) == (signer.SIGNED, (signer.SIGN_FAILED, fields | {"reason": code}))


async def test_a_cancelled_signing_propagates_after_its_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b = await _booted()

    def cancelled(*_: object, **__: object) -> bytearray:
        raise asyncio.CancelledError

    monkeypatch.setattr(LoadedKek, "unwrap_export_dek", cancelled)
    with pytest.raises(asyncio.CancelledError) as raised:
        await b.sign()
    frames = list(traceback.walk_tb(raised.value.__traceback__))
    assert frames[-1][0].f_code.co_name == "cancelled" and frames[-1][0].f_locals == {}  # scrubbed
    closing = [(a, f.get("reason")) for a, f in b.written()]
    assert closing == [(signer.SIGNED, None), (signer.SIGN_FAILED, "cancelled")]


async def test_a_closing_record_that_is_lost_is_counted() -> None:
    b = await _booted()
    b.key["sealed_seed"] = bytes(60)

    async def lost(action: str, fields: dict[str, str]) -> None:
        if action == signer.SIGN_FAILED:
            raise RuntimeError("audit down")
        b.audit.records.append((action, dict(fields)))

    setattr(b.svc, "_audit_sink", lost)  # noqa: B010 -- the audit writer fails after the first
    before = m.credential_outcome_audit_failures_total._value.get()
    with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
        await b.sign()
    assert m.credential_outcome_audit_failures_total._value.get() == before + 1


async def test_the_signature_verifies_with_the_active_key_and_no_other() -> None:
    """RFC 8032's TEST 1 as the active key: its signature verifies with TEST 1 alone (C-13.5)."""
    dek, seed = env.new_dek(), bytearray(bytes.fromhex(RFC8032["TEST 1"][0]))
    key = _export_key.seal_seed(dek, seed, env_name="demo", version=1)
    sealed = {"sealed_seed": key.sealed_seed, "public_key": key.public_key, "kek_version": 1}
    sealed["dek_ref"] = kek(KEK_V1, 1).wrap_export_dek(dek, key_id=key.key_id)
    keys, row = InMemoryExportKeyStore(), {"id": uuid4(), "env": "demo", "version": 1}
    assert await keys.insert_first(row | sealed | {"key_id": key.key_id}, audit=GENERATED)
    signature = await (await _booted(keys)).sign()
    test_1, test_2 = (bytes.fromhex(RFC8032[n][1]) for n in ("TEST 1", "TEST 2"))
    Ed25519PublicKey.from_public_bytes(test_1).verify(signature, MESSAGE)
    for public, message in ((test_2, MESSAGE), (test_1, DIGEST)):
        with pytest.raises(InvalidSignature):
            Ed25519PublicKey.from_public_bytes(public).verify(signature, message)


async def test_the_directory_gives_the_active_key_s_public_material_and_no_seed() -> None:
    b = await _booted()
    active = await b.directory.active()
    assert active == (b.key["key_id"], b.key["public_key"], b.key["fingerprint_sha256"])
    usable = await signer._usable(b.keys, (kek(KEK_V2, 2), kek(KEK_V1, 1)))  # a rotation boot's
    assert usable is not None and usable[1].version == 1  # the KEK of the key's own version
    assert b.key["sealed_seed"].hex() not in repr(active) and b.key["dek_ref"] not in repr(active)


@pytest.mark.parametrize("process", ["stopped", "retired", "unopenable", "unreadable"])
async def test_the_directory_answers_none_while_export_is_unavailable(process: str) -> None:
    b = await _booted()
    await _unavailable(b, process)
    assert await b.directory.active() is None


async def test_each_capability_holds_a_closure_only_and_is_m2s() -> None:
    """As `CredentialBorrower`: no `__dict__` to reach the service, no subclass outside M2 (R7)."""
    b = await _booted()
    for capability, kind in ((b.signer, ExportSigner), (b.directory, SigningKeys)):
        assert type(capability) is kind and not hasattr(capability, "__dict__")
        with pytest.raises(TypeError, match="may not be subclassed"):
            type("Sub", (kind,), {})


async def test_no_seed_or_dek_is_in_a_log_a_record_a_failure_or_a_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-12.6: no seed or DEK made here is in a log, record, failure, repr or directory answer."""
    made: list[bytes] = []

    def recorded(make: Any) -> Any:
        def wrapper() -> bytearray:
            out: bytearray = make()
            made.append(bytes(out))
            return out

        return wrapper

    monkeypatch.setattr(env, "new_dek", recorded(env.new_dek))
    monkeypatch.setattr(_export_key, "new_seed", recorded(_export_key.new_seed))
    with capture_logs() as logs:
        b = await _booted()
        signature, active = await b.sign(), await b.directory.active()
        b.key["sealed_seed"] = bytes(60)
        with pytest.raises(CredentialUnavailable) as failed:
            await b.sign()
    seen = repr((logs, b.audit.records, failed.value, b.signer, b.directory, signature, active))
    assert len(made) == 2 and not [s for s in made if s.hex() in seen or repr(s) in seen]


@pytest.mark.parametrize("value", [UUID(int=7), str(UUID(int=7)), str(UUID(int=7)).upper()])
def test_the_job_and_the_owner_are_recorded_as_canonical_uuid_text(value: object) -> None:
    _, _, named = signer.request("cv-audit-export-v1:" + "a" * 16, DIGEST, value, value)
    assert named == {"job_id": str(UUID(int=7)), "actor_user_id": str(UUID(int=7))}
