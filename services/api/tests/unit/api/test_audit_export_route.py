"""`POST /admin/audit/export` served (#889 S10; 22 `exportAuditLog`): its checks in the contract's
order, the forbidden roles and another Owner at each (C-12.4); the request recorded before its job
exists and the completion after; one export at a time and none while a rotation runs, both ways;
the hourly cap and the window's maximum (AC-ADM-20); the replay; the volume without hard links;
and end to end through M2's signer as `admin.wiring` mints it: the file's `sha256sum`, the
manifest's `sha256` and the download's `Repr-Digest` one digest, signed by the pinned key and no
other (AC-ADM-21). A job that fails is `test_audit_export_jobs.py`'s. An in-memory chain, key
store and job store, `tmp_path`, a test KEK and keys made in-process: no database, no network, no
sleeps."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import FastAPI, Request
from structlog.testing import capture_logs

from candleviewer.admin.wiring import secrets_bundle
from candleviewer.api import audit as audit_api
from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_exports import AuditExports, ExportSigning
from candleviewer.api.audit_limiter import AuditVerifyLimiter
from candleviewer.api.recorder_admin import AUDIT_EXPORT, Job, JobConflict
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.query import AuditQueryService
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.secrets._export_custody import GENERATED
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryExportKeyStore
from candleviewer.settings import Environment
from tests.unit.api.test_audit_export_jobs import Jobs, Keys, Signer, key_of, seed
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, RFC8032, AuditLog
from tests.unit.credentials_m2.test_export_signer import _made

_BODY = {"from": "2026-10-22T11:00:00Z", "to": "2026-10-22T12:00:00Z"}  # `seed`'s window
_OWNER = AuditPrincipal(
    uuid.UUID(int=1), "owner", frozenset({"audit:read", "audit:export"}), uuid.UUID(int=101),
    is_owner=True,
)  # fmt: skip
_WHO = {
    "owner": _OWNER,
    "owner2": replace(_OWNER, user_id=uuid.UUID(int=2), session_id=uuid.UUID(int=102)),
    "manager": AuditPrincipal(  # a grant of `audit:export`, but not the Owner
        uuid.UUID(int=3), "m", frozenset({"audit:read", "audit:export"}), uuid.UUID(int=103)
    ),
    "viewer": AuditPrincipal(uuid.UUID(int=4), "v", frozenset(), uuid.UUID(int=104)),
}


class _World:
    """The router over a chain, a job store and `root`; it is the audit service and its writer,
    the session resolver and the step-up service. `records` holds what was written; `fail` names
    a record's reason the writer refuses; `rotating` is the running rotation's read."""

    is_active = step_up_is_active = sessions_is_active = True

    def __init__(self, root: Path, signing: ExportSigning | None = None) -> None:
        private = Ed25519PrivateKey.generate()
        self.signer, self.keys = Signer(private), Keys(key_of(private))
        self.root, self.records, self.fail, self.rotating = root, list[Any](), "", False
        self.repo, self.jobs, self.writer, self.step_up = FakeAuditRepository(), Jobs(), self, self
        self.query = AuditQueryService(self.repo)
        signing = signing or ExportSigning(
            signer=self.signer, keys=self.keys, rotating=lambda: self.rotating,
            environment=Environment.DEMO, max_rows=1000, max_bytes=1 << 20,
        )  # fmt: skip
        self.exports = AuditExports(self.jobs, root, ttl_s=86_400, signing=signing)
        self.exports.links_ok = True  # as the boot probe leaves a volume that takes hard links
        self.starts = AuditVerifyLimiter(rate_per_hour=2, clock=lambda: 0.0)
        self.app = FastAPI()
        self.app.include_router(make_audit_router(
            self, self, exports=self.exports, step_up=self, signing_keys=signing.keys,
            export_limiter=self.starts, export_max_range_days=31,
        ))  # fmt: skip

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        return _WHO.get(request.headers.get("x-who", ""))

    elevated = True  # False: no live `audit` window, so the step-up challenges
    #: A grace window on a fake clock (minutes), when set: elevated only while `now < until`.
    now: float = 0.0
    until: float | None = None

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        if not self.elevated or (self.until is not None and self.now >= self.until):
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> StepUpChallenge:
        return StepUpChallenge(uuid.UUID(int=7), action_class, datetime.now(UTC) + CHALLENGE_WINDOW)

    async def emit(self, action: str, **fields: Any) -> None:
        if fields.get("reason") == self.fail:
            raise OSError("audit WAL unavailable")
        self.records.append((action, fields))

    async def post(
        self, who: str = "owner", body: Any = _BODY, key: str | None = None, raw: bytes = b""
    ) -> httpx.Response:
        headers = {"x-who": who} | ({"idempotency-key": key} if key else {})
        sent: dict[str, Any] = {"content": raw} if raw else {"json": body}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                     base_url="http://t") as client:  # fmt: skip
            return await client.post("/admin/audit/export", headers=headers, **sent)

    async def get(self, job_id: str) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                     base_url="http://t") as client:  # fmt: skip
            return await client.get(f"/admin/audit/exports/{job_id}", headers={"x-who": "owner"})

    async def settled(self, answer: httpx.Response) -> Job:
        return await self.jobs.settled(answer.json()["job_id"])

    def reasons(self) -> list[str]:
        return [fields.get("reason", "") for _, fields in self.records]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path.resolve()  # the download walks the real path, one component at a time


@pytest.fixture
async def world(root: Path) -> Any:
    made = _World(root)
    await seed(made.repo)
    yield made
    made.signer.gate.set()
    await asyncio.gather(*made.jobs.tasks.values())  # every job a test made has ended
    made.query.close()


def _full(world: _World, who: str = "owner") -> None:
    for _ in range(2):
        world.starts.record_start(str(_WHO[who].user_id))


@pytest.mark.parametrize(
    ("who", "passed", "status", "code"),
    [
        ("", 0, 401, "unauthenticated"),
        ("manager", 0, 403, "forbidden"),  # the forbidden roles, before any body is read
        ("viewer", 0, 403, "forbidden"),
        ("owner", 0, 422, "validation_failed"),
        ("owner", 1, 503, "signing_unavailable"),
        ("owner", 2, 429, "rate_limited"),
        ("owner", 3, 409, "conflict"),
        ("owner2", 3, 409, "conflict"),  # another Owner, its own hour: the same single-flight
    ],
)
async def test_each_refusal_comes_in_the_contracts_order(
    world: _World, who: str, passed: int, status: int, code: str
) -> None:
    """Every later check would refuse too (a malformed body, no key named, the hour full, a
    rotation running); the first `passed` are lifted, so each answer pins its check before the
    rest. A forbidden role's refusal names its session; the `429` and `409` record nothing."""
    world.keys.key = world.keys.key if passed >= 2 else None
    if passed < 3:
        _full(world, who if who == "owner2" else "owner")
    world.rotating = True
    answer = await world.post(who, raw=b"" if passed else b"{not json")
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    recorded = {403: ["owner_only"] if who == "manager" else ["missing_permission:audit:export"]}
    recorded[503] = ["signing_unavailable"]
    assert world.reasons() == recorded.get(status, []) and world.jobs.held() == 0
    if status == 403:
        assert world.records[0][1]["session_id"] == _WHO[who].session_id


async def test_an_unelevated_owners_export_is_challenged_restating_the_window(
    world: _World,
) -> None:
    """#2304 slice 3b: the handler's `audit` challenge comes after RBAC and the body, restating
    the validated window; no job, no hold, no record, no quota spent."""
    world.elevated = False
    answer = await world.post(key=str(uuid.uuid4()))
    assert (answer.status_code, answer.json()["code"], answer.json()["action_class"]) == (
        403, "step_up_required", "audit"
    )  # fmt: skip
    window = "2026-10-22T11:00:00+00:00 to 2026-10-22T12:00:00+00:00"
    assert answer.json()["action_summary"] == f"Export the audit log from {window}, compressed"
    assert (world.records, world.jobs.held(), world.jobs.tasks) == ([], 0, {})
    assert answer.headers["cache-control"] == "no-store"
    world.elevated = True
    assert (await world.post()).status_code == 202  # the quota was never spent


async def test_a_replay_needs_a_live_window_and_never_outlives_it(world: _World) -> None:
    """#2304 slice 3b (review): the step-up comes before the idempotency lookup, so the same key
    and body re-sent once the `audit` window has ended on the fake clock get the challenge,
    never the stored `202`; inside a new window they get the replay."""
    key, world.until = str(uuid.uuid4()), 5.0
    first = await world.post(key=key)
    assert first.status_code == 202
    world.now = 6.0  # past the 5-minute window
    resent = await world.post(key=key)
    assert (resent.status_code, resent.json()["code"]) == (403, "step_up_required")
    assert "idempotency-replayed" not in resent.headers
    assert first.json()["job_id"] not in resent.text
    world.until = 11.0  # a new step-up
    again = await world.post(key=key)
    assert (again.status_code, again.headers["idempotency-replayed"]) == (202, "true")


@pytest.mark.parametrize("who", ["manager", "viewer"])
async def test_an_unelevated_forbidden_role_is_the_audited_403_never_a_challenge(
    world: _World, who: str
) -> None:
    world.elevated = False
    answer = await world.post(who)
    assert (answer.status_code, answer.json()["code"], "challenge_id" in answer.json()) == (
        403, "forbidden", False
    )  # fmt: skip
    assert len(world.records) == 1 and world.records[0][0] == "admin.audit_denied"


@pytest.mark.parametrize(
    "body",
    [{"from": "2026-10-22T11:00:00Z"}, {**_BODY, "note": "SENTINEL"}],
    ids=["no-to", "other"],
)
async def test_an_unelevated_owners_invalid_body_is_the_422_never_a_challenge(
    world: _World, body: dict[str, Any]
) -> None:
    world.elevated = False
    answer = await world.post(body=body)
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert "SENTINEL" not in answer.text and world.jobs.held() == 0


async def test_an_export_wired_without_its_step_up_fails_closed(root: Path) -> None:
    """#2304 slice 3b: no step-up service is a wiring fault, 503, never "no step-up needed"."""
    made = _World(root)
    made.app = FastAPI()
    made.app.include_router(make_audit_router(made, made, exports=made.exports))
    answer = await made.post()
    assert (answer.status_code, answer.json()["code"], made.jobs.tasks) == (
        503, "service_unavailable", {}
    )  # fmt: skip
    made.query.close()


async def test_a_429_and_a_409_are_counted_and_carried_by_the_users_next_record(
    world: _World,
) -> None:
    """22: refusals fall under the audit budget as verify's do; the `429` and the `409`s
    (`conflict` and `idempotency_key_reuse`) write no record, and each user's next record
    carries them as `suppressed`."""
    key = str(uuid.uuid4())
    await world.settled(await world.post(key=key))
    reuse = await world.post(key=key, body=_BODY | {"compress": False})
    assert (reuse.status_code, reuse.json()["code"]) == (409, "idempotency_key_reuse")
    _full(world)
    world.rotating = True
    assert [(await world.post(who)).status_code for who in ("owner", "owner2")] == [429, 409]
    world.keys.key = None
    assert [(await world.post(who)).status_code for who in ("owner", "owner2")] == [503, 503]
    carried = [(f["actor_user_id"], f["after_state"]["suppressed"]) for _, f in world.records[2:]]
    assert carried == [(_OWNER.user_id, 2), (_WHO["owner2"].user_id, 1)]


async def test_the_request_is_recorded_before_its_job_exists_and_the_completion_after(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """22 **Audit**: the request's `admin.audit_export` before the job exists, and while it is
    written the hold refuses another export and a rotation (S7 reads `ensure_free`), as the job
    does until its end; then the completion, naming the job, the window, the span, the rows and
    the digest, once the file is signed. The job is its requester's alone (#889 S9-0)."""
    seen, emit = list[Any](), world.emit

    async def watched(action: str, **fields: Any) -> None:
        try:
            world.jobs.ensure_free(AUDIT_EXPORT)
            held = False
        except JobConflict:
            held = True
        seen.append((fields["reason"], world.jobs.held(), held))
        await emit(action, **fields)

    monkeypatch.setattr(world, "emit", watched)
    answer = await world.post()
    assert (answer.status_code, answer.json()["download_url"]) == (202, None)
    job = await world.settled(answer)
    assert seen == [("requested", 0, True), ("completed", 1, True)]  # held until its end
    (_, request), (_, done) = world.records
    window = {"job_id": job.id, "from": _BODY["from"], "to": _BODY["to"]}
    assert (request["object_kind"], request["object_id"]) == ("audit_export", job.id)
    assert request["after_state"] == window | {"compressed": True}
    result: dict[str, Any] = job.result or {}
    spans = ("first_id", "last_id", "row_count", "sha256", "size_bytes", "key_id", "compressed")
    assert done["after_state"] == window | {name: result[name] for name in spans}
    assert (result["first_id"], result["last_id"], result["row_count"]) == (2, 4, 3)
    assert job.requester == str(_OWNER.user_id) and job.hidden_from(_WHO["owner2"])


async def test_a_request_record_unwritten_is_503_with_no_job_and_no_quota_spent(
    world: _World,
) -> None:
    world.fail = "requested"
    world.starts.record_start(str(_OWNER.user_id))  # one of the hour's two used: one is left
    answer = await world.post()
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    assert world.jobs.held() == 0 and world.starts.retry_after(str(_OWNER.user_id)) is None
    world.fail = ""
    assert (await world.post()).status_code == 202  # the hold was released


@pytest.mark.parametrize(
    "error", [RuntimeError("a defect"), asyncio.CancelledError()], ids=["raise", "cancel"]
)
async def test_a_request_record_that_raises_or_is_cancelled_releases_the_hold(
    world: _World, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    """Whatever leaves between the hold and the request's record, a raise or a cancel, releases
    the single-flight (else every rotation is refused until a restart) and spends no hour."""

    async def leaves(*args: Any, **kwargs: Any) -> bool:
        raise error

    monkeypatch.setattr(audit_api, "write_verify_record", leaves)
    world.starts.record_start(str(_OWNER.user_id))  # one of the hour's two used: one is left
    with pytest.raises(type(error)):
        await world.post()
    world.jobs.ensure_free(AUDIT_EXPORT)  # no hold left behind: a rotation may run
    assert world.jobs.held() == 0 and world.starts.retry_after(str(_OWNER.user_id)) is None


async def test_one_export_at_a_time_and_none_while_a_rotation_runs(world: _World) -> None:
    world.signer.gate.clear()  # the first export's job holds at its signature
    first = await world.post()
    second = await world.post("owner2")
    assert (first.status_code, second.status_code, second.json()["code"]) == (202, 409, "conflict")
    world.signer.gate.set()
    await world.settled(first)
    world.rotating = True
    rotating = await world.post()
    assert (rotating.status_code, rotating.json()["code"]) == (409, "conflict")
    world.rotating = False
    assert (await world.post()).status_code == 202 and world.reasons().count("requested") == 2


async def test_only_an_export_whose_job_is_created_counts_toward_the_hour(world: _World) -> None:
    """AC-ADM-20: a third in the test's hour of 2 is `429` with `Retry-After`; a refused request
    spent nothing, and another user's hour is its own."""
    named, world.keys.key = world.keys.key, None
    assert (await world.post()).status_code == 503
    world.keys.key = named
    for _ in range(2):
        await world.settled(await world.post())
    capped = await world.post()
    assert (capped.status_code, capped.json()["code"]) == (429, "rate_limited")
    assert (
        int(capped.headers["Retry-After"]) > 0 and (await world.post("owner2")).status_code == 202
    )


@pytest.mark.parametrize(
    ("body", "key", "field", "rule"),
    [
        ({"from": "2026-09-01T00:00:00Z", "to": "2026-10-02T00:00:00.000001Z"}, None, "to",
         "max_export_range"),
        ({"from": "2026-10-21T13:00:00Z", "to": "2026-10-21T13:00:00Z"}, None, "", "value_error"),
        (_BODY | {"from": "2026-10-21T12:00:00"}, None, "from", "value_error"),  # naive
        (_BODY | {"compress": "yes"}, None, "compress", "bool_type"),
        (_BODY | {"limit": 5}, None, "(unknown)", "extra_forbidden"),
        (_BODY, "not-a-uuid", "Idempotency-Key", "uuid"),
        (_BODY | {"pad": "x" * 1024}, None, "", "max_body_bytes"),  # refused unread past 1 KiB
        ({"from": "0001-01-01T00:00:00+01:00", "to": "0001-01-02T00:00:00+01:00"}, None, "from",
         "value_error"),  # no UTC instant: refused, so no hold is ever taken (and kept) for it
    ],
    ids=["over_31_days", "empty", "naive", "compress", "unknown", "key", "too_long", "no_utc"],
)  # fmt: skip
async def test_a_request_the_contract_refuses_is_422_naming_no_value(
    world: _World, body: dict[str, Any], key: str | None, field: str, rule: str
) -> None:
    answer = await world.post(body=body, key=key)
    assert (answer.status_code, answer.json()["errors"]) == (422, [{"field": field, "rule": rule}])
    assert (world.records, world.jobs.held()) == ([], 0)
    world.jobs.ensure_free(AUDIT_EXPORT)  # no hold left behind: a rotation may run
    if rule == "max_export_range":
        assert "audit_export_max_range_days (31)" in answer.json()["detail"]
        days_31 = {"from": "2026-09-01T00:00:00Z", "to": "2026-10-02T00:00:00Z"}
        assert (await world.post(body=days_31)).status_code == 202


async def test_a_repeated_key_and_body_get_the_same_202_while_every_refusal_would_hold(
    world: _World,
) -> None:
    """22: only the `202` is kept, read before any refusal; another body is a reuse, and another
    Owner's key is never this one's (C-12.4)."""
    world.signer.gate.clear()
    key = str(uuid.uuid4())
    first = await world.post(key=key)
    assert "Idempotency-Replayed" not in first.headers  # a first answer is no replay
    assert first.headers["Cache-Control"] == "no-store"  # as 22's `202` declares it
    world.exports.links_ok = False  # the job, holding at its signature, never reads it
    _full(world)
    again = await world.post(key=key)
    replayed = (again.status_code, again.json(), again.headers.get("Idempotency-Replayed"))
    assert replayed == (202, first.json(), "true")
    reuse = await world.post(key=key, body=_BODY | {"compress": False})
    assert (reuse.status_code, reuse.json()["code"]) == (409, "idempotency_key_reuse")
    other = await world.post("owner2", key=key)
    assert other.status_code == 503 and "Idempotency-Replayed" not in other.headers
    assert world.reasons() == ["requested", "export_volume_unavailable"]
    world.signer.gate.set()
    await world.settled(first)


async def test_a_volume_without_hard_links_refuses_export_with_its_own_reason(
    world: _World,
) -> None:
    world.exports.links_ok = False
    answer = await world.post()
    assert (answer.status_code, answer.json()["code"]) == (503, "signing_unavailable")
    assert "export directory" in answer.json()["detail"]
    assert world.reasons() == ["export_volume_unavailable"] and world.jobs.held() == 0
    world.fail = "export_volume_unavailable"  # a refusal whose record cannot be written
    lost = await world.post()
    assert (lost.status_code, lost.json()["code"], world.jobs.held()) == (
        503,
        "store_unavailable",
        0,
    )


async def test_end_to_end_one_digest_signed_by_the_pinned_key_and_no_other(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0039 Validation, through M2's signer, directory and running rotation as wiring mints
    them: `sha256sum` of the downloaded file, the manifest's `sha256` and the `Repr-Digest` agree;
    the signature over `cv.audit.export.v1:` and that hex verifies with the key whose fingerprint
    was pinned from its generation record, and with no other (a fresh key, RFC 8032 TEST 1's).
    No seed, DEK or file path reaches a response, a log or a record."""
    made = _made(monkeypatch)
    keys, audit = InMemoryExportKeyStore(), AuditLog()
    svc = _svc(_Src(KEK_V1, 1), audit=audit, auth_keys=InMemoryAuthKeyStore(), export_keys=keys)
    await svc.start(_ctx())
    bundle = secrets_bundle(svc)
    (pinned,) = [f["fingerprint_sha256"] for a, f in keys.audit if a == GENERATED]
    signing = ExportSigning(
        signer=bundle.export_signer, keys=bundle.signing_keys,
        rotating=bundle.rotation_running.running, environment=Environment.DEMO, max_rows=1000,
        max_bytes=1 << 20,
    )  # fmt: skip
    world = _World(root, signing)
    await seed(world.repo)
    with capture_logs() as logs:
        answer = await world.post()
        job = await world.settled(answer)
        download = await world.get(job.id)
    world.query.close()
    manifest: dict[str, Any] = job.result or {}
    assert manifest["download_url"] == f"/api/v1/admin/audit/exports/{job.id}"
    served = base64.b64decode(download.headers["Repr-Digest"].removeprefix("sha-256=:")[:-1])
    assert hashlib.sha256(download.content).hexdigest() == manifest["sha256"] == served.hex()
    message, signature = f"cv.audit.export.v1:{manifest['sha256']}".encode(), manifest["signature"]
    public = base64.b64decode(manifest["public_key"])
    assert hashlib.sha256(public).hexdigest() == pinned  # 24 Sec.15.7 step 2: the pin
    Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(signature), message)
    rfc = Ed25519PublicKey.from_public_bytes(bytes.fromhex(RFC8032["TEST 1"][1]))
    for other in (Ed25519PrivateKey.generate().public_key(), rfc):
        with pytest.raises(InvalidSignature):
            other.verify(base64.b64decode(signature), message)
    seen = repr((answer.text, manifest, download.headers, logs, world.records, audit.records))
    assert made and not [m for m in made if m.hex() in seen or repr(m) in seen]
    assert str(root) not in seen + repr(keys.audit)
