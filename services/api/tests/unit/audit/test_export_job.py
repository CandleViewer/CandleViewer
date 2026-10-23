"""The signed export's job (#889 S10, `audit/export_job.py`): the plan as of the chain head, the key
id taken from the directory alone (S7's re-check, A7), the file written then its digest signed,
each failure as 22's `Job.error` with its file removed; and through M2's signer as `admin.wiring`
mints it, the record before the signature, a record that fails, and a span that straddles a
rotation. An in-memory read port, an in-memory key store, a test KEK and keys made in-process:
no database, no network, no sleeps."""

from __future__ import annotations

import base64
import errno
import gzip
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import GENESIS, FakeAuditRepository
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from structlog.testing import capture_logs

from candleviewer.admin.wiring import SecretsBundle, secrets_bundle
from candleviewer.audit import export_job
from candleviewer.audit.export import EXPORT_DIR
from candleviewer.audit.export_job import (
    JOB_ERRORS,
    ExportJobFailed,
    ExportRequest,
    ExportSettings,
    SignedExport,
    plan_export,
    run_export,
)
from candleviewer.audit.export_signing import SIGNING_FAILURES, ExportSigningFailed, SigningKey
from candleviewer.audit.query import AuditQueryService
from candleviewer.secrets import export_signer as m2_signer
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryExportKeyStore
from candleviewer.settings import Environment
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, AuditLog

_FROM, _TO = datetime(2026, 10, 21, 12, tzinfo=UTC), datetime(2026, 10, 21, 13, tzinfo=UTC)
_JOB, _OWNER = uuid.UUID(int=0xA1), uuid.UUID(int=0xB2)
_SIGNED = "security.audit_export_signed"
_REQUEST = ExportRequest(_FROM, _TO, compressed=True)


def _record(n: int, ts: str) -> dict[str, Any]:
    return {
        "record_id": f"00000000-0000-4000-8000-{n:012d}", "actor_label": "system",
        "action": "auth.login", "outcome": "success", "severity": "info", "event_ts": ts,
    }  # fmt: skip


async def _chain(*stamps: str) -> FakeAuditRepository:
    repo = FakeAuditRepository()
    for n, ts in enumerate(stamps, 1):
        await repo.insert(_record(n, ts))
    return repo


#: Before the window, at `from`, at `to` (out of it), then inside it again: a span of 2 to 4.
_STAMPS = ("11:59:59", "12:00:00", "13:00:00", "12:30:00")


async def _window() -> FakeAuditRepository:
    return await _chain(*(f"2026-10-21T{ts}+00:00" for ts in _STAMPS))


def _key(private: Ed25519PrivateKey) -> SigningKey:
    raw = private.public_key().public_bytes_raw()
    fingerprint = hashlib.sha256(raw).hexdigest()
    return SigningKey(f"cv-audit-export-v1:{fingerprint[:16]}", raw, fingerprint)


class _Keys:
    """A directory naming `key`, counting its reads."""

    def __init__(self, key: SigningKey | None) -> None:
        self.key, self.reads = key, 0

    async def active(self) -> SigningKey | None:
        self.reads += 1
        return self.key

    async def listing(self) -> list[dict[str, Any]] | None:
        return None


class _Signer:
    """Signs the 83-byte message with `private`, recording each call; refuses with `refuse`."""

    def __init__(self, private: Ed25519PrivateKey, refuse: str | None = None) -> None:
        self.private, self.refuse = private, refuse
        self.calls: list[tuple[str, bytes, uuid.UUID, uuid.UUID]] = []

    async def sign_audit_export(
        self, key_id: str, digest: bytes, job_id: uuid.UUID, actor_user_id: uuid.UUID
    ) -> bytes:
        self.calls.append((key_id, digest, job_id, actor_user_id))
        if self.refuse is not None:
            raise ExportSigningFailed(self.refuse)
        return self.private.sign(b"cv.audit.export.v1:" + digest.hex().encode())


def _settings(root: Path, **limits: int) -> ExportSettings:
    return ExportSettings(environment=Environment.DEMO, data_dir=root, **limits)


def _left(root: Path) -> list[str]:
    folder = root / EXPORT_DIR
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


async def _failed(*call: Any, **kw: Any) -> ExportJobFailed:
    with pytest.raises(ExportJobFailed) as failed:
        await run_export(*call, **kw)
    assert (failed.value.__cause__, failed.value.__context__) == (None, None)
    return failed.value


def test_the_jobs_codes_are_22s_job_error_for_an_export() -> None:
    codes = {"export_too_large", "signing_key_rotated", "signing_unavailable", "audit_unavailable"}
    assert JOB_ERRORS == codes | {"internal_error"} and SIGNING_FAILURES < JOB_ERRORS
    with pytest.raises(ValueError, match="not an audit export job error"):
        ExportJobFailed("TimeoutError")


async def test_the_plan_is_the_windows_span_as_of_the_head_with_its_anchor() -> None:
    """22 **Content**: from the first to the last entry in `[from, to)` up to the head read when
    the job starts, an entry inside the span but out of the window included; an entry written
    after the head is read is not."""
    repo, key = await _window(), _key(Ed25519PrivateKey.generate())
    span = repo.export_span

    async def written_meanwhile(**kw: Any) -> tuple[int, int, str] | None:
        await repo.insert(_record(9, "2026-10-21T12:15:00+00:00"))  # after the head was read
        return await span(**kw)

    repo.export_span = written_meanwhile  # type: ignore[method-assign]  # a write in between
    plan = await plan_export(repo, _REQUEST, environment=Environment.LIVE, key=key)
    first, head = repo.rows[1], repo.rows[3]
    assert (plan.first_id, plan.last_id, plan.anchor_hash) == (2, 4, first["prev_hash"])
    assert (plan.head_id, plan.head_hash) == (4, head["entry_hash"]) and len(repo.rows) == 5
    assert (plan.key_id, base64.b64decode(plan.public_key)) == (key.key_id, key.public_key)
    assert (plan.environment, plan.compressed) == (Environment.LIVE, True)


async def test_an_empty_window_is_an_empty_span_and_an_empty_log_a_genesis_head() -> None:
    key = _key(Ed25519PrivateKey.generate())
    later = ExportRequest(_TO.replace(hour=14), datetime(2026, 10, 22, tzinfo=UTC), False)
    plan = await plan_export(await _window(), later, environment=Environment.DEMO, key=key)
    assert (plan.first_id, plan.last_id, plan.anchor_hash, plan.head_id) == (None, None, None, 4)
    empty = await plan_export(FakeAuditRepository(), later, environment=Environment.DEMO, key=key)
    assert (empty.head_id, empty.head_hash, empty.first_id) == (0, GENESIS, None)


async def test_the_job_signs_the_files_digest_with_the_key_the_directory_names(
    tmp_path: Path,
) -> None:
    """A7: the directory is the one source of the key id the header names and the signer is
    given; the digest is the file's as written, and the signature verifies over 24 §15.7's
    message. Through `AuditQueryService.export`, over its own repository."""
    private = Ed25519PrivateKey.generate()
    keys, signer = _Keys(_key(private)), _Signer(private)
    query = AuditQueryService(await _window())
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    done = await query.export(_REQUEST, signer, keys, **call)
    assert isinstance(done, SignedExport) and keys.reads == 1
    data = (tmp_path / EXPORT_DIR / done.file.name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == done.file.sha256 and done.file.row_count == 3
    header = json.loads(gzip.decompress(data).split(b"\n", 1)[0])
    named = (header["key_id"], base64.b64decode(header["public_key"]))
    assert named == (keys.key.key_id, keys.key.public_key)  # type: ignore[union-attr]
    assert signer.calls == [(header["key_id"], bytes.fromhex(done.file.sha256), _JOB, _OWNER)]
    message = b"cv.audit.export.v1:" + done.file.sha256.encode()
    private.public_key().verify(done.signature, message)


async def test_no_key_named_fails_the_job_before_any_read_or_write(tmp_path: Path) -> None:
    repo, signer = await _window(), _Signer(Ed25519PrivateKey.generate())
    reads = repo.export_calls

    async def no_head() -> None:
        raise AssertionError("no read before a key is named")

    repo.read_head = no_head  # type: ignore[method-assign]
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    failed = await _failed(repo, signer, _Keys(None), _REQUEST, **call)
    nothing: tuple[list[Any], ...] = ([], [], [])
    assert (failed.code, (signer.calls, reads, _left(tmp_path))) == ("signing_unavailable", nothing)


async def test_a_span_over_the_row_cap_fails_export_too_large_with_nothing_on_disk(
    tmp_path: Path,
) -> None:
    private = Ed25519PrivateKey.generate()
    signer, settings = _Signer(private), _settings(tmp_path, max_rows=2)
    call = {"job_id": _JOB, "owner": _OWNER, "settings": settings}
    failed = await _failed(await _window(), signer, _Keys(_key(private)), _REQUEST, **call)
    assert (failed.code, signer.calls, _left(tmp_path)) == ("export_too_large", [], [])


@pytest.mark.parametrize("code", sorted(SIGNING_FAILURES))
async def test_a_signer_refusal_fails_the_job_with_its_code_and_removes_the_file(
    tmp_path: Path, code: str
) -> None:
    """`ExportSigningFailed` is an `AuditError`: it is caught first, so its code is the job's."""
    private = Ed25519PrivateKey.generate()
    signer = _Signer(private, refuse=code)
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    with capture_logs() as logs:
        failed = await _failed(await _window(), signer, _Keys(_key(private)), _REQUEST, **call)
    assert (failed.code, len(signer.calls), _left(tmp_path)) == (code, 1, [])
    assert [(e["event"], e["code"], e["error"]) for e in logs] == [
        ("audit.export.failed", code, None)
    ]  # fmt: skip


async def test_a_read_that_fails_is_an_internal_error_named_by_its_class_alone(
    tmp_path: Path,
) -> None:
    repo, private = await _window(), Ed25519PrivateKey.generate()

    async def timed_out(**_: Any) -> None:
        raise TimeoutError(f"statement over budget under {tmp_path}")

    repo.export_span = timed_out  # type: ignore[method-assign]
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    with capture_logs() as logs:
        failed = await _failed(repo, _Signer(private), _Keys(_key(private)), _REQUEST, **call)
    assert failed.code == "internal_error" and str(tmp_path) not in repr((failed, logs))
    assert [(e["event"], e["error"]) for e in logs] == [("audit.export.failed", "TimeoutError")]


async def test_a_file_that_cannot_be_removed_is_logged_by_its_errno_and_left_to_the_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*_: Any) -> None:
        raise PermissionError(errno.EACCES, "denied", str(tmp_path))

    monkeypatch.setattr(export_job, "remove_exports", refused)
    private = Ed25519PrivateKey.generate()
    signer = _Signer(private, refuse="signing_unavailable")
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    with capture_logs() as logs:
        failed = await _failed(await _window(), signer, _Keys(_key(private)), _REQUEST, **call)
    assert failed.code == "signing_unavailable" and len(_left(tmp_path)) == 1
    discard = [e for e in logs if e["event"] == "audit.export.discard_failed"]
    assert discard == [{"event": "audit.export.discard_failed", "errno": "EACCES",
                        "log_level": "warning"}]  # fmt: skip


# -- through M2's signer and directory, as `admin.wiring` mints them --------------------------


async def _m2() -> tuple[SecretsBundle, InMemoryExportKeyStore, AuditLog]:
    keys, audit = InMemoryExportKeyStore(), AuditLog()
    svc = _svc(_Src(KEK_V1, 1), audit=audit, auth_keys=InMemoryAuthKeyStore(), export_keys=keys)
    await svc.start(_ctx())
    return secrets_bundle(svc), keys, audit


async def test_through_m2_the_record_names_the_job_the_owner_and_the_digest_before_it_signs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 7: M2's `security.audit_export_signed` is written before the signature is made,
    naming this job, its Owner, the file's digest and the key the directory named."""
    bundle, keys, audit = await _m2()
    sign = m2_signer.sign_export

    def spied(*args: Any, **kw: Any) -> bytes:
        assert audit.actions()[-1] == _SIGNED  # the record is in before any signature
        return sign(*args, **kw)

    monkeypatch.setattr(m2_signer, "sign_export", spied)
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    done = await run_export(await _window(), bundle.export_signer, bundle.signing_keys,
                            _REQUEST, **call)  # fmt: skip
    row, (action, fields) = keys.rows[0], audit.records[-1]
    assert (action, fields["job_id"], fields["actor_user_id"]) == (_SIGNED, str(_JOB), str(_OWNER))
    named = (fields["sha256"], fields["key_id"], fields["fingerprint_sha256"])
    assert named == (done.file.sha256, row["key_id"], row["fingerprint_sha256"])
    message = b"cv.audit.export.v1:" + done.file.sha256.encode()
    Ed25519PublicKey.from_public_bytes(row["public_key"]).verify(done.signature, message)


async def test_through_m2_a_record_that_cannot_be_written_fails_the_job_unsigned(
    tmp_path: Path,
) -> None:
    bundle, _, audit = await _m2()
    audit.fail = True
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    repo = await _window()
    failed = await _failed(repo, bundle.export_signer, bundle.signing_keys, _REQUEST, **call)
    assert (failed.code, _left(tmp_path)) == ("audit_unavailable", [])
    assert _SIGNED not in audit.actions()


async def test_through_m2_a_span_that_straddles_a_rotation_fails_the_job_unsigned(
    tmp_path: Path,
) -> None:
    """A rotation that ran anyway between the plan and the signature (the `409`s keep one out in
    both directions): the header names the retired key, so M2 refuses before its record."""
    bundle, keys, audit = await _m2()
    repo, fetch = await _window(), FakeAuditRepository.fetch_export_batch

    async def rotated_meanwhile(**kw: Any) -> list[tuple[Any, ...]]:
        if keys.rows[0]["status"] == "active":
            await bundle.signing_key_rotator.rotate(
                "scheduled", actor_user_id=_OWNER, client_ref=uuid.uuid4(),
                client_body_sha256="b" * 64, export_running=lambda: False,
            )  # fmt: skip
        return await fetch(repo, **kw)

    repo.fetch_export_batch = rotated_meanwhile  # type: ignore[method-assign]
    call = {"job_id": _JOB, "owner": _OWNER, "settings": _settings(tmp_path)}
    failed = await _failed(repo, bundle.export_signer, bundle.signing_keys, _REQUEST, **call)
    assert (failed.code, _left(tmp_path), keys.rows[1]["status"]) == (
        "signing_key_rotated", [], "active"
    )  # fmt: skip
    assert _SIGNED not in audit.actions()
