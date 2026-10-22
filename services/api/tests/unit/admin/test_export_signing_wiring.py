"""The audit export signer and key directory as `admin.wiring` mints them (#889 S6b): `audit`'s
ports over M2's, an M2 refusal leaving as the job's code (22 `Job.error`), nothing chained."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from candleviewer.admin.wiring import SecretsBundle, secrets_audit_row, secrets_bundle
from candleviewer.audit.export_signing import SIGNING_FAILURES, ExportSigningFailed, SigningKey
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryExportKeyStore
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, AuditLog

DIGEST = hashlib.sha256(b"an audit export file").digest()
SIGNED = "security.audit_export_signed"
MESSAGE = b"cv.audit.export.v1:" + DIGEST.hex().encode()


async def _bundle() -> tuple[SecretsBundle, Any, InMemoryExportKeyStore, AuditLog]:
    keys, audit = InMemoryExportKeyStore(), AuditLog()
    svc = _svc(_Src(KEK_V1, 1), audit=audit, auth_keys=InMemoryAuthKeyStore(), export_keys=keys)
    await svc.start(_ctx())
    return secrets_bundle(svc), svc, keys, audit


async def test_the_job_signs_with_the_key_the_directory_names() -> None:
    bundle, _, keys, _ = await _bundle()
    key, row = await bundle.signing_keys.active(), keys.rows[0]
    assert key == SigningKey(row["key_id"], row["public_key"], row["fingerprint_sha256"])
    signature = await bundle.export_signer.sign_audit_export(key.key_id, DIGEST, uuid4(), uuid4())
    Ed25519PublicKey.from_public_bytes(key.public_key).verify(signature, MESSAGE)


#: An M2 refusal, how to cause it, and the job's code it leaves as.
REFUSED: dict[str, tuple[dict[str, Any], str, str]] = {
    "rotated": ({"key_id": "cv-audit-export-v9:" + "0" * 16}, "", "signing_key_rotated"),
    "malformed": ({"digest": DIGEST[:31]}, "", "internal_error"),
    "audit_down": ({}, "audit_down", "audit_unavailable"),
    "no_kek": ({}, "stopped", "signing_unavailable"),
    "unopenable": ({}, "damaged", "signing_unavailable"),  # a signer failure after its record
}


@pytest.mark.parametrize(("change", "process", "code"), REFUSED.values(), ids=list(REFUSED))
async def test_an_m2_refusal_leaves_as_the_jobs_code(
    change: dict[str, Any], process: str, code: str
) -> None:
    bundle, svc, keys, audit = await _bundle()
    if process == "audit_down":
        audit.fail = True
    elif process == "stopped":
        await svc.stop(1.0)
    elif process == "damaged":
        keys.rows[0]["sealed_seed"] = bytes(60)
    call = {"key_id": keys.rows[0]["key_id"], "digest": DIGEST} | change
    with pytest.raises(ExportSigningFailed) as failed:
        await bundle.export_signer.sign_audit_export(job_id=uuid4(), actor_user_id=uuid4(), **call)
    raised = failed.value
    assert (raised.code, raised.__context__, raised.__cause__) == (code, None, None)
    assert code in SIGNING_FAILURES


async def test_the_directory_names_no_key_while_export_is_unavailable() -> None:
    bundle, svc, _, _ = await _bundle()
    await svc.stop(1.0)
    assert await bundle.signing_keys.active() is None


def test_a_code_that_is_not_the_jobs_is_refused() -> None:
    with pytest.raises(ValueError, match="not an audit export signing failure code"):
        ExportSigningFailed("export_key_unavailable")


async def test_the_signers_records_are_registered_and_kept_whole() -> None:
    """SR-E42-11: both records, as the signer writes them, through the audit row builder: the
    key's object, the Owner as the actor, every member kept (24 Sec.15.7's cross-check)."""
    bundle, _, keys, audit = await _bundle()
    key_id, owner = keys.rows[0]["key_id"], uuid4()
    await bundle.export_signer.sign_audit_export(key_id, DIGEST, uuid4(), owner)
    keys.rows[0]["sealed_seed"] = bytes(60)
    with pytest.raises(ExportSigningFailed):
        await bundle.export_signer.sign_audit_export(key_id, DIGEST, uuid4(), owner)
    written = audit.records[-3:]  # signed; then signed and its failure
    assert [a for a, _ in written] == [SIGNED, SIGNED, SIGNED.replace("signed", "sign_failed")]
    for action, fields in written:
        row = secrets_audit_row("demo")(action, fields)
        assert (row["object_kind"], row["object_id"], row["actor_user_id"]) == (
            "audit_signing_key", key_id, str(owner)
        )  # fmt: skip
        assert (row["severity"], row["after_state"]) == ("info", fields)
