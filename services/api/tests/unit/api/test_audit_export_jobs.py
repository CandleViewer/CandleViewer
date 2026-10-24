"""The export's job on the API side (#889 S10, `api/audit_exports.py`), driven with no route: what
`exportAuditLog` submits. A job runs `AuditQueryService.export` with the injected `ExportSigning`
and holds the validated manifest once its completion's `admin.audit_export` is written; a failed
job's completion names its code, and an unwritten completion fails it `audit_unavailable` with its
file removed. `reserve` is the single-flight both ways, `replayed` a key's `202`, and `unavailable`
why export is refused. An in-memory chain and job store, `tmp_path` and keys made in-process: no
database, no network, no sleeps."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.audit_exports import AuditExports, ExportSigning
from candleviewer.api.idempotency import IdempotencyKeyReuse
from candleviewer.api.recorder_admin import AUDIT_EXPORT, AdminJobStore, Job, JobConflict
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.export import EXPORT_DIR
from candleviewer.audit.export_job import ExportRequest
from candleviewer.audit.export_signing import ExportSigningFailed, SigningKey
from candleviewer.audit.query import AuditQueryService
from candleviewer.settings import Environment
from tests.unit.audit.audit_fakes import FakeAuditRepository

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
OWNER = AuditPrincipal(uuid.UUID(int=1), "owner", frozenset({"audit:export"}), is_owner=True)
_ASKED = ExportRequest(NOW - timedelta(hours=1), NOW, compressed=True)


def key_of(private: Ed25519PrivateKey) -> SigningKey:
    raw = private.public_key().public_bytes_raw()
    fingerprint = hashlib.sha256(raw).hexdigest()
    return SigningKey(f"cv-audit-export-v1:{fingerprint[:16]}", raw, fingerprint)


class Keys:
    """A directory naming `key`, or none while it is None."""

    def __init__(self, key: SigningKey | None) -> None:
        self.key = key

    async def active(self) -> SigningKey | None:
        return self.key

    async def listing(self) -> list[dict[str, Any]] | None:
        return None


class Signer:
    """Signs the 83-byte message with `private` once `gate` is open, refuses with `refuse`, or
    while `garbled` answers no bytes at all, a defect the manifest cannot be built from."""

    def __init__(self, private: Ed25519PrivateKey) -> None:
        self.private, self.gate, self.refuse, self.garbled = private, asyncio.Event(), "", False
        self.gate.set()

    async def sign_audit_export(self, key_id: str, digest: bytes, *_: Any) -> bytes:
        await self.gate.wait()
        if self.refuse:
            raise ExportSigningFailed(self.refuse)
        if self.garbled:
            return "garbled"  # type: ignore[return-value]  # the defect under test
        return self.private.sign(b"cv.audit.export.v1:" + digest.hex().encode())


class Jobs(AdminJobStore):
    """The job store, keeping each job's task, so a test awaits its end."""

    def __init__(self) -> None:
        super().__init__()
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def submit(self, *args: Any, **kw: Any) -> Job:
        job = super().submit(*args, **kw)
        self.tasks[job.id] = self._tasks[job.id]
        return job

    async def settled(self, job_id: str) -> Job:
        await asyncio.wait({self.tasks[job_id]})
        job = self.get(job_id)
        assert job is not None
        return job


async def seed(repo: FakeAuditRepository, day: str = "2026-10-22") -> None:
    """Before the window, at its start, at its end (out of it), then in it again: a span of 2-4."""
    for n, ts in enumerate(("10:59:59", "11:00:00", "12:00:00", "11:30:00"), 1):
        await repo.insert({
            "record_id": f"00000000-0000-4000-8000-{n:012d}", "actor_label": "system",
            "action": "auth.login", "outcome": "success", "severity": "info",
            "event_ts": f"{day}T{ts}+00:00",
        })  # fmt: skip


class _Rig:
    """An `AuditExports` with its signing, over a seeded chain; `records` the writer's, `fail` a
    record reason it refuses, `rotating` the running rotation's read."""

    def __init__(self, root: Path) -> None:
        private = Ed25519PrivateKey.generate()
        self.signer, self.keys, self.jobs = Signer(private), Keys(key_of(private)), Jobs()
        self.records, self.fail, self.rotating, self.root = list[Any](), "", False, root
        self.repo = FakeAuditRepository()
        self.query = AuditQueryService(self.repo)
        signing = ExportSigning(
            signer=self.signer, keys=self.keys, rotating=lambda: self.rotating,
            environment=Environment.DEMO, max_rows=1000, max_bytes=1 << 20,
        )  # fmt: skip
        self.exports = AuditExports(self.jobs, root, ttl_s=86_400, clock=lambda: NOW,
                                    signing=signing)  # fmt: skip

    async def emit(self, action: str, **fields: Any) -> None:
        if fields.get("reason") == self.fail:
            raise OSError("audit WAL unavailable")
        self.records.append((action, fields))

    def submit(self, key: uuid.UUID | None = None, digest: str = "d" * 64) -> Job:
        fields = {"object_kind": "audit_export"}
        call = {"job_id": uuid.uuid4(), "key": key, "digest": digest}
        return self.exports.submit(self.query, self.emit, fields, OWNER, _ASKED, **call)


@pytest.fixture
async def rig(tmp_path: Path) -> Any:
    made = _Rig(tmp_path)
    await seed(made.repo)
    yield made
    made.query.close()


async def test_a_job_holds_the_validated_manifest_once_its_completion_is_written(
    rig: _Rig,
) -> None:
    """22 `AuditExportResult`: the download, the file's digest and size as written, the signature
    over 24 §15.7's message with the directory's key, the window, the span and `expires_at`, the
    TTL from the job's end; the completion names the job, the window, the span and the digest."""
    job = await rig.jobs.settled(rig.submit().id)
    result: dict[str, Any] = job.result or {}
    manifest = api.AuditExportResult.model_validate(result)
    data = (rig.root / EXPORT_DIR / f"{job.id}.ndjson.gz").read_bytes()
    assert (manifest.sha256, manifest.size_bytes) == (hashlib.sha256(data).hexdigest(), len(data))
    assert manifest.download_url == f"/api/v1/admin/audit/exports/{job.id}"
    key = rig.keys.key
    assert key is not None
    assert (manifest.key_id, manifest.public_key) == (
        key.key_id, base64.b64encode(key.public_key).decode()
    )  # fmt: skip
    message = f"cv.audit.export.v1:{manifest.sha256}".encode()
    rig.signer.private.public_key().verify(base64.b64decode(manifest.signature), message)
    span = (manifest.first_id, manifest.last_id, manifest.row_count, manifest.compressed)
    assert span == (2, 4, 3, True) and manifest.expires_at == NOW + timedelta(days=1)
    assert (manifest.from_, manifest.to) == (_ASKED.from_ts, _ASKED.to_ts)
    [(action, done)] = rig.records
    assert (action, done["reason"], done["object_kind"]) == (
        "admin.audit_export", "completed", "audit_export"
    )  # fmt: skip
    window = {"job_id": job.id, "from": "2026-10-22T11:00:00Z", "to": "2026-10-22T12:00:00Z"}
    named = ("first_id", "last_id", "row_count", "sha256", "size_bytes", "key_id", "compressed")
    assert done["after_state"] == window | {name: result[name] for name in named}
    assert job.requester == str(OWNER.user_id)  # the requester rule's key (S9's helper)


@pytest.mark.parametrize(
    ("refuse", "fail", "error"),
    [
        ("signing_key_rotated", "", "signing_key_rotated"),
        ("", "completed", "audit_unavailable"),
        ("garbled", "", "internal_error"),  # a manifest that cannot be built is never served
    ],
    ids=["signer", "completion_unwritten", "manifest_invalid"],
)
async def test_a_failed_job_leaves_no_file_and_its_completion_names_its_code(
    rig: _Rig, refuse: str, fail: str, error: str
) -> None:
    rig.signer.garbled = refuse == "garbled"
    rig.signer.refuse, rig.fail = "" if rig.signer.garbled else refuse, fail
    job = await rig.jobs.settled(rig.submit().id)
    assert (job.status, job.error, job.result) == ("failed", error, None)
    assert list((rig.root / EXPORT_DIR).iterdir()) == []
    _, failed = rig.records[-1]
    assert (failed["reason"], failed["after_state"]["error"]) == ("failed", error)


async def test_the_hold_refuses_another_export_and_a_rotation_until_released(rig: _Rig) -> None:
    """22 single-flight: what `rotateAuditSigningKey` reads (`ensure_free`) refuses while an
    export holds its place before its job exists, as it does while the job is queued or running;
    and no export takes the place while a rotation runs."""
    release = rig.exports.reserve()
    for refused in (lambda: rig.jobs.ensure_free(AUDIT_EXPORT), rig.exports.reserve):
        with pytest.raises(JobConflict):
            refused()
    release()
    rig.jobs.ensure_free(AUDIT_EXPORT)
    rig.rotating = True
    with pytest.raises(JobConflict):
        rig.exports.reserve()
    rig.jobs.ensure_free(AUDIT_EXPORT)  # a refused hold holds nothing


async def test_a_key_answers_its_own_job_for_its_own_request_alone(rig: _Rig) -> None:
    key, other = uuid.uuid4(), "e" * 64
    assert rig.exports.replayed("owner", key, "d" * 64) is None
    job = await rig.jobs.settled(rig.submit(key).id)  # one at a time
    unkeyed = await rig.jobs.settled(rig.submit(None).id)
    assert rig.exports.replayed(str(OWNER.actor_id), key, "d" * 64) == job.id
    with pytest.raises(IdempotencyKeyReuse):
        rig.exports.replayed(str(OWNER.actor_id), key, other)
    assert rig.exports.replayed(str(uuid.UUID(int=2)), key, "d" * 64) is None  # another Owner's
    assert rig.exports.replayed(str(OWNER.actor_id), uuid.UUID(unkeyed.id), "d" * 64) is None


async def test_export_is_unavailable_with_no_signing_no_key_or_no_hard_links(rig: _Rig) -> None:
    rig.exports.links_ok = True  # as the boot probe leaves a volume that takes hard links
    assert await rig.exports.unavailable() is None
    rig.exports.links_ok = False
    assert await rig.exports.unavailable() == "export_volume_unavailable"
    rig.keys.key = None
    assert await rig.exports.unavailable() == "signing_unavailable"
    unwired = AuditExports(rig.jobs, rig.root, ttl_s=86_400)
    assert await unwired.unavailable() == "signing_unavailable"
    with pytest.raises(JobConflict):  # and it schedules nothing
        unwired.submit(rig.query, rig.emit, {}, OWNER, _ASKED, job_id=uuid.uuid4(), key=None,
                       digest="d" * 64)  # fmt: skip
    assert rig.jobs.held() == 0
